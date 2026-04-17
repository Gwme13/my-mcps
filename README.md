# My MCPs

A collection of [Model Context Protocol (MCP)](https://modelcontextprotocol.io) servers that extend Claude with real-world capabilities.

## Servers

### [`ssh/`](ssh/) — SSH MCP Server

Gives Claude the ability to open persistent SSH connections to remote servers and execute commands, scripts, and file transfers, all within a conversation.

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

- **Private key**: pass `key_path` (e.g. `~/.ssh/id_rsa`). RSA, Ed25519, and ECDSA keys are supported.
- **Password**: pass `password`.
- **SSH agent**: if neither `key_path` nor `password` is provided, the local SSH agent is used.

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

### [`ollama/`](ollama/) — Ollama MCP Delegation Server

Delegates SIMPLE coding tasks (docstrings, explanations, small refactors, unit tests for pure functions) to a local Ollama model, keeping the main model focused on complex work. Ships with two-tier routing: a small fast model (default `qwen2.5-coder:7b-instruct-q8_0`) for trivial tasks and a larger MoE model (default `qwen3-coder:30b-a3b-q8_0`) for deeper reasoning.

#### Tools

| Tool | Tier | Description |
|------|------|-------------|
| `ollama_generate` | small | Raw text generation (single prompt, no chat history). |
| `ollama_chat` | small | Chat completion with a list of `{role, content}` messages. |
| `ollama_code_review` | small | Review a snippet; returns Issues / Improvements / Verdict bullets. |
| `ollama_refactor` | large | Refactor code; returns only the refactored code block. |
| `ollama_explain` | small | Explain code (detail levels: `low`, `medium`, `high`). |
| `ollama_write_tests` | large | Generate a unit test file (AAA structure, happy + edge + error paths). |
| `ollama_write_docstring` | small | Add docstrings/comments in language-idiomatic style. |
| `ollama_fix_bug` | large | Diagnose and fix; returns root cause + fixed code. |
| `ollama_list_models` | — | List locally available models. |
| `ollama_pull_model` | — | Pull a model from the Ollama registry. |
| `ollama_delete_model` | — | Delete a local model. |
| `ollama_show_model` | — | Show model metadata (modelfile, parameters, template). |
| `ollama_running_models` | — | List models currently loaded in memory (`ps`). |
| `ollama_copy_model` | — | Duplicate a model under a new name. |
| `ollama_health_check` | — | Verify Ollama is reachable; reports small/large availability. |
| `ollama_embeddings` | small | Generate embeddings for the input text. |
| `ollama_benchmark` | small | Quick benchmark, returns tokens/sec. |

Passing `model=` explicitly on any call overrides the tier routing.

#### Installation

```bash
cd ollama
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
claude mcp add -s user ollama-mcp "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
```

See [`ollama/README.md`](ollama/README.md) for configuration, environment variables, and architectural notes.

#### Example usage

> "Add Google-style docstrings to this fibonacci function."

Claude will call `ollama_write_docstring(code, 'python', 'google')` and apply the result.

---

## License

[MIT](LICENSE)
