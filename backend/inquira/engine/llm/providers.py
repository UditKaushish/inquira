"""LLM provider adapters behind one tiny interface: `complete(system, prompt) -> str`.

The pipeline only needs JSON-returning chat completion, so every provider is
reduced to that. Adding a provider means adding one class here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, ClassVar

from inquira.core.errors import ApiError
from inquira.engine.warehouse.base import FieldSpec

log = logging.getLogger(__name__)

# Per-attempt timeout and retry budget. SDKs retry 408/409/429/5xx with jittered backoff and honour
# Retry-After; the pipeline's question deadline caps the total.
ATTEMPT_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2
_RETRYABLE_STATUS = [408, 429, 500, 502, 503, 504]

# Model availability probing. Providers list models an account can't actually call (Google lists
# Gemini 2.5 for new accounts, then rejects it as "no longer available to new users"), so every
# candidate gets a tiny real request before it's offered. Results are cached per key.
PROBE_MAX_MODELS = 24
PROBE_WORKERS = 8
PROBE_CACHE_SECONDS = 15 * 60
_UNAVAILABLE_HINTS = (
    # Phrases about the *model* itself. Generic ones like "not supported" are deliberately absent: they
    # also appear in parameter errors ("thinking level ... not supported") for models that work fine.
    "no longer available", "not found", "does not exist", "unsupported model",
    "is deprecated", "been deprecated", "shut down", "retired", "decommissioned", "do not have access",
    "does not have access", "not have access to the model", "model_not_found", "invalid model",
)
_probe_cache: dict[tuple, tuple[float, list[str]]] = {}
_probe_lock = threading.Lock()


def _is_unavailable_error(e: Exception) -> bool:
    """True only when the provider says the model itself can't be used by this account. Rate limits,
    parameter complaints and network errors return False so a working model is never hidden."""
    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    text = f"{e} {getattr(e, 'message', '') or ''}".lower()
    if status == 404:
        return True
    if status == 429 and "limit: 0" in text:
        return True  # the key's plan has zero quota for this model (e.g. Pro models on a free-tier key)
    return any(h in text for h in _UNAVAILABLE_HINTS)


# SDK clients own HTTP connection pools: reuse them instead of paying TCP+TLS setup on every call.
_clients: OrderedDict[tuple, Any] = OrderedDict()
_clients_lock = threading.Lock()


def _cached_client(provider: str, api_key: str | None, base_url: str | None, factory: Callable[[], Any]) -> Any:
    key = (provider, hashlib.sha256((api_key or "").encode()).hexdigest(), base_url or "")
    with _clients_lock:
        if key in _clients:
            _clients.move_to_end(key)
            return _clients[key]
        client = _clients[key] = factory()
        while len(_clients) > 32:
            _clients.popitem(last=False)
        return client


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

    def __init__(self, config: LLMConfig) -> None:
        self.config = config

    @abstractmethod
    def _complete(self, system: str, prompt: str) -> str: ...

    key_prefix: ClassVar[str | None] = None
    key_help: ClassVar[str | None] = None

    def key_format_hint(self) -> str | None:
        key = (self.config.api_key or "").strip()
        if self.key_prefix and key and not key.startswith(self.key_prefix):
            hint = f"{self.label} keys start with \u201c{self.key_prefix}\u201d, but this one doesn't."
            return f"{hint} {self.key_help}" if self.key_help else hint
        return None

    def _list_models(self) -> list[ModelInfo]:
        """Live model listing from the provider API. Override per provider."""
        raise NotImplementedError

    @classmethod
    def curated_models(cls) -> list[ModelInfo]:
        return [ModelInfo(m) for m in cls.models]

    # Preferred order (provider's current recommendations first); unlisted models follow.
    recommended: ClassVar[list[str]] = []
    probe_models: ClassVar[bool] = True

    def _probe(self, model_id: str) -> None:
        """Make the smallest possible real request to `model_id`; raise if it fails."""
        raise NotImplementedError

    def _order(self, models: list[ModelInfo]) -> list[ModelInfo]:
        rank = {m: i for i, m in enumerate(self.recommended)}
        return sorted(models, key=lambda m: (rank.get(m.id, len(rank)), 0))  # stable: keeps live order after

    def _available_ids(self, candidates: list[ModelInfo], refresh: bool) -> set[str]:
        key = (self.id, hashlib.sha256((self.config.api_key or "").encode()).hexdigest(), self.config.base_url or "")
        now = time.monotonic()
        with _probe_lock:
            hit = _probe_cache.get(key)
            if hit and not refresh and now - hit[0] < PROBE_CACHE_SECONDS:
                return set(hit[1])

        def check(model_id: str) -> str | None:
            try:
                self._probe(model_id)
            except Exception as e:
                if _is_unavailable_error(e):
                    log.info("%s model %s unavailable for this key: %s", self.label, model_id, _provider_detail(e))
                    return None
            return model_id

        with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
            ok = {m for m in pool.map(check, [c.id for c in candidates]) if m}
        with _probe_lock:
            _probe_cache[key] = (now, sorted(ok))
        return ok

    def list_models(self, refresh: bool = False) -> tuple[list[ModelInfo], str, str | None]:
        """Returns (models, source, message): only models this key can actually call, best first.
        Falls back to the curated list, with the reason, when listing fails."""
        try:
            live = self._list_models()
        except NotImplementedError:
            return self.curated_models(), "curated", None
        except Exception as e:
            return self.curated_models(), "curated", _friendly_error(self.label, e, self.key_format_hint())
        live = self._order(live)[:PROBE_MAX_MODELS]
        if live and self.probe_models:
            try:
                available = self._available_ids(live, refresh)
                live = [m for m in live if m.id in available]
            except NotImplementedError:
                pass
        if not live:
            return self.curated_models(), "curated", f"None of the models {self.label} listed are usable with this key."
        return live, "live", None

    def complete_json(self, system: str, prompt: str) -> dict[str, Any]:
        try:
            text = self._complete(system, prompt)
        except ApiError:
            raise
        except Exception as e:  # provider SDKs raise many types; surface a clean message
            raise LLMError(_friendly_error(self.label, e, self.key_format_hint())) from e
        return parse_json(text)


def _short(e: Exception) -> str:
    msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
    # Never echo anything that looks like a credential (raw or provider-masked) back to the client.
    msg = re.sub(r"(sk-|AIza|key=)[A-Za-z0-9_\-*.]{4,}", r"\1***", msg)
    return msg[:300]


def _provider_detail(e: Exception) -> str:
    """The provider's own explanation, without SDK noise or credentials."""
    detail = getattr(e, "message", None)
    body = getattr(e, "body", None)
    if not detail and isinstance(body, dict):
        err = body.get("error")
        detail = err.get("message") if isinstance(err, dict) else None
    detail = str(detail or _short(e)).strip().splitlines()[0]
    detail = re.sub(r"(sk-|AIza|key=)[A-Za-z0-9_\-*.]{4,}", r"\1***", detail)
    return detail[:240].rstrip(".")


def _friendly_error(label: str, e: Exception, key_hint: str | None = None) -> str:
    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    detail = _provider_detail(e)
    text = f"{e} {getattr(e, 'message', '') or ''} {detail}".lower()
    log.warning("%s error (status=%s): %s", label, status, detail)
    if "location is not supported" in text or "not available in your country" in text:
        return f"{label} isn't available from this server's region ({detail}). Use another provider or a proxy region."
    if "has not been used in project" in text or "service_disabled" in text or "is disabled" in text:
        return (f"The API isn't enabled for this key's Google Cloud project ({detail}). "
                f"Create a key at aistudio.google.com/apikey, or enable the Generative Language API.")
    if status in (401, 403) or any(k in text for k in ("api key", "api_key", "unauthorized", "authentication",
                                                        "permission denied", "invalid x-api-key")):
        msg = f"{label} rejected the API key: \u201c{detail}\u201d."
        return f"{msg} {key_hint}" if key_hint else f"{msg} Check that it's correct, active, and from {label}."
    if "no longer available" in text or "restricted" in text:
        return f"This {label} model isn't available to your account ({detail}). Pick one from the model list."
    if status == 404 or ("not found" in text and "model" in text):
        return f"{label} doesn't recognise that model ({detail}). Pick one from the model list."
    if status == 429 or "quota" in text or "rate limit" in text:
        return f"{label} is rate-limiting this key or its quota is exhausted ({detail})."
    if "timed out" in text or "timeout" in text:
        return f"{label} didn't respond in time. Please try again."
    if "connect" in text:
        return f"Couldn't reach {label}. Check the network or base URL."
    return f"{label} request failed: {detail}"


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
    # Per Google's model docs (Oct 2026): 2.5, 3.5-flash and 3.7-flash are restricted to accounts that
    # used them before; 3.8-flash is the recommended default for new projects.
    # 3.6-flash is the default: stable and fast (~2s). 3.8-flash is newer but took ~50s per call in
    # testing (Oct 2026), which doesn't fit a two-call answer inside the question deadline.
    default_model = "gemini-3.6-flash"
    recommended = ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                   "gemini-4-argon"]
    key_prefix = "AIza"
    key_help = ("Create one at aistudio.google.com/apikey "
                "(Google Cloud OAuth secrets or service-account keys won't work).")
    models = ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    # Models that can't do text-to-JSON chat (speech, image, music, agents, ...).
    _EXCLUDE = re.compile(r"tts|image|banana|lyria|transcribe|robotics|computer-use|antigravity|deep-research|"
                          r"customtools|embedding|aqa|imagen|veo|omni|live|audio", re.I)

    def _list_models(self) -> list[ModelInfo]:
        out = []
        client = self._client()
        for m in client.models.list():
            mid = (m.name or "").removeprefix("models/")
            actions = getattr(m, "supported_actions", None) or []
            if "generateContent" in actions and mid.startswith(("gemini", "gemma")) and not self._EXCLUDE.search(mid):
                out.append(ModelInfo(mid, m.display_name or None))
        # Newest first; previews, "-latest" aliases and Gemma after the stable Gemini models.
        return sorted(out, key=lambda m: (m.id.startswith("gemma"), "preview" in m.id or "latest" in m.id,
                                          *_version_key(m.id)))

    def _probe_client(self) -> Any:
        from google import genai
        from google.genai import types

        # No retries and a short timeout (Google rejects deadlines under 10s): probes must be fast and cheap.
        return _cached_client("gemini-probe", self.config.api_key, None, lambda: genai.Client(
            api_key=self.config.api_key, http_options=types.HttpOptions(timeout=12000)))

    def _probe(self, model_id: str) -> None:
        from google.genai import types

        client = self._probe_client()
        # 1) count_tokens is free and fast, and returns Google's "no longer available to new users" /
        #    "not found" errors for restricted or retired models.
        client.models.count_tokens(model=model_id, contents="ping")
        # 2) A 16-token generation reveals "limit: 0" quota (model not included in the key's plan).
        #    Slow models may time out here; that's inconclusive and the model is kept.
        client.models.generate_content(
            model=model_id, contents="Reply with OK.",
            config=types.GenerateContentConfig(max_output_tokens=16, temperature=0.0),
        )

    def _client(self) -> Any:
        from google import genai
        from google.genai import types

        # google-genai makes a single attempt unless retry options are given explicitly.
        return _cached_client(self.id, self.config.api_key, None, lambda: genai.Client(
            api_key=self.config.api_key,
            http_options=types.HttpOptions(
                timeout=int(ATTEMPT_TIMEOUT_SECONDS * 1000),
                retry_options=types.HttpRetryOptions(
                    attempts=MAX_RETRIES + 1, initial_delay=0.5, max_delay=8, http_status_codes=_RETRYABLE_STATUS),
            ),
        ))

    def _complete(self, system: str, prompt: str) -> str:
        from google.genai import types

        resp = self._client().models.generate_content(
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
    key_prefix = "sk-ant-"
    key_help = "Create one at console.anthropic.com/settings/keys."
    models = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-4-5-20251001"]
    recommended = ["claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-haiku-4-5-20251001"]

    def _probe(self, model_id: str) -> None:
        self._client().messages.create(model=model_id, max_tokens=16,
                                       messages=[{"role": "user", "content": "Reply with OK."}])

    def _list_models(self) -> list[ModelInfo]:
        client = self._client()
        return [ModelInfo(m.id, getattr(m, "display_name", None)) for m in client.models.list(limit=100)]

    def _client(self) -> Any:
        import anthropic

        return _cached_client(self.id, self.config.api_key, None, lambda: anthropic.Anthropic(
            api_key=self.config.api_key, timeout=ATTEMPT_TIMEOUT_SECONDS, max_retries=MAX_RETRIES))

    def _complete(self, system: str, prompt: str) -> str:
        resp = self._client().messages.create(
            model=self.config.model,
            # Generous: newer Claude models may think before answering, which counts against this.
            max_tokens=8192,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        if getattr(resp, "stop_reason", None) == "max_tokens":
            log.warning("Anthropic reply hit max_tokens (model=%s); output may be truncated", self.config.model)
        return "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")


class OpenAIProvider(LLMProvider):
    id = "openai"
    label = "OpenAI"
    description = "GPT models via the OpenAI API."
    default_model = "gpt-4.1-mini"
    key_prefix = "sk-"
    key_help = "Create one at platform.openai.com/api-keys."
    models = ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini", "gpt-4o"]
    _INCLUDE = re.compile(r"^(gpt-|o\d|chatgpt-)", re.I)
    _EXCLUDE = re.compile(r"audio|realtime|tts|transcribe|search|image|embedding|instruct|codex|moderation", re.I)

    def _client(self) -> Any:
        from openai import OpenAI

        return _cached_client(self.id, self.config.api_key, self.config.base_url, lambda: OpenAI(
            api_key=self.config.api_key, base_url=self.config.base_url,
            timeout=ATTEMPT_TIMEOUT_SECONDS, max_retries=MAX_RETRIES))

    def _probe(self, model_id: str) -> None:
        self._client().chat.completions.create(model=model_id, max_completion_tokens=16,
                                               messages=[{"role": "user", "content": "Reply with OK."}])

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
    key_prefix = None  # Groq, OpenRouter, Together, ... all use their own formats
    probe_models = False  # probing would make Ollama/vLLM load every model; their lists are already accurate
    models = ["llama3.1:8b", "qwen2.5-coder:14b", "mistral-small"]
    fields = [
        FieldSpec("base_url", "Base URL", placeholder="http://localhost:11434/v1"),
        FieldSpec("api_key", "API key", "password", required=False, secret=True, help="Optional for local servers."),
    ]

    def _client(self) -> Any:
        from openai import OpenAI

        # Local models can be slow to answer: give them a longer per-attempt timeout.
        return _cached_client(self.id, self.config.api_key, self.config.base_url, lambda: OpenAI(
            api_key=self.config.api_key or "not-needed", base_url=self.config.base_url,
            timeout=ATTEMPT_TIMEOUT_SECONDS * 2, max_retries=MAX_RETRIES))

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
