"""UnityWorks Cognitive Integration Layer (Version 1 Integration Phase).

Adapters — and only adapters — that connect the existing UnityWorks *Body* (Document,
Knowledge, Semantic Intelligence, Conversation, Generation, Workspace platforms, the
Intent Detector, Context Builder, and Ollama infrastructure) to the completed
Cognitive Operating System *Brain* (Kernel, Runtime, State, and the eight engines).

The Cognitive OS becomes the central brain:

    Conversation -> Perception -> [Brain] -> Executive -> Generation -> Response

Nothing here redesigns an engine, a platform, or the Constitution. The cognitive
engines import no platform and no adapter; the adapters depend on *ports* (Protocols)
and are wired by dependency injection. A single feature flag, ``COGNITIVE_BRAIN_ENABLED``,
gates the whole layer — disabled, the existing production pipeline is untouched.
"""

from __future__ import annotations

from .flag import cognitive_brain_enabled
from .pipeline import CognitivePipeline, Deliberation
from .ports import (
    ContextPort,
    GenerationPort,
    IntentPort,
    IntentResult,
    LLMPort,
    PerceivedInput,
    PlatformActionPort,
    Turn,
    TurnResult,
)
from .session import CognitiveSession

__all__ = [
    "CognitiveSession",
    "CognitivePipeline",
    "Deliberation",
    "cognitive_brain_enabled",
    # ports & DTOs
    "IntentPort",
    "ContextPort",
    "LLMPort",
    "GenerationPort",
    "PlatformActionPort",
    "IntentResult",
    "PerceivedInput",
    "Turn",
    "TurnResult",
]
