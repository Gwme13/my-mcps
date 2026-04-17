"""Configuration loader for the Ollama MCP server.

Design: single source of truth loaded at startup, env vars override file values.
Frozen dataclass prevents accidental mutation across concurrent tool calls.

Two-tier model routing:
  * small_model: fast, fits entirely in VRAM; for trivial tasks.
  * large_model: more capable, split GPU/CPU; for harder tasks.
  * tool_model_map: per-tool selector ("small" | "large"); the tool's explicit
    `model` argument always wins over this map.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

CONFIG_PATH = Path(__file__).parent / "config.json"

_DEFAULT_BUDGETS: Dict[str, int] = {
    "docstring": 512,
    "refactor": 1500,
    "explain": 800,
    "tests": 2000,
    "review": 800,
    "fix_bug": 1500,
}

_DEFAULT_TOOL_MODEL_MAP: Dict[str, str] = {
    "generate": "small",
    "chat": "small",
    "docstring": "small",
    "explain": "small",
    "review": "small",
    "embeddings": "small",
    "benchmark": "small",
    "refactor": "large",
    "tests": "large",
    "fix_bug": "large",
}


@dataclass(frozen=True)
class Config:
    base_url: str
    small_model: str
    large_model: str
    default_model: str
    default_temperature: float
    default_num_predict: int
    request_timeout_seconds: int
    keep_alive: str
    log_level: str
    tool_model_map: Dict[str, str] = field(default_factory=dict)
    tool_budgets: Dict[str, int] = field(default_factory=dict)

    def model_for(self, tool: str) -> str:
        """Resolve which configured model to use for a given tool name."""
        tier = self.tool_model_map.get(tool, "small")
        return self.large_model if tier == "large" else self.small_model


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fp:
        return json.load(fp)


def load_config() -> Config:
    data = _load_json(CONFIG_PATH)
    budgets = {**_DEFAULT_BUDGETS, **data.get("tool_budgets", {})}
    tool_map = {**_DEFAULT_TOOL_MODEL_MAP, **data.get("tool_model_map", {})}

    small = os.getenv("OLLAMA_SMALL_MODEL", data.get("small_model", "qwen2.5-coder:7b-instruct-q8_0"))
    large = os.getenv("OLLAMA_LARGE_MODEL", data.get("large_model", "qwen3-coder:30b-a3b-q8_0"))
    default = os.getenv("OLLAMA_DEFAULT_MODEL", data.get("default_model", small))

    return Config(
        base_url=os.getenv("OLLAMA_BASE_URL", data.get("base_url", "http://localhost:11434")),
        small_model=small,
        large_model=large,
        default_model=default,
        default_temperature=float(
            os.getenv("OLLAMA_TEMPERATURE", data.get("default_temperature", 0.1))
        ),
        default_num_predict=int(
            os.getenv("OLLAMA_NUM_PREDICT", data.get("default_num_predict", 1024))
        ),
        request_timeout_seconds=int(
            os.getenv("OLLAMA_TIMEOUT", data.get("request_timeout_seconds", 300))
        ),
        keep_alive=os.getenv("OLLAMA_KEEP_ALIVE", data.get("keep_alive", "2m")),
        log_level=os.getenv("OLLAMA_MCP_LOG_LEVEL", data.get("log_level", "DEBUG")),
        tool_model_map=tool_map,
        tool_budgets=budgets,
    )
