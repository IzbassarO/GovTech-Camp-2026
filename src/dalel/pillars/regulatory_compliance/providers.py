"""LLM provider abstraction with a content-addressed response cache.

AlemLLM-ready provider architecture: any OpenAI-compatible endpoint is
configured entirely through environment variables (LLM_PROVIDER,
LLM_BASE_URL, LLM_API_KEY, LLM_MODEL) — no hardcoded credentials, URLs or
model names. The default pipeline runs WITHOUT a provider; tests use
MockProvider and never touch the network.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dalel.pillars.regulatory_compliance.config import (
    ENV_LLM_API_KEY,
    ENV_LLM_BASE_URL,
    ENV_LLM_MODEL,
    ENV_LLM_PROVIDER,
    LLM_TEMPERATURE,
    LLM_TIMEOUT_SECONDS,
)


class ProviderError(Exception):
    """Provider invocation failed (configuration or transport)."""


@dataclass
class LLMResponse:
    text: str  # raw provider output (validated elsewhere)
    provider_name: str
    model_name: str
    from_cache: bool = False


class LLMProvider:
    """Minimal structured-generation interface."""

    name: str = "base"
    model: str = ""

    def generate_structured(self, prompt: str) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class DisabledProvider(LLMProvider):
    """Explicitly disabled: any call is a programming error."""

    name = "disabled"

    def generate_structured(self, prompt: str) -> str:
        raise ProviderError("LLM provider is disabled; deterministic mode only")


@dataclass
class MockProvider(LLMProvider):
    """Deterministic in-memory provider for tests and offline demos.

    Responses are served in FIFO order; when the queue is exhausted the
    last response repeats. ``calls`` records every prompt verbatim."""

    responses: list[str] = field(default_factory=list)
    fail_with: str | None = None
    name: str = "mock"
    model: str = "mock-model"
    calls: list[str] = field(default_factory=list)

    def generate_structured(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self.fail_with is not None:
            raise ProviderError(self.fail_with)
        if not self.responses:
            raise ProviderError("MockProvider has no responses configured")
        if len(self.responses) > 1:
            return self.responses.pop(0)
        return self.responses[0]


@dataclass
class OpenAICompatibleProvider(LLMProvider):
    """Chat-completions call against a configurable OpenAI-compatible
    endpoint (AlemLLM-ready: endpoint/model/key come from configuration).

    Network access happens ONLY here and only when this provider is
    explicitly selected — never in tests, never by default."""

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    name: str = "openai-compatible"
    timeout_seconds: int = LLM_TIMEOUT_SECONDS

    def generate_structured(self, prompt: str) -> str:
        if not self.base_url or not self.model:
            raise ProviderError("openai-compatible provider requires LLM_BASE_URL and LLM_MODEL")
        import urllib.error
        import urllib.request

        payload = json.dumps(
            {
                "model": self.model,
                "temperature": LLM_TEMPERATURE,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.base_url.rstrip("/") + "/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"provider call failed: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("provider returned an unexpected payload shape") from exc
        if not isinstance(content, str):
            raise ProviderError("provider returned non-text content")
        return content


def provider_from_config(provider_name: str | None) -> LLMProvider | None:
    """Resolve the provider. ``None``/"none" → deterministic mode.

    CLI argument wins; otherwise the LLM_PROVIDER environment variable is
    consulted. Unknown names are a configuration error."""
    name = (provider_name or os.environ.get(ENV_LLM_PROVIDER) or "none").strip().lower()
    if name in ("", "none", "off"):
        return None
    if name == "disabled":
        return DisabledProvider()
    if name == "mock":
        return MockProvider(
            responses=[
                json.dumps(
                    {
                        "label": "insufficient_evidence",
                        "confidence": 0.3,
                        "rationale": "Mock provider default response.",
                    }
                )
            ]
        )
    if name == "openai-compatible":
        return OpenAICompatibleProvider(
            base_url=os.environ.get(ENV_LLM_BASE_URL, ""),
            api_key=os.environ.get(ENV_LLM_API_KEY, ""),
            model=os.environ.get(ENV_LLM_MODEL, ""),
        )
    raise ProviderError(
        f"unknown LLM provider {name!r} (supported: none, disabled, mock, openai-compatible)"
    )


@dataclass
class ResponseCache:
    """Content-addressed response cache: sha256(provider|model|prompt) →
    validated raw response. JSONL on disk, deterministic ordering."""

    path: Path | None
    entries: dict[str, str] = field(default_factory=dict)
    dirty: bool = False

    @classmethod
    def load(cls, path: Path | None) -> ResponseCache:
        cache = cls(path=path)
        if path is not None and path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                cache.entries[str(record["prompt_hash"])] = str(record["response"])
        return cache

    def get(self, prompt_hash: str) -> str | None:
        return self.entries.get(prompt_hash)

    def put(self, prompt_hash: str, response: str) -> None:
        if self.entries.get(prompt_hash) != response:
            self.entries[prompt_hash] = response
            self.dirty = True

    def save(self) -> None:
        if self.path is None or not self.dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="\n") as handle:
            for key in sorted(self.entries):
                handle.write(
                    json.dumps(
                        {"prompt_hash": key, "response": self.entries[key]},
                        ensure_ascii=False,
                    )
                )
                handle.write("\n")


def response_hash(response_text: str) -> str:
    return hashlib.sha256(response_text.encode("utf-8")).hexdigest()
