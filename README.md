# My MCPs

A collection of [Model Context Protocol (MCP)](https://modelcontextprotocol.io) servers that extend Claude with real-world capabilities.

## Servers

### [`ssh/`](ssh/) — SSH MCP Server

Gives Claude the ability to open persistent SSH connections to remote servers and execute commands, scripts, and file transfers — all within a conversation.

#### Tools

| Tool | Description |
|------|-------------|
| `ssh_connect` | Open a persistent SSH connection (password or private key). Returns a `conn_id` used by all other tools. |
| `ssh_exec` | Execute a shell command on an open connection. Returns stdout, stderr, and exit code. Each command runs in an isolated channel (no state persistence). |
| `ssh_exec_script` | Upload and run an inline shell script remotely. The temp file is deleted after execution. |
| `ssh_shell_open` | Open a persistent interactive shell with PTY. Maintains state (working directory, environment variables) across commands. |
| `ssh_shell_exec` | Send a command to a persistent shell. State persists between calls (cd, export, etc.). Returns output and exit code. |
| `ssh_shell_close` | Close a persistent shell session. |
| `ssh_upload_file` | Upload a local file to the remote server via SFTP. |
| `ssh_download_file` | Download a file from the remote server via SFTP. |
| `ssh_list_connections` | List all currently open connections and their status. |
| `ssh_disconnect` | Close a specific connection (and any associated shells). |

#### Authentication

- **Private key** — pass `key_path` (e.g. `~/.ssh/id_rsa`). RSA, Ed25519, and ECDSA keys are supported.
- **Password** — pass `password`.
- **SSH agent** — if neither `key_path` nor `password` is provided, the local SSH agent is used.

Host key verification is **always enforced** (`RejectPolicy`). Register unknown hosts before connecting:

```bash
ssh-keyscan -H <host> >> ~/.ssh/known_hosts
```

#### Installation

```bash
cd ssh
pip install -r requirements.txt
```

#### Claude Desktop configuration (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "ssh": {
      "command": "python3",
      "args": ["/absolute/path/to/ssh/server.py"]
    }
  }
}
```

#### Example usage

> "Connect to [host] as [user] using my key at ~/.ssh/[file], then show me disk usage."

Claude will call `ssh_connect` → `ssh_exec df -h` → return the output.

---

## License

[MIT](LICENSE)
