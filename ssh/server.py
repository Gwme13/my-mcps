"""SSH MCP server entry point.

Exposes tools to open persistent SSH connections, run commands in one-shot or
interactive shells, and transfer files via SFTP. Kept intentionally thin: all
paramiko business logic lives in services.ssh_service.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from config import load_config
from logger_setup import get_logger
from services.ssh_service import SSHService

_cfg = load_config()
_log = get_logger("ssh_mcp.server", _cfg.log_level)
_svc = SSHService(_cfg)

mcp = FastMCP("ssh-mcp")


# Connection tools

@mcp.tool()
def ssh_connect(
    conn_id: str,
    host: str,
    username: str,
    port: Optional[int] = None,
    password: Optional[str] = None,
    key_path: Optional[str] = None,
    key_passphrase: Optional[str] = None,
    known_hosts_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Open a persistent SSH connection. Auth priority: key_path -> password -> SSH agent."""
    return _svc.connect(
        conn_id, host, username, port, password, key_path, key_passphrase, known_hosts_path
    )


@mcp.tool()
def ssh_disconnect(conn_id: str) -> Dict[str, Any]:
    """Close an SSH connection and any shells attached to it."""
    return _svc.disconnect(conn_id)


@mcp.tool()
def ssh_list_connections() -> Dict[str, Any]:
    """List all currently open SSH connections with active status and peer address."""
    return _svc.list_connections()


# One-shot command tools

@mcp.tool()
def ssh_exec(conn_id: str, command: str, timeout: Optional[int] = None) -> Dict[str, Any]:
    """Execute a shell command in an isolated channel. Returns stdout, stderr, exit_code."""
    return _svc.exec(conn_id, command, timeout)


@mcp.tool()
def ssh_exec_script(
    conn_id: str,
    script: str,
    interpreter: str = "bash",
    timeout: Optional[int] = None,
) -> Dict[str, Any]:
    """Upload an inline script to /tmp, run it, delete the temp file. Returns stdout/stderr/exit_code."""
    return _svc.exec_script(conn_id, script, interpreter, timeout)


# Interactive shell tools

@mcp.tool()
def ssh_shell_open(
    conn_id: str,
    shell_id: Optional[str] = None,
    term: Optional[str] = None,
    cols: Optional[int] = None,
    rows: Optional[int] = None,
) -> Dict[str, Any]:
    """Open a persistent PTY shell. State (cwd, env) persists across ssh_shell_exec calls."""
    return _svc.shell_open(conn_id, shell_id, term, cols, rows)


@mcp.tool()
def ssh_shell_exec(shell_id: str, command: str, timeout: Optional[int] = None) -> Dict[str, Any]:
    """Send a command to a persistent shell; returns output, exit_code, optional timeout flag."""
    return _svc.shell_exec(shell_id, command, timeout)


@mcp.tool()
def ssh_shell_close(shell_id: str) -> Dict[str, Any]:
    """Close a persistent shell session."""
    return _svc.shell_close(shell_id)


# SFTP tools

@mcp.tool()
def ssh_upload_file(conn_id: str, local_path: str, remote_path: str) -> Dict[str, Any]:
    """Upload a local file to the remote server via SFTP."""
    return _svc.upload_file(conn_id, local_path, remote_path)


@mcp.tool()
def ssh_download_file(conn_id: str, remote_path: str, local_path: str) -> Dict[str, Any]:
    """Download a file from the remote server to local via SFTP."""
    return _svc.download_file(conn_id, remote_path, local_path)


if __name__ == "__main__":
    _log.info("Starting SSH MCP server")
    mcp.run()
