"""Composition — build a production CognitivePipeline (lazy singleton for the route).

Assembles the full slice from the production wrappers by default; every collaborator is
injectable, so tests build the same pipeline with fakes. Booting a brain is one-time.
"""

from __future__ import annotations

import threading
from typing import Any

from .adapters_prod import (
    ConversationContextAdapter,
    GenerationLLMAdapter,
    IntentDetectorAdapter,
    OllamaLLMAdapter,
)
from .generation import GenerationAdapter
from .perception import PerceptionAdapter
from .pipeline import CognitivePipeline
from .session import CognitiveSession


def build_pipeline(*, llm: Any | None = None, intent: Any | None = None, context: Any | None = None,
                   generator: Any | None = None, model: str | None = None) -> CognitivePipeline:
    llm = llm or OllamaLLMAdapter()
    session = CognitiveSession(llm, model=model)
    perception = PerceptionAdapter(intent or IntentDetectorAdapter(), context or ConversationContextAdapter())
    generation = GenerationAdapter(generator or GenerationLLMAdapter(llm, model=model))
    return CognitivePipeline(session, perception, generation)


_pipeline: CognitivePipeline | None = None
_lock = threading.Lock()


def get_pipeline() -> CognitivePipeline:
    """Lazily boot one shared brain for the route (thread-safe)."""
    global _pipeline
    with _lock:
        if _pipeline is None:
            _pipeline = build_pipeline()
        return _pipeline
