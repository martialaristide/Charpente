"""Pluggable AI backend. Charpente must work fully (build/run/test/package)
with zero AI dependency installed and zero API key configured -- `ask` and
any AI-assisted diagnostics degrade to a clear, honest message instead of
crashing or silently doing nothing.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Optional


class AIProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool:
        """False means complete() would fail or is meaningless (no key,
        library not installed, endpoint unset) -- callers should check this
        before complete() to give a clean message instead of a stack trace."""

    @abstractmethod
    def complete(self, prompt: str, *, system: Optional[str] = None) -> str:
        ...


class NullProvider(AIProvider):
    """The default when nothing is configured. Every AI-touching command
    must work with this provider active -- that's the whole point."""

    name = "none"

    def is_available(self) -> bool:
        return False

    def complete(self, prompt: str, *, system: Optional[str] = None) -> str:
        return (
            "AI features are not configured. Set ANTHROPIC_API_KEY or "
            "OPENAI_API_KEY, or point CHARPENTE_AI_URL at a local "
            "OpenAI-compatible server (e.g. Ollama), to enable this."
        )


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model or os.environ.get("CHARPENTE_AI_MODEL", "claude-sonnet-4-5-20250929")

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def complete(self, prompt: str, *, system: Optional[str] = None) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self._api_key)
        response = client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system or "",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", "") == "text")


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model or os.environ.get("CHARPENTE_AI_MODEL", "gpt-4o-mini")

    def is_available(self) -> bool:
        if not self._api_key:
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def complete(self, prompt: str, *, system: Optional[str] = None) -> str:
        import openai
        client = openai.OpenAI(api_key=self._api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = client.chat.completions.create(model=self._model, messages=messages)
        return response.choices[0].message.content or ""


class LocalProvider(AIProvider):
    """Any OpenAI-compatible /v1/chat/completions endpoint -- Ollama,
    llama.cpp's server, LM Studio, etc. No extra dependency: stdlib
    urllib only, so this path never needs `pip install`."""

    name = "local"

    def __init__(self, base_url: str, model: Optional[str] = None, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._model = model or os.environ.get("CHARPENTE_AI_MODEL", "llama3")
        self._timeout = timeout

    def is_available(self) -> bool:
        return bool(self._base_url)

    def complete(self, prompt: str, *, system: Optional[str] = None) -> str:
        import json
        import urllib.request

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = json.dumps({"model": self._model, "messages": messages}).encode("utf-8")
        request = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]


def select_provider(env: Optional[dict] = None) -> AIProvider:
    """Resolution order: an explicit CHARPENTE_AI_PROVIDER override, then
    whichever API key is present, then a configured local endpoint,
    then NullProvider. Never raises -- always returns something usable."""
    env = os.environ if env is None else env

    forced = env.get("CHARPENTE_AI_PROVIDER", "").strip().lower()
    if forced == "anthropic":
        return AnthropicProvider(api_key=env.get("ANTHROPIC_API_KEY"))
    if forced == "openai":
        return OpenAIProvider(api_key=env.get("OPENAI_API_KEY"))
    if forced == "local":
        return LocalProvider(env.get("CHARPENTE_AI_URL", "http://localhost:11434/v1"))
    if forced == "none":
        return NullProvider()

    if env.get("ANTHROPIC_API_KEY"):
        return AnthropicProvider(api_key=env["ANTHROPIC_API_KEY"])
    if env.get("OPENAI_API_KEY"):
        return OpenAIProvider(api_key=env["OPENAI_API_KEY"])
    if env.get("CHARPENTE_AI_URL"):
        return LocalProvider(env["CHARPENTE_AI_URL"])
    return NullProvider()
