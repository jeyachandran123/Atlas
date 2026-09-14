"""Chat profiles — what kind of thinking a request needs, as data.

A profile is the whole answer to "how should the model be called for this?":
which model, whether it reasons before answering, how deterministic it is, how
much it may write and how long we will wait. Call sites name a profile; they
never pick a model, a temperature or a token budget themselves.

That is the point of the module. Before it, three different code paths each
called NVIDIA with their own model setting, their own temperature and their own
idea of whether thinking was on - so "which model is the app using" had three
answers, and changing it meant finding all three.

Two models back the profiles, one setting each:

* ``NVIDIA_CHAT_MODEL``      - everything interactive: general chat, coding,
                               planning, documents, code generation.
* ``NVIDIA_REASONING_MODEL`` - the deep modes a person deliberately chooses:
                               reasoning and mathematics.

The split is measured, not stylistic. On NVIDIA's hosted tier Nemotron 3 Super
120B returned its first token in 0.4s; Nemotron 3 Ultra 550B took 167s. Ultra is
the stronger reasoner, and a person who picks "Reasoning" is choosing depth over
speed - but three minutes before the first word of every chat turn is not a
chat. Setting both variables to the same model is supported and needs no code.

Anything finer is a per-profile override (``LLM_PROFILE_OVERRIDES``, JSON):

    LLM_PROFILE_OVERRIDES={"coding": {"model": "nvidia/nemotron-3-ultra-550b-a55b"}}
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from loguru import logger

ThinkingControl = Literal["auto", "enable_thinking", "thinking", "none"]
"""How a model is told whether to reason before answering.

Model families disagree on the name of the switch, and sending the wrong one is
silently ignored - the model just does whatever it does by default:

* Nemotron and Qwen:  ``chat_template_kwargs.enable_thinking``
* DeepSeek:           ``chat_template_kwargs.thinking``

``auto`` picks by model name, which is right for every model configured today;
the explicit values exist for a model whose name does not say what it is, and
``none`` for one with no switch at all.
"""

Tier = Literal["chat", "reasoning"]
"""Which of the two configured models a profile runs on by default."""


def thinking_kwarg(model: str, control: str = "auto") -> str | None:
    """The ``chat_template_kwargs`` key that turns thinking on or off for ``model``."""
    if control == "none":
        return None
    if control in ("enable_thinking", "thinking"):
        return control
    return "thinking" if "deepseek" in (model or "").lower() else "enable_thinking"


@dataclass(frozen=True)
class ChatProfile:
    name: str
    label: str
    description: str
    model: str
    thinking: bool
    temperature: float
    top_p: float
    max_tokens: int
    timeout_seconds: float
    thinking_control: ThinkingControl = "auto"
    tier: Tier = "chat"

    def as_public_dict(self) -> dict[str, Any]:
        """What the UI may see. Nothing here is secret, but it is also the
        contract the frontend's mode picker is built on, so it is explicit."""
        data = asdict(self)
        data.pop("thinking_control", None)
        return data


# ── Built-in profiles ─────────────────────────────────────────────────────────
#
# Budgets are latency budgets as much as length limits. A reasoning pass is
# paid for in output tokens before a single visible word is written, which is
# why the thinking profiles get several times the budget of the ones that
# answer directly - a thinking model given a small ceiling can spend all of it
# thinking and return nothing at all.
#
# Timeouts on the reasoning tier are long on purpose: they cover the hosted
# queue in front of the large model, not only its generation time.

GENERAL = "general"
REASONING = "reasoning"
MATH = "math"
CODING = "coding"
AGENT_PLANNING = "agent_planning"
DOCUMENT = "document"
CODEGEN = "codegen"
FAST = "fast"

_BUILTIN: dict[str, dict[str, Any]] = {
    GENERAL: dict(
        label="General",
        description="Everyday conversation, explanations and writing. Answers directly.",
        thinking=False, temperature=0.6, top_p=0.95, max_tokens=2048, timeout_seconds=120,
    ),
    REASONING: dict(
        label="Reasoning",
        description="The deepest model, thinking step by step. Slower; for hard questions.",
        thinking=True, temperature=0.6, top_p=0.95, max_tokens=16384, timeout_seconds=600,
        tier="reasoning",
    ),
    MATH: dict(
        label="Mathematics",
        description="The deepest model with careful, checked working. Slower.",
        thinking=True, temperature=0.2, top_p=0.95, max_tokens=16384, timeout_seconds=600,
        tier="reasoning",
    ),
    CODING: dict(
        label="Complex coding",
        description="Designs, writes and debugs non-trivial code, reasoning through it first.",
        thinking=True, temperature=0.2, top_p=0.95, max_tokens=8192, timeout_seconds=300,
    ),
    AGENT_PLANNING: dict(
        label="Agent planning",
        description="Breaks a goal into ordered, checkable steps and decides which tools to use.",
        thinking=True, temperature=0.3, top_p=0.95, max_tokens=4096, timeout_seconds=240,
    ),
    DOCUMENT: dict(
        label="Documents",
        description="Grounded answers from your documents, with citations. Direct and literal.",
        thinking=False, temperature=0.2, top_p=0.95, max_tokens=2048, timeout_seconds=180,
    ),
    CODEGEN: dict(
        label="Code generation",
        description="Writes the Python that transforms a document. Deterministic, no chatter.",
        thinking=False, temperature=0.1, top_p=0.95, max_tokens=2400, timeout_seconds=240,
    ),
    FAST: dict(
        label="Fast",
        description="Short internal tasks: titles, classification, one-line rewrites.",
        thinking=False, temperature=0.2, top_p=0.95, max_tokens=512, timeout_seconds=60,
    ),
}

PUBLIC_PROFILES = (GENERAL, REASONING, MATH, CODING, AGENT_PLANNING, DOCUMENT)
"""The ones a person chooses between. CODEGEN and FAST are internal."""

AGENT_MODE_PROFILES: dict[str, str] = {
    "auto": GENERAL,
    "business": GENERAL,
    "code": CODING,
    "reasoning": REASONING,
    "math": MATH,
    "planning": AGENT_PLANNING,
    "agent_planning": AGENT_PLANNING,
    "general": GENERAL,
    "coding": CODING,
    "document": DOCUMENT,
}
"""The chat module's agent modes, mapped onto profiles. Unknown modes fall back
to GENERAL rather than failing - an old client sending a mode this build does
not know should still get an answer."""


def profile_for_mode(agent_mode: str | None) -> str:
    return AGENT_MODE_PROFILES.get((agent_mode or "auto").strip().lower(), GENERAL)


def _overrides(settings: Any) -> dict[str, dict[str, Any]]:
    raw = str(getattr(settings, "llm_profile_overrides", "") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        # A typo in one override must not take chat down with it.
        logger.warning(f"LLM_PROFILE_OVERRIDES is not valid JSON ({e}); ignoring it")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("LLM_PROFILE_OVERRIDES must be a JSON object; ignoring it")
        return {}
    return {str(k): v for k, v in parsed.items() if isinstance(v, dict)}


_ALLOWED_OVERRIDE_FIELDS = {
    "model", "thinking", "temperature", "top_p", "max_tokens",
    "timeout_seconds", "thinking_control", "label", "description",
}


def _model_for(tier: str, settings: Any) -> str:
    chat = str(getattr(settings, "nvidia_chat_model", "") or "").strip()
    if tier == "reasoning":
        # No reasoning model configured means one model for everything.
        return str(getattr(settings, "nvidia_reasoning_model", "") or "").strip() or chat
    return chat


def resolve_profile(name: str | None, settings: Any = None) -> ChatProfile:
    """The profile called ``name``, with configuration applied."""
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    key = (name or GENERAL).strip().lower()
    if key not in _BUILTIN:
        logger.debug(f"Unknown chat profile {key!r}; using {GENERAL!r}")
        key = GENERAL

    spec = dict(_BUILTIN[key])
    tier = spec.get("tier", "chat")
    profile = ChatProfile(name=key, model=_model_for(tier, settings), **spec)

    override = _overrides(settings).get(key, {})
    clean = {k: v for k, v in override.items() if k in _ALLOWED_OVERRIDE_FIELDS}
    if clean:
        try:
            profile = replace(profile, **clean)
        except TypeError as e:
            logger.warning(f"Override for profile {key!r} rejected: {e}")
    return profile


def list_profiles(settings: Any = None, *, public_only: bool = True) -> list[ChatProfile]:
    names = PUBLIC_PROFILES if public_only else tuple(_BUILTIN)
    return [resolve_profile(n, settings) for n in names]
