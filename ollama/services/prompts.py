"""Specialized prompt templates.

Design principle: system prompts are deliberately strict so the model returns
only the useful payload (code, docstring, review bullets). This keeps the MCP
output compact and avoids wasting Claude's tokens on re-parsing chatty answers.
"""
from __future__ import annotations

from typing import Optional, Tuple


def _lang_hint(language: Optional[str]) -> str:
    return f" ({language})" if language else ""


def code_review(code: str, language: Optional[str], focus: Optional[str]) -> Tuple[str, str]:
    system = (
        "You are a senior reviewer. Output ONLY a markdown list with three sections: "
        "'Issues', 'Improvements', 'Verdict'. No preamble, no closing remarks. "
        "Keep each bullet under 20 words."
    )
    focus_line = f"\nFocus: {focus}." if focus else ""
    user = f"Review this code{_lang_hint(language)}.{focus_line}\n\n```\n{code}\n```"
    return system, user


def refactor(code: str, language: Optional[str], instructions: Optional[str]) -> Tuple[str, str]:
    system = (
        "You are a refactoring assistant. Output ONLY the refactored code inside a single "
        "fenced code block. Preserve public API and behavior unless explicitly told otherwise. "
        "Do not include explanations before or after the block."
    )
    extra = f"\nInstructions: {instructions}" if instructions else ""
    user = f"Refactor this{_lang_hint(language)}.{extra}\n\n```\n{code}\n```"
    return system, user


def explain(code: str, language: Optional[str], detail_level: Optional[str]) -> Tuple[str, str]:
    level = (detail_level or "medium").lower()
    length_hint = {"low": "2-3 sentences", "medium": "a short paragraph", "high": "multiple paragraphs with bullets"}.get(
        level, "a short paragraph"
    )
    system = (
        f"You explain code to a working engineer. Output {length_hint}. "
        "No intro like 'Sure!' or 'Here is'. Start directly with the explanation."
    )
    user = f"Explain this{_lang_hint(language)}:\n\n```\n{code}\n```"
    return system, user


def write_tests(code: str, language: Optional[str], framework: Optional[str]) -> Tuple[str, str]:
    system = (
        "You are a test engineer. Output ONLY a single fenced code block with the test file. "
        "Cover happy path, edge cases, error paths. Use AAA structure. No prose."
    )
    fw = f"\nFramework: {framework}." if framework else ""
    user = f"Write unit tests for this{_lang_hint(language)}.{fw}\n\n```\n{code}\n```"
    return system, user


def write_docstring(code: str, language: Optional[str], style: Optional[str]) -> Tuple[str, str]:
    system = (
        "You generate documentation. Output ONLY the full code with added docstrings/comments "
        "inside a single fenced code block. Match the language convention. No prose."
    )
    style_line = f"\nStyle: {style}." if style else ""
    user = f"Add docstrings to this{_lang_hint(language)}.{style_line}\n\n```\n{code}\n```"
    return system, user


def fix_bug(code: str, error_message: Optional[str], language: Optional[str]) -> Tuple[str, str]:
    system = (
        "You are a debugger. Output format (strict): "
        "'Root cause: <1 line>.' then a single fenced code block with the fixed code. "
        "No extra commentary."
    )
    err = f"\nError:\n{error_message}" if error_message else ""
    user = f"Fix this{_lang_hint(language)}.{err}\n\n```\n{code}\n```"
    return system, user
