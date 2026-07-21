"""
Platform Capability Registry (Objective 5).

Generalizes the parser-only ParserCapabilities (kept, untouched — parsers
still declare theirs the same way) into a platform-wide, self-describing
registry any provider can join: document parsers, the OCR engine, the chunk
builder, storage providers, and — in future phases — embedding providers,
retrievers, reasoners, generators, vision providers, repository providers,
automation providers.

Providers REGISTER themselves; nothing here branches on provider identity.
A future embedding provider adds one `register()` call at import time —
zero changes to this module or to anything that already registered.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class CapabilityCategory(str, Enum):
    DOCUMENT_PARSER = "document_parser"
    OCR_ENGINE = "ocr_engine"
    CHUNK_BUILDER = "chunk_builder"
    EMBEDDING_PROVIDER = "embedding_provider"
    VECTOR_STORE = "vector_store"           # Phase 3 (Objective 15)
    SEMANTIC_INDEX = "semantic_index"       # Phase 3 (Objective 15)
    RETRIEVER = "retriever"
    RANKER = "ranker"                       # Phase 4 (Objective 5)
    LLM_PROVIDER = "llm_provider"           # Phase 4 (Objective 9)
    INTENT_CLASSIFIER = "intent_classifier"  # Phase 4 (Objective 2)
    REASONER = "reasoner"
    GENERATOR = "generator"
    STORAGE_PROVIDER = "storage_provider"
    VISION_PROVIDER = "vision_provider"
    REPOSITORY_PROVIDER = "repository_provider"
    AUTOMATION_PROVIDER = "automation_provider"


class CapabilityStatus(str, Enum):
    ACTIVE = "active"
    EXPERIMENTAL = "experimental"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


@dataclass(frozen=True)
class PlatformCapability:
    name: str
    category: CapabilityCategory
    version: str = "1.0.0"
    supported_features: frozenset[str] = field(default_factory=frozenset)
    limitations: frozenset[str] = field(default_factory=frozenset)
    dependencies: frozenset[str] = field(default_factory=frozenset)
    configuration: dict[str, Any] = field(default_factory=dict)
    status: CapabilityStatus = CapabilityStatus.ACTIVE

    @property
    def key(self) -> str:
        return f"{self.category.value}:{self.name}"


class CapabilityRegistry:
    """
    Process-wide registry. Providers call `register()` once, typically at
    module import time (mirroring the existing parser-registry pattern).
    Read access is used by the Knowledge Health evaluator (Objective 9) to
    detect when a Knowledge Object was built with a now-outdated capability
    version, and by the future /platform/capabilities endpoint.
    """

    def __init__(self) -> None:
        self._entries: dict[str, PlatformCapability] = {}

    def register(self, capability: PlatformCapability) -> None:
        self._entries[capability.key] = capability

    def get(self, category: CapabilityCategory, name: str) -> Optional[PlatformCapability]:
        return self._entries.get(f"{category.value}:{name}")

    def current_version(self, category: CapabilityCategory, name: str) -> Optional[str]:
        cap = self.get(category, name)
        return cap.version if cap else None

    def list_by_category(self, category: CapabilityCategory) -> list[PlatformCapability]:
        return sorted(
            (c for c in self._entries.values() if c.category == category),
            key=lambda c: c.name,
        )

    def all(self) -> list[PlatformCapability]:
        return sorted(self._entries.values(), key=lambda c: c.key)


_registry: CapabilityRegistry | None = None


def get_capability_registry() -> CapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = CapabilityRegistry()
        _register_document_platform_capabilities(_registry)
        _register_semantic_platform_capabilities(_registry)
        _register_conversation_platform_capabilities(_registry)
    return _registry


def _register_document_platform_capabilities(registry: CapabilityRegistry) -> None:
    """
    Registers today's DIP providers. Each parser already self-describes via
    ParserCapabilities (Phase 2.5) — this projects that into the platform-wide
    registry without duplicating the source of truth, plus the OCR service,
    chunker, and active storage backend.
    """
    from app.config import get_settings
    from app.document_platform.processing.parsers import get_parser_registry
    from app.document_platform.processing.versioning import CHUNK_VERSION

    parsers = get_parser_registry()
    seen: set[str] = set()
    for ext in parsers.supported_extensions:
        parser = parsers.get(ext)
        if parser is None or parser.name in seen:
            continue
        seen.add(parser.name)
        caps = parser.capabilities
        features = {
            f for f, on in (
                ("tables", caps.supports_tables),
                ("images", caps.supports_images),
                ("ocr_trigger", caps.supports_ocr_trigger),
                ("metadata", caps.supports_metadata),
                ("structure", caps.supports_structure),
                ("language_detection", caps.supports_language_detection),
                ("embedded_images", caps.supports_embedded_images),
            ) if on
        }
        registry.register(PlatformCapability(
            name=parser.name,
            category=CapabilityCategory.DOCUMENT_PARSER,
            version=parser.version,
            supported_features=frozenset(features),
        ))

    cfg = get_settings()
    registry.register(PlatformCapability(
        name="ocr_service",
        category=CapabilityCategory.OCR_ENGINE,
        version="1.0.0",
        supported_features=frozenset(),  # NullOcrProvider today — no extraction yet
        limitations=frozenset({"no_provider_configured"}),
        status=CapabilityStatus.EXPERIMENTAL,
    ))
    registry.register(PlatformCapability(
        name="structure_aware_chunker",
        category=CapabilityCategory.CHUNK_BUILDER,
        version=CHUNK_VERSION,
        supported_features=frozenset({"section_aware", "table_preserving"}),
    ))
    registry.register(PlatformCapability(
        name=cfg.storage_backend,
        category=CapabilityCategory.STORAGE_PROVIDER,
        version="1.0.0",
        supported_features=frozenset({"put", "get", "delete", "exists"} | (
            {"signed_url"} if cfg.storage_backend == "s3" else set()
        )),
    ))


def _register_semantic_platform_capabilities(registry: CapabilityRegistry) -> None:
    """
    Registers Phase 3's providers (Objective 15). The embedding provider and
    vector store self-describe their own name/version; nothing here
    hardcodes which one is active beyond reading it from config, exactly
    like storage_backend above.
    """
    from app.config import get_settings
    from app.document_platform.semantic.providers import get_embedding_provider
    from app.document_platform.semantic.vector_store import get_vector_store

    cfg = get_settings()

    try:
        provider = get_embedding_provider()
        registry.register(PlatformCapability(
            name=provider.name,
            category=CapabilityCategory.EMBEDDING_PROVIDER,
            version=provider.version,
            supported_features=frozenset({"embed"}),
            configuration={"model": provider.model_name, "timeout_seconds": provider.timeout_seconds},
        ))
    except Exception:
        pass  # provider construction depends on runtime config; never block startup

    try:
        vector_store = get_vector_store()
        registry.register(PlatformCapability(
            name=vector_store.name,
            category=CapabilityCategory.VECTOR_STORE,
            version="1.0.0",
            supported_features=frozenset(
                {"upsert", "delete", "count", "collection_exists", "search"}  # search: Phase 4
            ),
        ))
    except Exception:
        pass

    registry.register(PlatformCapability(
        name="dip_semantic_index",
        category=CapabilityCategory.SEMANTIC_INDEX,
        version="1.0.0",
        supported_features=frozenset({"create", "register", "stats", "query"}),  # query: Phase 4
        configuration={"vector_store_provider": cfg.dip_vector_store_provider},
    ))


def _register_conversation_platform_capabilities(registry: CapabilityRegistry) -> None:
    """Registers Phase 4's providers: the LLM provider, the semantic
    retriever, the multi-signal ranker, and the intent classifier."""
    from app.config import get_settings

    cfg = get_settings()

    try:
        from app.document_platform.conversation.llm import get_llm_provider
        provider = get_llm_provider()
        registry.register(PlatformCapability(
            name=provider.name,
            category=CapabilityCategory.LLM_PROVIDER,
            version="1.0.0",
            supported_features=frozenset({"generate", "stream"}),
            configuration={"model": provider.model_name},
        ))
    except Exception:
        pass  # never block startup on provider construction

    registry.register(PlatformCapability(
        name="semantic",
        category=CapabilityCategory.RETRIEVER,
        version="1.0.0",
        supported_features=frozenset(
            {"semantic_search", "metadata_filtering", "version_aware", "health_aware"}
        ),
        configuration={"vector_store_provider": cfg.dip_vector_store_provider},
    ))
    registry.register(PlatformCapability(
        name="multi_signal",
        category=CapabilityCategory.RANKER,
        version="1.0.0",
        supported_features=frozenset({"similarity", "health", "freshness", "version"}),
    ))
    registry.register(PlatformCapability(
        name="rule_based",
        category=CapabilityCategory.INTENT_CLASSIFIER,
        version="1.0.0",
        supported_features=frozenset({"deterministic", "pluggable"}),
    ))
