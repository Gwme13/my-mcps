#!/usr/bin/env python3
"""
MCP SSH Server
Exposes tools for connecting to remote servers via SSH and executing shell commands/scripts.
"""

import asyncio
import json
import logging
import os
import uuid
from typing import Any

import paramiko
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("mcp-ssh")

# --------------------------------------------------------------------------- #
# SSH connection pool (simple in-memory dict)
# --------------------------------------------------------------------------- #

_connections: dict[str, paramiko.SSHClient] = {}


def _get_connection(conn_id: str) -> paramiko.SSHClient:
    """Return an active SSH connection by ID, or raise if not found / inactive."""
    if conn_id not in _connections:
        raise ValueError(f"Connection '{conn_id}' not found. Call ssh_connect first.")
    client = _connections[conn_id]
    transport = client.get_transport()
    if transport is None or not transport.is_active():
        raise ValueError(f"Connection '{conn_id}' is no longer active. Reconnect.")
    return client


def _exec(client: paramiko.SSHClient, command: str, timeout: int = 30) -> dict:
    """Execute a shell command and return stdout, stderr and exit code."""
    _, stdout, stderr = client.exec_command(command, timeout=timeout)
    # Read output before recv_exit_status to avoid deadlock when buffers fill up
    stdout_data = stdout.read().decode("utf-8", errors="replace")
    stderr_data = stderr.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    return {
        "stdout": stdout_data,
        "stderr": stderr_data,
        "exit_code": exit_code,
    }


# --------------------------------------------------------------------------- #
# MCP server
# --------------------------------------------------------------------------- #

server = Server("mcp-ssh-server")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="ssh_connect",
            description=(
                "Open a persistent SSH connection to a remote server. "
                "Supports password or private key authentication. "
                "Returns a conn_id to be used in subsequent tools."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "conn_id": {
                        "type": "string",
                        "description": "Identifier for this connection (e.g. 'prod', 'dev').",
                    },
                    "host": {
                        "type": "string",
                        "description": "Hostname or IP address of the remote server.",
                    },
                    "port": {
                        "type": "integer",
                        "description": "SSH port (default: 22).",
                        "default": 22,
                    },
                    "username": {
                        "type": "string",
                        "description": "SSH username.",
                    },
                    "password": {
                        "type": "string",
                        "description": "Password (optional if key_path is provided).",
                    },
                    "key_path": {
                        "type": "string",
                        "description": "Path to the SSH private key (e.g. ~/.ssh/id_rsa). Optional.",
                    },
                    "key_passphrase": {
                        "type": "string",
                        "description": "Passphrase for the private key, if encrypted.",
                    },
                    "known_hosts_path": {
                        "type": "string",
                        "description": (
                            "Path to a custom known_hosts file (optional). "
                            "If omitted, ~/.ssh/known_hosts and /etc/ssh/ssh_known_hosts are used. "
                            "To add a new host: ssh-keyscan -H <host> >> ~/.ssh/known_hosts"
                        ),
                    },
                },
                "required": ["conn_id", "host", "username"],
            },
        ),
        types.Tool(
            name="ssh_exec",
            description=(
                "Execute a shell command on an open SSH connection. "
                "Returns stdout, stderr and exit code."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "conn_id": {"type": "string", "description": "ID of the open connection."},
                    "command": {"type": "string", "description": "Shell command to execute."},
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 30).",
                        "default": 30,
                    },
                },
                "required": ["conn_id", "command"],
            },
        ),
        types.Tool(
            name="ssh_exec_script",
            description=(
                "Upload and execute an inline shell script on a remote server. "
                "The script is written to a temporary file, executed, then deleted."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "conn_id": {"type": "string", "description": "ID of the open connection."},
                    "script": {
                        "type": "string",
                        "description": "Shell script content (e.g. #!/bin/bash\\necho hello).",
                    },
                    "interpreter": {
                        "type": "string",
                        "description": "Interpreter to use: bash, sh, python3, etc. (default: bash).",
                        "default": "bash",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 60).",
                        "default": 60,
                    },
                },
                "required": ["conn_id", "script"],
            },
        ),
        types.Tool(
            name="ssh_upload_file",
            description="Upload a local file to the remote server via SFTP.",
            inputSchema={
                "type": "object",
                "properties": {
                    "conn_id": {"type": "string", "description": "ID of the open connection."},
                    "local_path": {"type": "string", "description": "Local path of the file to upload."},
                    "remote_path": {"type": "string", "description": "Destination path on the remote server."},
                },
                "required": ["conn_id", "local_path", "remote_path"],
            },
        ),
        types.Tool(
            name="ssh_download_file",
            description="Download a file from the remote server to local via SFTP.",
            inputSchema={
                "type": "object",
                "properties": {
                    "conn_id": {"type": "string", "description": "ID of the open connection."},
                    "remote_path": {"type": "string", "description": "Path of the file on the remote server."},
                    "local_path": {"type": "string", "description": "Local path where the file will be saved."},
                },
                "required": ["conn_id", "remote_path", "local_path"],
            },
        ),
        types.Tool(
            name="ssh_list_connections",
            description="List all active SSH connections.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="ssh_disconnect",
            description="Close an SSH connection.",
            inputSchema={
                "type": "object",
                "properties": {
                    "conn_id": {"type": "string", "description": "ID of the connection to close."},
                },
                "required": ["conn_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        result = await _dispatch(name, arguments)
    except Exception as e:
        result = {"error": str(e)}
    return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


async def _dispatch(name: str, args: dict) -> dict:
    """Route tool calls to the appropriate handler, running blocking I/O in a thread pool."""
    loop = asyncio.get_running_loop()

    if name == "ssh_connect":
        return await loop.run_in_executor(None, _tool_connect, args)

    if name == "ssh_exec":
        conn_id = args["conn_id"]
        command = args["command"]
        timeout = args.get("timeout", 30)
        return await loop.run_in_executor(
            None, lambda: _exec(_get_connection(conn_id), command, timeout)
        )

    if name == "ssh_exec_script":
        return await loop.run_in_executor(None, _tool_exec_script, args)

    if name == "ssh_upload_file":
        return await loop.run_in_executor(None, _tool_sftp_upload, args)

    if name == "ssh_download_file":
        return await loop.run_in_executor(None, _tool_sftp_download, args)

    if name == "ssh_list_connections":
        connections = {}
        for cid, client in _connections.items():
            transport = client.get_transport()
            active = transport is not None and transport.is_active()
            connections[cid] = {
                "active": active,
                "remote": str(transport.getpeername()) if active else "N/A",
            }
        return {"connections": connections}

    if name == "ssh_disconnect":
        conn_id = args["conn_id"]
        if conn_id in _connections:
            _connections[conn_id].close()
            del _connections[conn_id]
            return {"status": f"Connection '{conn_id}' closed."}
        return {"error": f"Connection '{conn_id}' not found."}

    raise ValueError(f"Unknown tool: {name}")


# --------------------------------------------------------------------------- #
# SSH helpers
# --------------------------------------------------------------------------- #

def _load_host_keys(client: paramiko.SSHClient, known_hosts_path: str | None) -> None:
    """
    Load known_hosts into the client from standard locations and optionally a custom path.
    At least one known_hosts file must exist; otherwise RejectPolicy will refuse all hosts.
    To register a new host: ssh-keyscan -H <host> >> ~/.ssh/known_hosts
    """
    loaded = False

    # 1. User known_hosts (~/.ssh/known_hosts)
    user_kh = os.path.expanduser("~/.ssh/known_hosts")
    if os.path.isfile(user_kh):
        client.load_host_keys(user_kh)
        loaded = True

    # 2. System-wide known_hosts (/etc/ssh/ssh_known_hosts on Linux/macOS)
    system_kh = "/etc/ssh/ssh_known_hosts"
    if os.path.isfile(system_kh):
        client.load_system_host_keys(system_kh)
        loaded = True
    else:
        # Fallback: let paramiko find the system default
        try:
            client.load_system_host_keys()
            loaded = True
        except Exception:
            pass

    # 3. Optional custom known_hosts file
    if known_hosts_path:
        expanded = os.path.expanduser(known_hosts_path)
        if not os.path.isfile(expanded):
            raise FileNotFoundError(f"known_hosts_path not found: {expanded}")
        client.load_host_keys(expanded)
        loaded = True

    if not loaded:
        raise RuntimeError(
            "No known_hosts file found. "
            "Add the host with: ssh-keyscan -H <host> >> ~/.ssh/known_hosts"
        )


def _tool_connect(args: dict) -> dict:
    """Open an SSH connection and store it in the connection pool."""
    conn_id = args["conn_id"]
    host = args["host"]
    port = args.get("port", 22)
    username = args["username"]
    password = args.get("password")
    key_path = args.get("key_path")
    key_passphrase = args.get("key_passphrase")
    known_hosts_path = args.get("known_hosts_path")

    client = paramiko.SSHClient()

    # Load known_hosts then enforce RejectPolicy:
    # connections to unverified hosts will be refused entirely.
    # Register new hosts with: ssh-keyscan -H <host> >> ~/.ssh/known_hosts
    _load_host_keys(client, known_hosts_path)
    client.set_missing_host_key_policy(paramiko.RejectPolicy())

    connect_kwargs: dict[str, Any] = {
        "hostname": host,
        "port": port,
        "username": username,
    }

    connect_kwargs["look_for_keys"] = False
    connect_kwargs["allow_agent"] = False

    if key_path:
        expanded = os.path.expanduser(key_path)
        if not os.path.isfile(expanded):
            raise FileNotFoundError(f"Private key not found: {expanded}")
        # Try RSA first, then Ed25519, then ECDSA
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
        # Fall back to local SSH agent
        connect_kwargs["allow_agent"] = True
        connect_kwargs["look_for_keys"] = True

    # Close existing connection with the same ID if present
    if conn_id in _connections:
        try:
            _connections[conn_id].close()
        except Exception:
            pass

    client.connect(**connect_kwargs)

    _connections[conn_id] = client
    transport = client.get_transport()
    peer = str(transport.getpeername()) if transport else "?"
    return {"status": "connected", "conn_id": conn_id, "remote": peer}


def _tool_exec_script(args: dict) -> dict:
    """Upload an inline script to a temp file on the remote server, execute it, then delete it."""
    conn_id = args["conn_id"]
    script = args["script"]
    interpreter = args.get("interpreter", "bash")
    timeout = args.get("timeout", 60)
    client = _get_connection(conn_id)

    tmp_path = f"/tmp/_mcp_script_{uuid.uuid4().hex}.sh"

    # Upload script via SFTP
    sftp = client.open_sftp()
    try:
        with sftp.file(tmp_path, "w") as f:
            f.write(script)
        sftp.chmod(tmp_path, 0o700)
    finally:
        sftp.close()

    try:
        result = _exec(client, f"{interpreter} {tmp_path}", timeout=timeout)
    finally:
        # Always clean up the temp file
        try:
            _exec(client, f"rm -f {tmp_path}", timeout=5)
        except Exception:
            pass

    return result


def _tool_sftp_upload(args: dict) -> dict:
    """Upload a local file to the remote server via SFTP."""
    conn_id = args["conn_id"]
    local_path = args["local_path"]
    remote_path = args["remote_path"]
    client = _get_connection(conn_id)

    sftp = client.open_sftp()
    try:
        sftp.put(local_path, remote_path)
    finally:
        sftp.close()
    return {"status": "uploaded", "local": local_path, "remote": remote_path}


def _tool_sftp_download(args: dict) -> dict:
    """Download a file from the remote server to local via SFTP."""
    conn_id = args["conn_id"]
    remote_path = args["remote_path"]
    local_path = args["local_path"]
    client = _get_connection(conn_id)

    sftp = client.open_sftp()
    try:
        sftp.get(remote_path, local_path)
    finally:
        sftp.close()
    return {"status": "downloaded", "remote": remote_path, "local": local_path}


# --------------------------------------------------------------------------- #
# Entrypoint
# --------------------------------------------------------------------------- #

async def main():
    async with stdio_server() as streams:
        await server.run(
            streams[0],
            streams[1],
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())