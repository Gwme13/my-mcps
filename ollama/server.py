"""Ollama MCP server entry point.

Exposes coding-focused tools for task delegation. Kept intentionally thin:
all business logic lives in services.ollama_service; this module only
registers tools and marshals arguments.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from config import load_config
from logger_setup import get_logger
from services import prompts
from services.ollama_service import OllamaService

_cfg = load_config()
_log = get_logger("ollama_mcp.server", _cfg.log_level)
_svc = OllamaService(_cfg)

mcp = FastMCP("ollama-mcp")


# Generation tools

@mcp.tool()
def ollama_generate(
    prompt: str,
    model: Optional[str] = None,
    system: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """Raw text generation. Use for free-form prompts without chat history."""
    return _svc.generate(prompt, model, system, temperature, max_tokens)


@mcp.tool()
def ollama_chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    system: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """Chat completion. messages is a list of {role, content} dicts."""
    return _svc.chat(messages, model, system, temperature, max_tokens)


@mcp.tool()
def ollama_code_review(code: str, language: Optional[str] = None, focus: Optional[str] = None) -> str:
    """Review code; returns concise Issues/Improvements/Verdict markdown list."""
    s, u = prompts.code_review(code, language, focus)
    return _svc.run_prompted("review", s, u)


@mcp.tool()
def ollama_refactor(code: str, language: Optional[str] = None, instructions: Optional[str] = None) -> str:
    """Refactor code; returns only the refactored code block."""
    s, u = prompts.refactor(code, language, instructions)
    return _svc.run_prompted("refactor", s, u)


@mcp.tool()
def ollama_explain(code: str, language: Optional[str] = None, detail_level: Optional[str] = None) -> str:
    """Explain code. detail_level: low | medium | high."""
    s, u = prompts.explain(code, language, detail_level)
    return _svc.run_prompted("explain", s, u)


@mcp.tool()
def ollama_write_tests(code: str, language: Optional[str] = None, framework: Optional[str] = None) -> str:
    """Generate unit tests; returns only the test file block."""
    s, u = prompts.write_tests(code, language, framework)
    return _svc.run_prompted("tests", s, u)


@mcp.tool()
def ollama_write_docstring(code: str, language: Optional[str] = None, style: Optional[str] = None) -> str:
    """Add docstrings/comments; returns full code with docs added."""
    s, u = prompts.write_docstring(code, language, style)
    return _svc.run_prompted("docstring", s, u)


@mcp.tool()
def ollama_fix_bug(code: str, error_message: Optional[str] = None, language: Optional[str] = None) -> str:
    """Diagnose and fix; returns root cause line + fixed code block."""
    s, u = prompts.fix_bug(code, error_message, language)
    return _svc.run_prompted("fix_bug", s, u)


# Model management tools

@mcp.tool()
def ollama_list_models() -> List[Dict[str, Any]]:
    """List all locally available models."""
    return _svc.list_models()


@mcp.tool()
def ollama_pull_model(model_name: str) -> str:
    """Pull a model from the Ollama registry."""
    return _svc.pull_model(model_name)


@mcp.tool()
def ollama_delete_model(model_name: str) -> str:
    """Delete a local model."""
    return _svc.delete_model(model_name)


@mcp.tool()
def ollama_show_model(model_name: str) -> Dict[str, Any]:
    """Show model details and metadata."""
    return _svc.show_model(model_name)


@mcp.tool()
def ollama_running_models() -> List[Dict[str, Any]]:
    """List currently loaded models (ps)."""
    return _svc.running_models()


@mcp.tool()
def ollama_copy_model(source: str, destination: str) -> str:
    """Copy a model to a new name."""
    return _svc.copy_model(source, destination)


# Utility tools

@mcp.tool()
def ollama_health_check() -> Dict[str, Any]:
    """Verify Ollama is reachable and responsive."""
    return _svc.health_check()


@mcp.tool()
def ollama_embeddings(text: str, model: Optional[str] = None) -> List[float]:
    """Generate embeddings for the input text."""
    return _svc.embeddings(text, model)


@mcp.tool()
def ollama_benchmark(prompt: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
    """Short benchmark returning tokens/sec for the given model."""
    return _svc.benchmark(prompt or "Write a fibonacci function in Python.", model)


if __name__ == "__main__":
    _log.info(
        "Starting Ollama MCP server (small=%s, large=%s)",
        _cfg.small_model,
        _cfg.large_model,
    )
    mcp.run()
