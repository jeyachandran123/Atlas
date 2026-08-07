"""Document VLM adapters — the provider-facing side of ``DocumentVLMPort``.

Shipped today:

``nvidia``
    NVIDIA's hosted Chat Completion API. Cloud, priced, catalogued.

``ollama``
    A local Ollama daemon. Free at the margin, private, and only as available as
    the model someone remembered to pull.

Both implement the same port with the same DTOs and the same error taxonomy, so
switching between them is ``DOCUMENT_VLM_PROVIDER`` and a restart.

Importing this package registers both with the registry. Nothing in
``app.document_platform`` imports it — the platform depends on the port, and the
composition root at the API edge depends on both.
"""

from app.adapters.document_vlm.base import HttpDocumentVLMAdapter, VLMAdapterConfig
from app.adapters.document_vlm.nvidia import (
    NvidiaDocumentVLMAdapter,
    build_nvidia_adapter,
)
from app.adapters.document_vlm.ollama import (
    OllamaDocumentVLMAdapter,
    build_ollama_adapter,
)
from app.adapters.document_vlm.registry import (
    build_document_vlm,
    describe_document_vlm,
    get_document_vlm,
    register_document_vlm_provider,
    registered_providers,
    reset_document_vlm_cache,
    unregister_document_vlm_provider,
)

__all__ = [
    "HttpDocumentVLMAdapter",
    "NvidiaDocumentVLMAdapter",
    "OllamaDocumentVLMAdapter",
    "VLMAdapterConfig",
    "build_document_vlm",
    "build_nvidia_adapter",
    "build_ollama_adapter",
    "describe_document_vlm",
    "get_document_vlm",
    "register_document_vlm_provider",
    "registered_providers",
    "reset_document_vlm_cache",
    "unregister_document_vlm_provider",
]
