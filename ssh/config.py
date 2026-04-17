"""Configuration loader for the SSH MCP server.

Design: single source of truth loaded at startup, env vars override file values.
Frozen dataclass prevents accidental mutation across concurrent tool calls.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

CONFIG_PATH = Path(__file__).parent / "config.json"

_DEFAULT_KNOWN_HOSTS: List[str] = [
    "~/.ssh/known_hosts",
    "/etc/ssh/ssh_known_hosts",
]


@dataclass(frozen=True)
class Config:
    default_port: int
    default_exec_timeout: int
    default_script_timeout: int
    default_shell_timeout: int
    default_term: str
    default_cols: int
    default_rows: int
    log_level: str
    known_hosts_paths: List[str] = field(default_factory=list)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def load_config() -> Config:
    data = _load_json(CONFIG_PATH)
    known_hosts = data.get("known_hosts_paths") or _DEFAULT_KNOWN_HOSTS

    return Config(
        default_port=int(
            os.getenv("SSH_MCP_DEFAULT_PORT", data.get("default_port", 22))
        ),
        default_exec_timeout=int(
            os.getenv("SSH_MCP_EXEC_TIMEOUT", data.get("default_exec_timeout", 30))
        ),
        default_script_timeout=int(
            os.getenv("SSH_MCP_SCRIPT_TIMEOUT", data.get("default_script_timeout", 60))
        ),
        default_shell_timeout=int(
            os.getenv("SSH_MCP_SHELL_TIMEOUT", data.get("default_shell_timeout", 30))
        ),
        default_term=os.getenv("SSH_MCP_TERM", data.get("default_term", "xterm")),
        default_cols=int(os.getenv("SSH_MCP_COLS", data.get("default_cols", 200))),
        default_rows=int(os.getenv("SSH_MCP_ROWS", data.get("default_rows", 50))),
        log_level=os.getenv("SSH_MCP_LOG_LEVEL", data.get("log_level", "DEBUG")),
        known_hosts_paths=list(known_hosts),
    )
