from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import httpx

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)
settings = get_settings()


@dataclass
class LLMResponse:
    text: str
    tokens_used: int
    provider: str
    model: str


class LLMProvider(ABC):
    name: str = "base"
    model: str = "unknown"

    @abstractmethod
    async def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        ...


class MockLLMProvider(LLMProvider):
    name = "mock"
    model = "mock-v1"

    async def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        preview = prompt[:300].replace("\n", " ")
        tokens = max(50, len(prompt) // 4)
        return LLMResponse(
            text=f"[mock] Processed: {preview}",
            tokens_used=tokens,
            provider=self.name,
            model=self.model,
        )


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "temperature": 0.3},
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", len(text) // 4)
            return LLMResponse(text=text, tokens_used=tokens, provider=self.name, model=self.model)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    async def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 2048,
                    "system": system or "You are a helpful AI assistant.",
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["content"][0]["text"]
            usage = data.get("usage", {})
            tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            return LLMResponse(text=text, tokens_used=tokens, provider=self.name, model=self.model)


class GrokProvider(LLMProvider):
    name = "grok"

    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.x.ai/v1"

    async def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "messages": messages, "temperature": 0.3},
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            tokens = data.get("usage", {}).get("total_tokens", len(text) // 4)
            return LLMResponse(text=text, tokens_used=tokens, provider=self.name, model=self.model)


def _build_provider(name: str) -> LLMProvider | None:
    name = name.strip().lower()
    if name == "mock":
        return MockLLMProvider()
    if name == "openai" and settings.openai_api_key:
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    if name == "anthropic" and settings.anthropic_api_key:
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    if name == "grok" and settings.grok_api_key:
        return GrokProvider(settings.grok_api_key, settings.grok_model)
    return None


class FallbackLLMProvider(LLMProvider):
    """Try providers in order until one succeeds."""

    name = "fallback"
    model = "chain"

    def __init__(self, providers: list[LLMProvider]) -> None:
        if not providers:
            providers = [MockLLMProvider()]
        self._providers = providers
        self._active = providers[0]

    @property
    def active_provider(self) -> str:
        return self._active.name

    async def complete(self, prompt: str, *, system: str | None = None) -> LLMResponse:
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                result = await provider.complete(prompt, system=system)
                self._active = provider
                logger.info(
                    "llm_complete",
                    provider=result.provider,
                    model=result.model,
                    tokens=result.tokens_used,
                )
                return result
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "llm_provider_failed",
                    provider=provider.name,
                    error=str(exc),
                )
        if last_error:
            raise last_error
        return await MockLLMProvider().complete(prompt, system=system)


def _resolve_chain() -> list[str]:
    primary = (settings.llm_provider or "auto").lower()
    if primary == "auto":
        chain = [p.strip() for p in settings.llm_fallback_chain.split(",") if p.strip()]
    else:
        fallbacks = [p.strip() for p in settings.llm_fallback_chain.split(",") if p.strip()]
        chain = [primary] + [p for p in fallbacks if p != primary]
    if "mock" not in chain:
        chain.append("mock")
    return chain


def get_llm_provider() -> FallbackLLMProvider:
    chain = _resolve_chain()
    providers: list[LLMProvider] = []
    for name in chain:
        provider = _build_provider(name)
        if provider and not any(p.name == provider.name for p in providers):
            providers.append(provider)

    if not providers:
        providers = [MockLLMProvider()]

    active_names = [p.name for p in providers]
    logger.info("llm_chain_resolved", chain=active_names, primary=active_names[0])
    return FallbackLLMProvider(providers)


llm_provider = get_llm_provider()