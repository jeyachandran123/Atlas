"""Provider selection — one environment variable, no code path per provider.

``DOCUMENT_VLM_PROVIDER=nvidia`` or ``DOCUMENT_VLM_PROVIDER=ollama`` decides
which adapter the composition root binds. Nothing else in the codebase reads
that variable, nothing branches on the value, and no business logic can observe
which way it went.

Adding Claude Vision, Gemini Vision, OpenAI Vision or Qwen Cloud is:

    from app.adapters.document_vlm.registry import register_document_vlm_provider
    register_document_vlm_provider("claude", build_claude_adapter)

...plus the adapter module itself. No file in ``app.document_platform`` changes,
no API code changes, no test of the pipeline changes. That is the claim this
module exists to keep honest, and ``test_provider_switching.py`` proves it by
registering a fictional provider and running the whole pipeline through it.

The registry is a *registry* rather than an ``if/elif`` chain for one concrete
reason: a chain lives in this file, so every new provider edits shared code that
every other provider depends on. Registration inverts that — the new provider
depends on the registry, and the registry never learns the new provider's name.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.document_platform.vlm.errors import (
    DocumentVLMConfigurationError,
    DocumentVLMUnsupportedProviderError,
)
from app.document_platform.vlm.ports import DocumentVLMPort, is_document_vlm

ProviderFactory = Callable[..., DocumentVLMPort]
"""``(settings, **kwargs) -> DocumentVLMPort``. Receives the whole settings
object so a provider can read its own fields without the registry knowing any
of them."""

ProviderDescriber = Callable[[Any], Mapping[str, Any]]
"""``(settings) -> {...}``. Optional. Reports a provider's effective
configuration for the operator-facing endpoint — *without* credentials.

Registered alongside the factory rather than written here, for the same reason
the factory is: a registry that reports ``nvidia_api_key`` has learned an NVIDIA
field name, and the next provider's fields would have to be learned too."""


@dataclass(frozen=True)
class _Registration:
    factory: ProviderFactory
    describe: ProviderDescriber | None = None


_REGISTRY: dict[str, _Registration] = {}
_LOCK = threading.Lock()

_CACHED: DocumentVLMPort | None = None
_CACHED_KEY: tuple[str, str] | None = None


# ── registration ─────────────────────────────────────────────────────────────


def register_document_vlm_provider(
    name: str,
    factory: ProviderFactory,
    *,
    describe: ProviderDescriber | None = None,
    replace: bool = False,
) -> None:
    """Make a provider selectable by ``DOCUMENT_VLM_PROVIDER=<name>``.

    Re-registering an existing name raises unless ``replace`` is explicit: two
    modules silently claiming ``"nvidia"`` would make which adapter answers a
    function of import order, which is the least debuggable kind of bug.
    """
    key = name.strip().lower()
    if not key:
        raise DocumentVLMConfigurationError("a VLM provider needs a non-empty name")
    with _LOCK:
        if key in _REGISTRY and not replace:
            raise DocumentVLMConfigurationError(
                f"VLM provider '{key}' is already registered; pass replace=True to "
                f"override it deliberately"
            )
        _REGISTRY[key] = _Registration(factory=factory, describe=describe)


def unregister_document_vlm_provider(name: str) -> None:
    """Remove a provider. Exists for tests; harmless in production."""
    with _LOCK:
        _REGISTRY.pop(name.strip().lower(), None)


def registered_providers() -> tuple[str, ...]:
    """Every selectable provider name, sorted."""
    with _LOCK:
        return tuple(sorted(_REGISTRY))


# ── construction ─────────────────────────────────────────────────────────────


def build_document_vlm(
    provider: str | None = None,
    *,
    settings: Any = None,
    **kwargs: Any,
) -> DocumentVLMPort:
    """Build the configured provider. The only place a provider is chosen.

    ``provider`` overrides configuration and exists for tests and for an
    operator's one-off comparison; production passes nothing and gets whatever
    the environment says.
    """
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    name = (provider or getattr(settings, "document_vlm_provider", "")).strip().lower()
    if not name:
        raise DocumentVLMConfigurationError(
            "DOCUMENT_VLM_PROVIDER is not set and no provider was requested"
        )

    with _LOCK:
        registration = _REGISTRY.get(name)
    if registration is None:
        raise DocumentVLMUnsupportedProviderError(
            f"DOCUMENT_VLM_PROVIDER='{name}' is not a registered provider; "
            f"available providers are: {', '.join(registered_providers()) or 'none'}"
        )

    adapter = registration.factory(settings, **kwargs)

    # Conformance at binding time, not at first use. An adapter missing
    # ``estimate_cost`` should fail when the app starts, not when a budget
    # policy consults it during a customer's upload.
    if not is_document_vlm(adapter):
        raise DocumentVLMConfigurationError(
            f"provider '{name}' produced {type(adapter).__name__}, which does not "
            f"implement DocumentVLMPort"
        )
    return adapter


def get_document_vlm(*, settings: Any = None) -> DocumentVLMPort:
    """The process-wide provider instance, built once.

    Cached on (provider, model) so a settings change in a test — or a reload in
    development — produces a new adapter instead of a stale one holding the old
    endpoint.
    """
    global _CACHED, _CACHED_KEY

    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    key = (
        str(getattr(settings, "document_vlm_provider", "")).lower(),
        str(_model_for(settings)),
    )
    if _CACHED is not None and _CACHED_KEY == key:
        return _CACHED

    adapter = build_document_vlm(settings=settings)
    with _LOCK:
        _CACHED = adapter
        _CACHED_KEY = key
    logger.info(
        f"Document VLM provider bound: {adapter.provider_name()}/{adapter.model_name()}"
    )
    return adapter


def reset_document_vlm_cache() -> None:
    """Drop the cached instance. For tests and for hot configuration reloads."""
    global _CACHED, _CACHED_KEY
    with _LOCK:
        _CACHED = None
        _CACHED_KEY = None


def _model_for(settings: Any) -> str:
    """The model the current provider would use — for cache keying only.

    Deliberately generic: it asks settings for ``<provider>_model`` rather than
    knowing any provider's field names, so a new provider needs no edit here.
    """
    provider = str(getattr(settings, "document_vlm_provider", "")).lower()
    return str(getattr(settings, f"{provider}_model", ""))


# ── description ──────────────────────────────────────────────────────────────


def describe_document_vlm(settings: Any = None) -> Mapping[str, Any]:
    """Configuration as an operator should see it: complete, and without secrets.

    Credentials are reported as *present or absent* — which is the only fact
    anybody debugging a 401 actually needs, and the only one safe to serve over
    HTTP.
    """
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    provider = str(getattr(settings, "document_vlm_provider", "")).lower()
    described: dict[str, Any] = {
        "provider": provider,
        "model": _model_for(settings),
        "available_providers": list(registered_providers()),
        "base_url": "",
        "api_key_configured": False,
        "timeout_seconds": getattr(settings, "document_vlm_timeout_seconds", None),
        "max_retries": getattr(settings, "document_vlm_max_retries", None),
        "max_output_tokens": getattr(settings, "document_vlm_max_output_tokens", None),
        "max_pages": getattr(settings, "document_vlm_max_pages", None),
        "prompt_version": getattr(settings, "document_vlm_prompt_version", None),
    }

    # Provider-specific detail comes from the provider, through the describer it
    # registered. The registry stays ignorant of every provider's field names,
    # which is what keeps "add a provider" from meaning "edit the registry".
    with _LOCK:
        registration = _REGISTRY.get(provider)
    if registration is not None and registration.describe is not None:
        described.update(redact_description(registration.describe(settings)))
    return described


def redact_description(described: Mapping[str, Any]) -> dict[str, Any]:
    """Last line of defence before configuration is served over HTTP.

    A describer is written by whoever adds a provider, and the one thing that
    must not depend on their diligence is whether a key reaches an operator's
    browser.
    """
    from app.document_platform.vlm.observability import redact

    return dict(redact(dict(described)))


# ── built-in providers ───────────────────────────────────────────────────────


def _register_builtin_providers() -> None:
    """Register the providers shipped in this build.

    Imported here rather than at module top so that a broken third-party
    adapter cannot take the registry — and therefore the whole document API —
    down with it at import time.
    """
    from app.adapters.document_vlm.nvidia import build_nvidia_adapter, describe_nvidia_config
    from app.adapters.document_vlm.ollama import build_ollama_adapter, describe_ollama_config

    for name, factory, describe in (
        ("nvidia", build_nvidia_adapter, describe_nvidia_config),
        ("ollama", build_ollama_adapter, describe_ollama_config),
    ):
        try:
            register_document_vlm_provider(name, factory, describe=describe)
        except DocumentVLMConfigurationError:
            pass  # already registered — a re-import, not a conflict


_register_builtin_providers()


__all__ = [
    "ProviderDescriber",
    "ProviderFactory",
    "build_document_vlm",
    "describe_document_vlm",
    "get_document_vlm",
    "register_document_vlm_provider",
    "registered_providers",
    "reset_document_vlm_cache",
    "unregister_document_vlm_provider",
]
