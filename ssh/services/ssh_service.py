"""Wrapper around paramiko providing SSH connection and shell pools.

Responsibilities:
  * Own connection, shell, and shell->conn mapping pools.
  * Enforce host key verification (RejectPolicy, no exceptions).
  * Manage authentication priority: key file -> password -> SSH agent.
  * Detect exit codes from interactive shells via unique markers.
  * Log latency for each tool call.
  * Translate paramiko errors into actionable RuntimeError / ValueError.
"""
from __future__ import annotations

import os
import socket
import time
import uuid
from typing import Any, Dict, List, Optional

import paramiko

from config import Config
from logger_setup import get_logger

_SHELL_MARKER = "__MCP_END_{}_{}__"


class SSHService:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._log = get_logger("ssh_mcp.service", cfg.log_level)
        self._connections: Dict[str, paramiko.SSHClient] = {}
        self._shells: Dict[str, paramiko.Channel] = {}
        self._shell_to_conn: Dict[str, str] = {}
        self._log.info("SSHService initialized")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _log_elapsed(self, tool: str, t0: float, **extra: Any) -> None:
        elapsed = time.perf_counter() - t0
        extras = " ".join(f"{k}={v}" for k, v in extra.items() if v is not None)
        self._log.debug("tool=%s elapsed=%.2fs %s", tool, elapsed, extras)

    def _get_connection(self, conn_id: str) -> paramiko.SSHClient:
        if conn_id not in self._connections:
            raise ValueError(f"Connection '{conn_id}' not found. Call ssh_connect first.")
        client = self._connections[conn_id]
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise ValueError(f"Connection '{conn_id}' is no longer active. Reconnect.")
        return client

    def _load_host_keys(
        self, client: paramiko.SSHClient, extra_path: Optional[str]
    ) -> None:
        """Load known_hosts from config paths plus optional custom path.

        At least one known_hosts file must exist or RejectPolicy refuses all hosts.
        Register a new host with: ssh-keyscan -H <host> >> ~/.ssh/known_hosts
        """
        loaded = False
        for raw_path in self._cfg.known_hosts_paths:
            expanded = os.path.expanduser(raw_path)
            if os.path.isfile(expanded):
                client.load_host_keys(expanded)
                loaded = True

        if not loaded:
            try:
                client.load_system_host_keys()
                loaded = True
            except Exception:
                pass

        if extra_path:
            expanded = os.path.expanduser(extra_path)
            if not os.path.isfile(expanded):
                raise FileNotFoundError(f"known_hosts_path not found: {expanded}")
            client.load_host_keys(expanded)
            loaded = True

        if not loaded:
            raise RuntimeError(
                "No known_hosts file found. "
                "Add the host with: ssh-keyscan -H <host> >> ~/.ssh/known_hosts"
            )

    @staticmethod
    def _exec(client: paramiko.SSHClient, command: str, timeout: int) -> Dict[str, Any]:
        """Run a one-shot command. Reads stdout/stderr before recv_exit_status to
        avoid deadlocks when remote buffers fill up."""
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        stdout_data = stdout.read().decode("utf-8", errors="replace")
        stderr_data = stderr.read().decode("utf-8", errors="replace")
        exit_code = stdout.channel.recv_exit_status()
        return {
            "stdout": stdout_data,
            "stderr": stderr_data,
            "exit_code": exit_code,
        }

    @staticmethod
    def _drain_channel(channel: paramiko.Channel) -> str:
        data = b""
        while channel.recv_ready():
            data += channel.recv(65536)
        return data.decode("utf-8", errors="replace")

    @staticmethod
    def _shell_send(channel: paramiko.Channel, command: str, timeout: int) -> Dict[str, Any]:
        """Send a command to an interactive shell; detect exit code via marker."""
        marker = _SHELL_MARKER.format(uuid.uuid4().hex[:8], uuid.uuid4().hex[:8])
        full_cmd = '{}\necho "{} $?"\n'.format(command, marker)
        channel.sendall(full_cmd.encode())

        output = b""
        start = time.monotonic()
        timed_out = False

        while True:
            if time.monotonic() - start > timeout:
                timed_out = True
                break
            if channel.recv_ready():
                chunk = channel.recv(65536)
                if not chunk:
                    break
                output += chunk
                if marker.encode() in output:
                    break
            else:
                time.sleep(0.05)

        decoded = output.decode("utf-8", errors="replace")

        exit_code: Optional[int] = None
        output_lines: List[str] = []
        for line in decoded.split("\n"):
            if marker in line:
                remainder = line.split(marker)[-1].strip()
                try:
                    exit_code = int(remainder)
                except ValueError:
                    pass
                break
            output_lines.append(line)

        return {
            "output": "\n".join(output_lines).strip(),
            "exit_code": exit_code,
            "timed_out": timed_out,
        }

    # ------------------------------------------------------------------ #
    # Public tool methods
    # ------------------------------------------------------------------ #

    def connect(
        self,
        conn_id: str,
        host: str,
        username: str,
        port: Optional[int] = None,
        password: Optional[str] = None,
        key_path: Optional[str] = None,
        key_passphrase: Optional[str] = None,
        known_hosts_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        host = host.lower()
        port = port if port is not None else self._cfg.default_port
        t0 = time.perf_counter()

        client = paramiko.SSHClient()
        self._load_host_keys(client, known_hosts_path)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())

        connect_kwargs: Dict[str, Any] = {
            "hostname": host,
            "port": port,
            "username": username,
            "look_for_keys": False,
            "allow_agent": False,
        }

        if key_path:
            expanded = os.path.expanduser(key_path)
            if not os.path.isfile(expanded):
                raise FileNotFoundError(f"Private key not found: {expanded}")
            for key_class in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
                try:
                    pkey = key_class.from_private_key_file(expanded, password=key_passphrase)
                    connect_kwargs["pkey"] = pkey
                    break
                except paramiko.SSHException:
                    continue
            else:
                raise ValueError(f"Unable to load private key: {expanded}")
        elif password:
            connect_kwargs["password"] = password
        else:
            connect_kwargs["allow_agent"] = True
            connect_kwargs["look_for_keys"] = True

        if conn_id in self._connections:
            try:
                self._connections[conn_id].close()
            except Exception:
                pass

        try:
            client.connect(**connect_kwargs)
        except (paramiko.SSHException, socket.error) as e:
            self._log.error("connect failed conn_id=%s host=%s: %s", conn_id, host, e)
            raise RuntimeError(f"SSH connect error: {e}") from e

        self._connections[conn_id] = client
        transport = client.get_transport()
        peer = str(transport.getpeername()) if transport else "?"
        self._log_elapsed("connect", t0, conn_id=conn_id, remote=peer)
        return {"status": "connected", "conn_id": conn_id, "remote": peer}

    def exec(self, conn_id: str, command: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        timeout = timeout if timeout is not None else self._cfg.default_exec_timeout
        client = self._get_connection(conn_id)
        t0 = time.perf_counter()
        try:
            result = self._exec(client, command, timeout)
        except (paramiko.SSHException, socket.error) as e:
            self._log.error("exec failed conn_id=%s: %s", conn_id, e)
            raise RuntimeError(f"SSH exec error: {e}") from e
        self._log_elapsed("exec", t0, conn_id=conn_id, exit_code=result["exit_code"])
        return result

    def exec_script(
        self,
        conn_id: str,
        script: str,
        interpreter: str = "bash",
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        timeout = timeout if timeout is not None else self._cfg.default_script_timeout
        client = self._get_connection(conn_id)
        tmp_path = f"/tmp/_mcp_script_{uuid.uuid4().hex}.sh"
        t0 = time.perf_counter()

        try:
            sftp = client.open_sftp()
            try:
                with sftp.file(tmp_path, "w") as f:
                    f.write(script)
                sftp.chmod(tmp_path, 0o700)
            finally:
                sftp.close()

            try:
                result = self._exec(client, f"{interpreter} {tmp_path}", timeout)
            finally:
                try:
                    self._exec(client, f"rm -f {tmp_path}", timeout=5)
                except Exception:
                    pass
        except (paramiko.SSHException, socket.error) as e:
            self._log.error("exec_script failed conn_id=%s: %s", conn_id, e)
            raise RuntimeError(f"SSH exec_script error: {e}") from e

        self._log_elapsed("exec_script", t0, conn_id=conn_id, exit_code=result["exit_code"])
        return result

    def upload_file(self, conn_id: str, local_path: str, remote_path: str) -> Dict[str, Any]:
        client = self._get_connection(conn_id)
        t0 = time.perf_counter()
        try:
            sftp = client.open_sftp()
            try:
                sftp.put(local_path, remote_path)
            finally:
                sftp.close()
        except (paramiko.SSHException, socket.error, OSError) as e:
            self._log.error("upload_file failed conn_id=%s: %s", conn_id, e)
            raise RuntimeError(f"SSH upload error: {e}") from e
        self._log_elapsed("upload_file", t0, conn_id=conn_id, remote=remote_path)
        return {"status": "uploaded", "local": local_path, "remote": remote_path}

    def download_file(self, conn_id: str, remote_path: str, local_path: str) -> Dict[str, Any]:
        client = self._get_connection(conn_id)
        t0 = time.perf_counter()
        try:
            sftp = client.open_sftp()
            try:
                sftp.get(remote_path, local_path)
            finally:
                sftp.close()
        except (paramiko.SSHException, socket.error, OSError) as e:
            self._log.error("download_file failed conn_id=%s: %s", conn_id, e)
            raise RuntimeError(f"SSH download error: {e}") from e
        self._log_elapsed("download_file", t0, conn_id=conn_id, remote=remote_path)
        return {"status": "downloaded", "remote": remote_path, "local": local_path}

    def list_connections(self) -> Dict[str, Any]:
        connections: Dict[str, Any] = {}
        for cid, client in self._connections.items():
            transport = client.get_transport()
            active = transport is not None and transport.is_active()
            connections[cid] = {
                "active": active,
                "remote": str(transport.getpeername()) if active else "N/A",
            }
        return {"connections": connections}

    def disconnect(self, conn_id: str) -> Dict[str, Any]:
        if conn_id not in self._connections:
            raise ValueError(f"Connection '{conn_id}' not found.")
        for sid in [s for s, c in self._shell_to_conn.items() if c == conn_id]:
            try:
                self._shells[sid].close()
            except Exception:
                pass
            self._shells.pop(sid, None)
            self._shell_to_conn.pop(sid, None)
        self._connections[conn_id].close()
        del self._connections[conn_id]
        self._log.debug("tool=disconnect conn_id=%s", conn_id)
        return {"status": f"Connection '{conn_id}' closed."}

    def shell_open(
        self,
        conn_id: str,
        shell_id: Optional[str] = None,
        term: Optional[str] = None,
        cols: Optional[int] = None,
        rows: Optional[int] = None,
    ) -> Dict[str, Any]:
        shell_id = shell_id or conn_id
        term = term or self._cfg.default_term
        cols = cols if cols is not None else self._cfg.default_cols
        rows = rows if rows is not None else self._cfg.default_rows
        client = self._get_connection(conn_id)
        t0 = time.perf_counter()

        if shell_id in self._shells:
            try:
                self._shells[shell_id].close()
            except Exception:
                pass

        try:
            channel = client.invoke_shell(term=term, width=cols, height=rows)
        except paramiko.SSHException as e:
            self._log.error("shell_open failed conn_id=%s: %s", conn_id, e)
            raise RuntimeError(f"SSH shell_open error: {e}") from e

        channel.settimeout(5)
        self._shells[shell_id] = channel
        self._shell_to_conn[shell_id] = conn_id

        time.sleep(0.5)
        self._drain_channel(channel)
        self._shell_send(channel, "stty -echo 2>/dev/null; export PS1=''; export PS2=''", timeout=3)

        self._log_elapsed("shell_open", t0, conn_id=conn_id, shell_id=shell_id)
        return {"status": "shell_opened", "shell_id": shell_id, "conn_id": conn_id}

    def shell_exec(self, shell_id: str, command: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        timeout = timeout if timeout is not None else self._cfg.default_shell_timeout
        if shell_id not in self._shells:
            raise ValueError(f"Shell '{shell_id}' not found. Call ssh_shell_open first.")
        channel = self._shells[shell_id]
        if channel.closed:
            del self._shells[shell_id]
            self._shell_to_conn.pop(shell_id, None)
            raise ValueError(f"Shell '{shell_id}' is closed. Open a new one.")

        t0 = time.perf_counter()
        parsed = self._shell_send(channel, command, timeout)
        self._log_elapsed(
            "shell_exec", t0,
            shell_id=shell_id,
            exit_code=parsed["exit_code"],
            timed_out=parsed["timed_out"],
        )

        result: Dict[str, Any] = {"output": parsed["output"], "shell_id": shell_id}
        if parsed["exit_code"] is not None:
            result["exit_code"] = parsed["exit_code"]
        if parsed["timed_out"]:
            result["timeout"] = True
        return result

    def shell_close(self, shell_id: str) -> Dict[str, Any]:
        if shell_id not in self._shells:
            raise ValueError(f"Shell '{shell_id}' not found.")
        try:
            self._shells[shell_id].close()
        except Exception:
            pass
        del self._shells[shell_id]
        self._shell_to_conn.pop(shell_id, None)
        self._log.debug("tool=shell_close shell_id=%s", shell_id)
        return {"status": f"Shell '{shell_id}' closed."}
