# Ollama MCP Delegation Server

Local MCP server that exposes an Ollama model as a set of specialized coding tools. The goal is to delegate SIMPLE development tasks (docstrings, lightweight refactors, explanations, unit tests for pure functions) to a local model, reserving the main model for complex work.

## Requirements

- Python 3.10+
- Ollama running (default `http://localhost:11434`)
- Two models pulled (recommended):
  - `qwen2.5-coder:7b-instruct-q8_0` (small, fits entirely in VRAM, ~60-80 tok/s)
  - `qwen3-coder:30b-a3b-q8_0` (large, MoE with 3B active, split GPU/CPU)

Any other Ollama models can be used by editing `config.json` or via environment variables.

## Installation

```bash
cd ollama
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then register the server in Claude Code (user scope, available in every project):

```bash
claude mcp add -s user ollama-mcp "$(pwd)/.venv/bin/python" "$(pwd)/server.py"
```

Verify with:

```bash
claude mcp list
```

## Small / Large Routing

Each tool is mapped to `small` or `large` via `tool_model_map` in `config.json`:

| Tier | Tools |
|---|---|
| **small** (fast, default) | `ollama_generate`, `ollama_chat`, `ollama_write_docstring`, `ollama_explain`, `ollama_code_review`, `ollama_embeddings`, `ollama_benchmark` |
| **large** (deeper reasoning) | `ollama_refactor`, `ollama_write_tests`, `ollama_fix_bug` |

An explicit `model=` argument on a tool call always **overrides** the map.

## Configuration

`config.json` holds the defaults. Environment variables override file values:

| Variable | Description |
|---|---|
| `OLLAMA_BASE_URL` | Ollama server URL |
| `OLLAMA_SMALL_MODEL` | Small-tier model |
| `OLLAMA_LARGE_MODEL` | Large-tier model |
| `OLLAMA_DEFAULT_MODEL` | Generic fallback (defaults to small) |
| `OLLAMA_TEMPERATURE` | Default temperature (0.1) |
| `OLLAMA_NUM_PREDICT` | Default max tokens |
| `OLLAMA_TIMEOUT` | Request timeout in seconds |
| `OLLAMA_KEEP_ALIVE` | Model keep-alive duration (e.g. `2m`) |
| `OLLAMA_MCP_LOG_LEVEL` | Log level (default `DEBUG`) |

## Exposed Tools

### Generation (high-value for delegation)
- `ollama_generate(prompt, model?, system?, temperature?, max_tokens?)`
- `ollama_chat(messages, model?, system?, temperature?, max_tokens?)`
- `ollama_code_review(code, language?, focus?)`
- `ollama_refactor(code, language?, instructions?)` (large)
- `ollama_explain(code, language?, detail_level?)` (low | medium | high)
- `ollama_write_tests(code, language?, framework?)` (large)
- `ollama_write_docstring(code, language?, style?)`
- `ollama_fix_bug(code, error_message?, language?)` (large)

### Model management
- `ollama_list_models()`
- `ollama_pull_model(model_name)`
- `ollama_delete_model(model_name)`
- `ollama_show_model(model_name)`
- `ollama_running_models()`
- `ollama_copy_model(source, destination)`

### Utility
- `ollama_health_check()` (reports small/large availability)
- `ollama_embeddings(text, model?)`
- `ollama_benchmark(prompt?, model?)` (returns tokens/sec)

## Efficiency

The server is designed to reduce, not increase, the main model's token consumption:

- **Strict system prompts**: every tool instructs Ollama to return ONLY the useful payload (code, review bullets), no preamble. The caller does not have to strip boilerplate from the output.
- **Two-tier routing**: trivial tasks go to the 7B model for speed; harder tasks go to the 30B MoE.
- **Per-tool budgets**: `tool_budgets` in `config.json` caps `num_predict` by task type. A docstring costs less than a test suite.
- **Low temperature (0.1)**: deterministic output, fewer retries.
- **Singleton client**: HTTP connection reused across all calls.
- **2-minute keep-alive**: the model stays loaded between bursty calls without monopolizing VRAM long-term.
- **Metrics in logs** (`logs/mcp.log`): every call records `elapsed`, `prompt_tokens`, `eval_tokens`, `tokens_per_sec`, and the model used. Handy to verify that delegation is actually paying off.

## Architecture

```
ollama/
├── server.py              # Tool registration (Controller)
├── services/
│   ├── ollama_service.py  # Ollama client wrapper + routing + metrics (Service)
│   └── prompts.py         # Specialized system prompts
├── config.py              # Env + JSON config loader
├── logger_setup.py        # Rotating file logger
├── config.json            # Defaults
└── requirements.txt
```

Swap the backend (e.g. to llama.cpp) by replacing only `services/ollama_service.py`.

## Logs

`ollama/logs/mcp.log` (rotating, 5 MB x 3 files). Default level: `DEBUG`.

## Uninstall

```bash
claude mcp remove ollama-mcp
rm -rf ollama/.venv
```
