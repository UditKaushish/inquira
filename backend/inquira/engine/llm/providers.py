"""LLM provider adapters behind one tiny interface: `complete(system, prompt) -> str`.

The pipeline only needs JSON-returning chat completion, so every provider is
reduced to that. Adding a provider means adding one class here.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from inquira.core.errors import ApiError
from inquira.engine.warehouse.base import FieldSpec


class LLMError(ApiError):
    def __init__(self, message: str) -> None:
        super().__init__(502, "llm_error", message)


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str | None = None
    base_url: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelInfo:
    id: str
    label: str | None = None


def _version_key(model_id: str) -> tuple[float, str]:
    m = re.search(r"(\d+(?:\.\d+)?)", model_id)
    return (-float(m.group(1)) if m else 0.0, model_id)


class LLMProvider(ABC):
    id: ClassVar[str]
    label: ClassVar[str]
    description: ClassVar[str]
    default_model: ClassVar[str]
    models: ClassVar[list[str]]
    fields: ClassVar[list[FieldSpec]] = [FieldSpec("api_key", "API key", "password", secret=True)]
    timeout_seconds: ClassVar[float] = 60.0

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    @abstractmethod
    def _complete(self, system: str, prompt: str) -> str: ...

    def _list_models(self) -> list[ModelInfo]:
        """Live model listing from the provider API. Override per provider."""
        raise NotImplementedError

    @classmethod
    def curated_models(cls) -> list[ModelInfo]:
        return [ModelInfo(m) for m in cls.models]

    def list_models(self) -> tuple[list[ModelInfo], str, str | None]:
        """Returns (models, source, message). Falls back to the curated list on any failure."""
        try:
            live = self._list_models()
        except NotImplementedError:
            return self.curated_models(), "curated", None
        except Exception as e:
            return self.curated_models(), "curated", _friendly_error(self.label, e)
        if not live:
            return self.curated_models(), "curated", f"{self.label} returned no usable chat models."
        return live, "live", None

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        try:
            text = self._complete(system, prompt)
        except ApiError:
            raise
        except Exception as e:  # provider SDKs raise many types; surface a clean message
            raise LLMError(_friendly_error(self.label, e)) from e
        return parse_json(text)


def _short(e: Exception) -> str:
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    # Never echo anything that looks like a credential (raw or provider-masked) back to the client.
    msg = re.sub(r"(sk-|AIza|key=)[A-Za-z0-9_\-*.]{4,}", r"\1***", msg)
    return msg[:300]


def _friendly_error(label: str, e: Exception) -> str:
    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    text = str(e).lower()
    if status in (401, 403) or any(k in text for k in ("api key", "api_key", "unauthorized", "authentication",
                                                        "permission denied")):
        return f"{label} rejected the API key. Check it's correct and active, and that it belongs to {label}."
    if status == 404 or "not found" in text and "model" in text:
        return f"{label} doesn't recognise that model name. Pick one of the suggested models in Settings."
    if status == 429 or "quota" in text or "rate limit" in text:
        return f"{label} is rate-limiting this key or its quota is exhausted. Try again shortly."
    if "timed out" in text or "timeout" in text:
        return f"{label} didn't respond in time. Please try again."
    if "connect" in text:
        return f"Couldn't reach {label}. Check the network or base URL."
    return f"{label} request failed: {_short(e)}"


# Recognisable key prefixes -> the provider that issued them.
_KEY_PREFIXES = [("sk-ant-", "anthropic"), ("AIza", "gemini"), ("sk-", "openai")]


def detect_key_provider(api_key: str | None) -> str | None:
    for prefix, provider in _KEY_PREFIXES:
        if api_key and api_key.strip().startswith(prefix):
            return provider
    return None


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("The model did not return JSON.")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise LLMError("The model returned malformed JSON.") from e
    if not isinstance(data, dict):
        raise LLMError("The model returned an unexpected JSON shape.")
    return data


class GeminiProvider(LLMProvider):
    id = "gemini"
    label = "Google Gemini"
    description = "Fast and cost-effective. A generous free tier is available from Google AI Studio."
    default_model = "gemini-2.5-flash"
    models = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite", "gemini-3.5-flash"]
    # Models that can't do text-to-JSON chat (speech, image, music, agents, ...).
    _EXCLUDE = re.compile(r"tts|image|banana|lyria|transcribe|robotics|computer-use|antigravity|deep-research|"
                          r"customtools|embedding|aqa|imagen|veo|omni|live|audio", re.I)

    def _list_models(self) -> list[ModelInfo]:
        from google import genai

        client = genai.Client(api_key=self.config.api_key)
        out = []
        for m in client.models.list():
            mid = (m.name or "").removeprefix("models/")
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions and mid.startswith(("gemini", "gemma")) and not self._EXCLUDE.search(mid):
                out.append(ModelInfo(mid, m.display_name or None))
        return sorted(out, key=lambda m: (m.id.startswith("gemma"), *_version_key(m.id)))

    def _complete(self, system: str, prompt: str) -> str:
        from google import genai
        from google.genai import types

        client = genai.Client(
            api_key=self.config.api_key,
            http_options=types.HttpOptions(timeout=int(self.timeout_seconds * 1000)),
        )
        resp = client.models.generate_content(
            model=self.config.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system, temperature=0.0, response_mime_type="application/json"
            ),
        )
        return resp.text or ""


class AnthropicProvider(LLMProvider):
    id = "anthropic"
    label = "Anthropic Claude"
    description = "Excellent at reasoning over complex schemas and multi-step analytics."
    default_model = "claude-sonnet-5-5"
    models = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-4-5-20251001"]

    def _list_models(self) -> list[ModelInfo]:
        import anthropic

        client = anthropic.Anthropic(api_key=self.config.api_key, timeout=20)
        return [ModelInfo(m.id, getattr(m, "display_name", None)) for m in client.models.list(limit=100)]

    def _complete(self, system: str, prompt: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.config.api_key, timeout=self.timeout_seconds)
        resp = client.messages.create(
            model=self.config.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")


class OpenAIProvider(LLMProvider):
    id = "openai"
    label = "OpenAI"
    description = "GPT models via the OpenAI API."
    default_model = "gpt-4.1-mini"
    models = ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o"]
    _INCLUDE = re.compile(r"^(gpt-|o\d|chatgpt-)", re.I)
    _EXCLUDE = re.compile(r"audio|realtime|tts|transcribe|search|image|embedding|instruct|codex|moderation", re.I)

    def _client(self) -> Any:
        from openai import OpenAI

        return OpenAI(api_key=self.config.api_key, base_url=self.config.base_url, timeout=self.timeout_seconds)

    def _list_models(self) -> list[ModelInfo]:
        ids = [m.id for m in self._client().models.list()]
        chat = [i for i in ids if self._INCLUDE.search(i) and not self._EXCLUDE.search(i)]
        return [ModelInfo(i) for i in sorted(chat, key=_version_key)]

    def _complete(self, system: str, prompt: str) -> str:
        resp = self._client().chat.completions.create(
            model=self.config.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""


class OpenAICompatibleProvider(OpenAIProvider):
    id = "openai_compatible"
    label = "OpenAI-compatible / Local"
    description = "Ollama, vLLM, LM Studio, Groq, Together, OpenRouter: any OpenAI-compatible endpoint."
    default_model = "llama3.1:8b"
    models = ["llama3.1:8b", "qwen2.5-coder:14b", "mistral-small"]
    fields = [
        FieldSpec("base_url", "Base URL", placeholder="http://localhost:11434/v1"),
        FieldSpec("api_key", "API key", "password", required=False, secret=True, help="Optional for local servers."),
    ]

    def _client(self) -> Any:
        from openai import OpenAI

        return OpenAI(
            api_key=self.config.api_key or "not-needed", base_url=self.config.base_url, timeout=self.timeout_seconds
        )

    def _list_models(self) -> list[ModelInfo]:
        return [ModelInfo(m.id) for m in self._client().models.list()]

    def _complete(self, system: str, prompt: str) -> str:
        # Many local servers don't support response_format; rely on the prompt instead.
        resp = self._client().chat.completions.create(
            model=self.config.model,
            temperature=0,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content or ""


PROVIDERS: dict[str, type[LLMProvider]] = {
    p.id: p for p in (GeminiProvider, AnthropicProvider, OpenAIProvider, OpenAICompatibleProvider)
}


def build_llm(config: LLMConfig) -> LLMProvider:
    provider = PROVIDERS.get(config.provider)
    if provider is None:
        raise ApiError(400, "bad_request", f"Unknown LLM provider: {config.provider}")
    if not config.model:
        config.model = provider.default_model
    if any(f.name == "api_key" and f.required for f in provider.fields) and not config.api_key:
        raise ApiError(400, "llm_not_configured", f"{provider.label} needs an API key.")
    owner = detect_key_provider(config.api_key)
    if owner and owner != provider.id and provider.id != "openai_compatible":
        raise ApiError(400, "key_provider_mismatch",
                       f"That looks like a {PROVIDERS[owner].label} key, but {provider.label} is selected. "
                       f"Choose {PROVIDERS[owner].label} as the provider, or paste a {provider.label} key.")
    if provider.id == "openai_compatible" and not config.base_url:
        raise ApiError(400, "llm_not_configured", "A base URL is required for OpenAI-compatible providers.")
    return provider(config)
