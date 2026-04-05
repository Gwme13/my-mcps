# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A collection of MCP (Model Context Protocol) servers that extend Claude with additional capabilities. Currently contains an SSH server that provides persistent SSH connections, command execution, interactive shells, and SFTP file transfers.

## Running the Server

```bash
pip install -r ssh/requirements.txt
python3 ssh/server.py  # Runs as stdio-based MCP server
```

No tests, linter, or build system are configured.

## Architecture

The SSH MCP server (`ssh/server.py`) is a single-file implementation (~660 lines) built on **paramiko** and **mcp**.

**Request flow:** MCP stdio transport → `@server.call_tool()` → `_dispatch()` → tool handler (run in thread executor) → paramiko SSH/SFTP → JSON response as `TextContent`.

**Key abstractions:**
- **Connection pool** (`_connections` dict): maps `conn_id` → `paramiko.SSHClient`. Persists for server lifetime.
- **Shell pool** (`_shells` / `_shell_to_conn` dicts): maps `shell_id` → `paramiko.Channel` for interactive PTY sessions. Shells are tied to a parent connection and cleaned up on disconnect.
- **Two execution modes**: `ssh_exec` runs isolated commands (no state); `ssh_shell_*` tools maintain a persistent shell with marker-based exit code detection.

**Tool registration pattern:** `@server.list_tools()` returns `types.Tool` objects with JSON schemas. All calls route through `_dispatch()` which wraps blocking paramiko I/O in `asyncio.run_in_executor()`.

**Security:** Host key verification uses `RejectPolicy` — unknown hosts are always rejected. Keys are loaded from `~/.ssh/known_hosts`, `/etc/ssh/ssh_known_hosts`, or a custom path. Hostnames are normalized to lowercase for case-insensitive matching.

**Authentication priority:** explicit key file (tries RSA → Ed25519 → ECDSA) → password → SSH agent fallback.
