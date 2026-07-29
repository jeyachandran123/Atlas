"""Integration ports (Protocols) + DTOs — the seams between Body and Brain.

Every external collaborator the pipeline needs — the Intent Detector, the Context
Builder, the LLM (Ollama), the Generation pipeline, and platform actions — is
reached through a ``Protocol`` here. Production wrappers (``adapters_prod.py``) adapt
the *existing* components to these ports; tests inject fakes. This keeps the
integration testable and keeps zero hard imports of platforms or engines in the
orchestration. All ports are **synchronous** — the cognitive engines are synchronous,
so the pipeline runs in a worker thread and bridges to async infra at the edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


# --------------------------------------------------------------------------- #
# DTOs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Turn:
    """One conversational turn arriving from the Conversation Platform."""

    message: str
    conversation_id: str = "conv"
    user_id: str = "user"
    org_id: str = "org"
    mode: str = "auto"                       # auto | code | business (existing chat modes)
    history: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class IntentResult:
    """What the existing Intent Detector tells us about a message."""

    intent: str = "general"
    is_question: bool = True
    stakes: float = 0.1                      # 0..1 — drives the executive's autonomy threshold
    safety_relevant: bool = False
    irreversible: bool = False
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PerceivedInput:
    """The message rendered into cognitive terms by the Perception Adapter."""

    goal: str
    question: str
    intent: str
    stakes: float
    safety_relevant: bool
    reversibility: float
    goal_handle: str
    evidence_handles: tuple[str, ...]
    context_text: str


@dataclass(frozen=True, slots=True)
class TurnResult:
    """The pipeline's product for one turn."""

    reply: str
    authorized: bool
    decision: str
    escalated: bool
    conclusion: str | None
    confidence: float
    intent: str
    stages: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Ports (Protocols) — synchronous
# --------------------------------------------------------------------------- #


@runtime_checkable
class IntentPort(Protocol):
    """Reuses the existing Intent Detector."""

    def detect(self, message: str, history: list[Mapping[str, Any]]) -> IntentResult: ...


@runtime_checkable
class ContextPort(Protocol):
    """Reuses the existing Context Builder."""

    def build(self, message: str, turn: Turn) -> str: ...


@runtime_checkable
class LLMPort(Protocol):
    """Reuses the existing Ollama client (Qwen / DeepSeek / Llama). Synchronous."""

    def complete(self, prompt: str, *, system: str | None = None, model: str | None = None,
                 temperature: float = 0.15) -> str: ...


@runtime_checkable
class GenerationPort(Protocol):
    """Reuses the existing Generation pipeline to render the final reply."""

    def render(self, conclusion: str, context_text: str, turn: Turn) -> str: ...


@runtime_checkable
class PlatformActionPort(Protocol):
    """Reuses an existing platform (Document/Knowledge/Workspace/Generation) as an organ.

    An Executive-authorized action is dispatched here by name; the concrete platform
    is injected. The Executive never imports a platform — it authorizes; the adapter acts.
    """

    def execute(self, action: str, params: Mapping[str, Any]) -> Mapping[str, Any]: ...
