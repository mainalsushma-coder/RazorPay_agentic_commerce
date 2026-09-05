"""Minimal adapter for the agent's Ollama-shaped, non-streaming chat interface."""

from __future__ import annotations

import json
import logging
import os
import re
from collections import deque
from types import SimpleNamespace
from typing import Any

import httpx
from ollama import AsyncClient

logger = logging.getLogger(__name__)


def _safe_detail(value: Any, api_key: str) -> str | None:
    """Redact credentials and omit request/header echoes from remote messages."""
    if not isinstance(value, str):
        return None
    secrets = [api_key] + [
        value for name, value in os.environ.items()
        if any(marker in name.upper() for marker in ("KEY", "SECRET", "TOKEN", "PASSWORD"))
    ]
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        value = value.replace(secret, "[REDACTED]")
    if re.search(r'authorization|bearer|headers|messages|request[_ ]?(?:body|payload)|api[_ -]?key', value, re.I):
        return "[omitted: potentially sensitive provider detail]"
    value = re.sub(r'\b(?:sk-|rzp_)[A-Za-z0-9_-]+', '[REDACTED]', value)
    return value[:2000]


def _log_failure(response: httpx.Response | None, exc: Exception, model: str, api_key: str) -> None:
    detail = None
    if response is not None:
        try:
            payload = response.json()
            error = payload.get("error") if isinstance(payload, dict) else None
            # Only the error message, never the complete body or metadata/request.
            detail = _safe_detail(error.get("message") if isinstance(error, dict) else error, api_key)
        except (ValueError, UnicodeError):
            pass
    logger.warning(
        "Inference failure status=%s provider=openrouter model=%s error_type=%s message=%s",
        response.status_code if response is not None else None,
        _safe_detail(model, api_key), type(exc).__name__, detail,
    )


class InferenceConfigurationError(ValueError):
    """Safe configuration error containing names only, never supplied values."""


class InferenceError(RuntimeError):
    """Safe provider failure; remote error bodies are deliberately excluded."""


class _Message:
    def __init__(self, wire: dict[str, Any]):
        self.wire = wire
        self.content = wire.get("content")
        self.tool_calls = []
        for call in wire.get("tool_calls") or []:
            if not call.get("id") or call.get("type") != "function":
                raise ValueError("Invalid tool call")
            function = call["function"]
            arguments = json.loads(function["arguments"])
            if not isinstance(arguments, dict) or not function.get("name"):
                raise ValueError("Invalid tool arguments")
            self.tool_calls.append(SimpleNamespace(function=SimpleNamespace(
                name=function["name"], arguments=arguments,
            )))


def _messages_for_openrouter(messages: list[Any]) -> list[dict[str, Any]]:
    """Pair the unchanged agent's sequential tool results with original call IDs."""
    result = []
    pending: deque[dict[str, Any]] = deque()
    for message in messages:
        wire = dict(message.wire if isinstance(message, _Message) else message)
        if wire.get("role") == "assistant":
            pending.extend(wire.get("tool_calls") or [])
        elif wire.get("role") == "tool":
            call = pending.popleft()
            if wire.pop("tool_name") != call["function"]["name"]:
                raise ValueError("Unmatched tool result")
            wire["tool_call_id"] = call["id"]
        result.append(wire)
    return result


class OpenRouterClient:
    def __init__(self, *, api_key: str, model: str, max_tokens: int = 2048):
        self._api_key = api_key
        self.model = model
        self.max_tokens = max_tokens

    async def chat(self, *, model: str, messages: list[Any], tools: list[Any],
                   stream: bool = False) -> Any:
        response = None
        try:
            if stream:
                raise ValueError("Streaming is unsupported")
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={"model": self.model,
                          "max_tokens": self.max_tokens,
                          "messages": _messages_for_openrouter(messages),
                          "tools": tools, "stream": False,
                          "provider": {"require_parameters": True}},
                )
                response.raise_for_status()
                payload = response.json()
                if "error" in payload:
                    raise ValueError("Provider error")
                wire = payload["choices"][0]["message"]
                if wire.get("role") != "assistant":
                    raise ValueError("Invalid assistant response")
                return SimpleNamespace(message=_Message(wire))
        except Exception as exc:
            _log_failure(response, exc, self.model, self._api_key)
            # Keep remote diagnostics out of client-facing exceptions.
            raise InferenceError("OpenRouter inference failed; check configuration or retry.") from None


def create_chat_client() -> AsyncClient | OpenRouterClient:
    provider = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()
    if provider == "ollama":
        return AsyncClient()
    if provider != "openrouter":
        raise InferenceConfigurationError("LLM_PROVIDER must be ollama or openrouter.")
    model = os.environ.get("OPENROUTER_MODEL", "").strip()
    if not model:
        raise InferenceConfigurationError("OPENROUTER_MODEL is required when LLM_PROVIDER=openrouter.")
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise InferenceConfigurationError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter.")
    try:
        max_tokens = int(os.environ.get("OPENROUTER_MAX_TOKENS", "2048"))
        if max_tokens <= 0:
            raise ValueError
    except ValueError:
        raise InferenceConfigurationError("OPENROUTER_MAX_TOKENS must be a positive integer.") from None
    return OpenRouterClient(api_key=api_key, model=model, max_tokens=max_tokens)
