"""Wrapper around the official Ollama Python client.

Responsibilities:
  * Own a single Client instance (connection pooling, keep-alive).
  * Route each tool to small/large model via Config.model_for(tool).
  * Apply consistent defaults (temperature, num_predict, keep_alive).
  * Log latency + token counts so delegation ROI is measurable.
  * Translate ollama.ResponseError into actionable messages.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx
from ollama import Client, ResponseError

from config import Config
from logger_setup import get_logger


class OllamaService:
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._log = get_logger("ollama_mcp.service", cfg.log_level)
        self._client = Client(
            host=cfg.base_url,
            timeout=httpx.Timeout(cfg.request_timeout_seconds),
        )
        self._log.info(
            "OllamaService initialized host=%s small=%s large=%s",
            cfg.base_url,
            cfg.small_model,
            cfg.large_model,
        )

    def _resolve_model(self, tool: str, override: Optional[str]) -> str:
        """Explicit override wins; otherwise pick by tool_model_map."""
        return override or self._cfg.model_for(tool)

    def _build_options(
        self,
        temperature: Optional[float],
        num_predict: Optional[int],
    ) -> Dict[str, Any]:
        return {
            "temperature": temperature if temperature is not None else self._cfg.default_temperature,
            "num_predict": num_predict if num_predict is not None else self._cfg.default_num_predict,
        }

    def _log_metrics(self, tool: str, model: str, resp: Any, elapsed: float) -> None:
        prompt_tokens = getattr(resp, "prompt_eval_count", None)
        eval_tokens = getattr(resp, "eval_count", None)
        total_duration_ns = getattr(resp, "total_duration", None)
        tps = None
        if eval_tokens and total_duration_ns:
            tps = eval_tokens / (total_duration_ns / 1e9)
        self._log.debug(
            "tool=%s model=%s elapsed=%.2fs prompt_tokens=%s eval_tokens=%s tokens_per_sec=%s",
            tool,
            model,
            elapsed,
            prompt_tokens,
            eval_tokens,
            f"{tps:.1f}" if tps else "n/a",
        )

    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        resolved = self._resolve_model("generate", model)
        t0 = time.perf_counter()
        try:
            resp = self._client.generate(
                model=resolved,
                prompt=prompt,
                system=system,
                options=self._build_options(temperature, max_tokens),
                keep_alive=self._cfg.keep_alive,
                stream=False,
            )
        except ResponseError as e:
            self._log.error("generate failed: %s (status=%s)", e.error, e.status_code)
            raise RuntimeError(f"Ollama generate error: {e.error}") from e
        elapsed = time.perf_counter() - t0
        self._log_metrics("generate", resolved, resp, elapsed)
        return resp.response

    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        if system:
            messages = [{"role": "system", "content": system}, *messages]
        resolved = self._resolve_model("chat", model)
        t0 = time.perf_counter()
        try:
            resp = self._client.chat(
                model=resolved,
                messages=messages,
                options=self._build_options(temperature, max_tokens),
                keep_alive=self._cfg.keep_alive,
                stream=False,
            )
        except ResponseError as e:
            self._log.error("chat failed: %s (status=%s)", e.error, e.status_code)
            raise RuntimeError(f"Ollama chat error: {e.error}") from e
        elapsed = time.perf_counter() - t0
        self._log_metrics("chat", resolved, resp, elapsed)
        return resp.message.content

    def run_prompted(
        self,
        tool_name: str,
        system: str,
        user: str,
        model: Optional[str] = None,
        budget: Optional[int] = None,
    ) -> str:
        """Shared path for specialized coding tools. Routes model by tool_name."""
        resolved = self._resolve_model(tool_name, model)
        max_tokens = budget if budget is not None else self._cfg.tool_budgets.get(tool_name)
        t0 = time.perf_counter()
        try:
            resp = self._client.chat(
                model=resolved,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                options=self._build_options(None, max_tokens),
                keep_alive=self._cfg.keep_alive,
                stream=False,
            )
        except ResponseError as e:
            self._log.error("%s failed: %s (status=%s)", tool_name, e.error, e.status_code)
            raise RuntimeError(f"Ollama {tool_name} error: {e.error}") from e
        elapsed = time.perf_counter() - t0
        self._log_metrics(tool_name, resolved, resp, elapsed)
        return resp.message.content

    def embeddings(self, text: str, model: Optional[str] = None) -> List[float]:
        resolved = self._resolve_model("embeddings", model)
        t0 = time.perf_counter()
        try:
            resp = self._client.embed(model=resolved, input=text)
        except ResponseError as e:
            self._log.error("embeddings failed: %s", e.error)
            raise RuntimeError(f"Ollama embeddings error: {e.error}") from e
        self._log.debug("tool=embeddings model=%s elapsed=%.2fs", resolved, time.perf_counter() - t0)
        vectors = resp.embeddings if hasattr(resp, "embeddings") else resp.get("embeddings", [])
        return vectors[0] if vectors else []

    def list_models(self) -> List[Dict[str, Any]]:
        resp = self._client.list()
        models = getattr(resp, "models", []) or resp.get("models", [])
        return [
            {
                "name": getattr(m, "model", None) or m.get("model") or m.get("name"),
                "size": getattr(m, "size", None) or m.get("size"),
                "modified_at": str(getattr(m, "modified_at", None) or m.get("modified_at", "")),
            }
            for m in models
        ]

    def show_model(self, name: str) -> Dict[str, Any]:
        resp = self._client.show(name)
        return {
            "modelfile": getattr(resp, "modelfile", None),
            "parameters": getattr(resp, "parameters", None),
            "template": getattr(resp, "template", None),
            "details": getattr(resp, "details", None).__dict__ if getattr(resp, "details", None) else None,
        }

    def pull_model(self, name: str) -> str:
        try:
            self._client.pull(name)
            return f"Model '{name}' pulled successfully"
        except ResponseError as e:
            raise RuntimeError(f"Pull error: {e.error}") from e

    def delete_model(self, name: str) -> str:
        try:
            self._client.delete(name)
            return f"Model '{name}' deleted"
        except ResponseError as e:
            raise RuntimeError(f"Delete error: {e.error}") from e

    def copy_model(self, source: str, destination: str) -> str:
        try:
            self._client.copy(source, destination)
            return f"Model copied: {source} -> {destination}"
        except ResponseError as e:
            raise RuntimeError(f"Copy error: {e.error}") from e

    def running_models(self) -> List[Dict[str, Any]]:
        resp = self._client.ps()
        running = getattr(resp, "models", []) or resp.get("models", [])
        return [
            {
                "name": getattr(m, "model", None) or m.get("model"),
                "size_vram": getattr(m, "size_vram", None) or m.get("size_vram"),
                "expires_at": str(getattr(m, "expires_at", None) or m.get("expires_at", "")),
            }
            for m in running
        ]

    def health_check(self) -> Dict[str, Any]:
        try:
            t0 = time.perf_counter()
            models = self.list_models()
            elapsed = time.perf_counter() - t0
            names = [m["name"] for m in models]
            return {
                "status": "ok",
                "base_url": self._cfg.base_url,
                "small_model": self._cfg.small_model,
                "large_model": self._cfg.large_model,
                "small_available": self._cfg.small_model in names,
                "large_available": self._cfg.large_model in names,
                "models_count": len(models),
                "latency_ms": round(elapsed * 1000, 1),
            }
        except Exception as e:
            return {"status": "error", "reason": str(e), "base_url": self._cfg.base_url}

    def benchmark(self, prompt: str = "Write a fibonacci function in Python.", model: Optional[str] = None) -> Dict[str, Any]:
        resolved = self._resolve_model("benchmark", model)
        t0 = time.perf_counter()
        try:
            resp = self._client.generate(
                model=resolved,
                prompt=prompt,
                options={"temperature": 0.0, "num_predict": 256},
                keep_alive=self._cfg.keep_alive,
                stream=False,
            )
        except ResponseError as e:
            raise RuntimeError(f"Benchmark error: {e.error}") from e
        elapsed = time.perf_counter() - t0
        eval_tokens = getattr(resp, "eval_count", 0) or 0
        total_duration_ns = getattr(resp, "total_duration", 0) or 0
        tps = eval_tokens / (total_duration_ns / 1e9) if total_duration_ns else 0
        return {
            "model": resolved,
            "elapsed_s": round(elapsed, 2),
            "eval_tokens": eval_tokens,
            "tokens_per_sec": round(tps, 1),
        }
