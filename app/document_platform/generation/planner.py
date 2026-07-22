"""
Generation Planner — decides WHAT the artifact contains. Grounds the plan in
retrieved knowledge (consuming Phase 4's public RetrievalEngine /
RankingEngine / ContextBuilder, unchanged) and asks the LLM — through the
existing provider abstraction (Objective 20) wrapped in the existing
ReasoningEngine for retries — for a strict-JSON GenerationSpec. The LLM
never sees file formats' internals and never produces bytes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.config import get_settings
from app.document_platform.conversation.context_builder import ContextBuilder
from app.document_platform.conversation.llm import get_llm_provider
from app.document_platform.conversation.prompts import StructuredPrompt
from app.document_platform.conversation.ranking import RankingEngine
from app.document_platform.conversation.reasoning import ReasoningEngine
from app.document_platform.conversation.retrieval import RetrievalEngine
from app.document_platform.semantic.repository import SemanticRepository

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM = (
    "You are a document planning engine. You design the CONTENT PLAN for a "
    "business artifact; specialized software renders the file. Respond with "
    "ONLY a single valid JSON object — no prose, no markdown fences.\n"
    "Schema:\n"
    "{\n"
    '  "title": "string (required)",\n'
    '  "subtitle": "string (optional)",\n'
    '  "metadata": {"key": "value"},\n'
    '  "sections": [\n'
    "    {\n"
    '      "heading": "string",\n'
    '      "level": 1,\n'
    '      "paragraphs": ["string"],\n'
    '      "bullets": ["string"],\n'
    '      "table": {"name": "string", "headers": ["string"], '
    '"rows": [["string"]]}  // optional\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "Rules: if SOURCES are provided, base ALL factual content strictly on "
    "them — never invent facts. Table rows must be arrays of strings in "
    "header order. Prefer tables for tabular/spreadsheet outputs."
)


class PlanningError(Exception):
    """The LLM could not produce a parseable generation spec."""


@dataclass
class GenerationPlan:
    spec: dict[str, Any]
    grounded: bool
    source_knowledge_ids: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_provider: str = ""
    llm_model: str = ""


class GenerationPlanner:
    def __init__(self, semantic_repo: SemanticRepository) -> None:
        cfg = get_settings()
        self._retrieval = RetrievalEngine(semantic_repo)
        self._ranking = RankingEngine()
        self._context_builder = ContextBuilder(cfg.dip_context_token_budget)
        self._reasoning = ReasoningEngine(get_llm_provider(), cfg.dip_llm_max_retries)
        self._top_k = cfg.dip_retrieval_top_k

    async def plan(
        self, prompt: str, org_id: str, format_name: str,
        document_id: str | list[str] | None = None,
    ) -> GenerationPlan:
        sources_text = ""
        grounded = False
        knowledge_ids: list[str] = []
        retrieval = await self._retrieval.retrieve(
            "semantic", prompt, org_id, self._top_k, document_id,
        )
        if retrieval.chunks:
            ranked = self._ranking.rank(retrieval.chunks, retrieval.manifest_facts)
            bundle = self._context_builder.build(ranked)
            if bundle.sources:
                grounded = True
                knowledge_ids = sorted({s.knowledge_id for s in bundle.sources})
                sources_text = "# SOURCES\n" + "\n\n".join(
                    f"[{s.source_id}] {s.text}" for s in bundle.sources
                )

        user = (
            (sources_text + "\n\n" if sources_text else "")
            + f"# REQUEST\nTarget format: {format_name}\n{prompt}"
        )
        structured = StructuredPrompt(system=_SYSTEM, user=user, strategy="generation_plan")

        last_error: Exception | None = None
        prompt_tokens = completion_tokens = 0
        for _ in range(2):  # transport retries live in ReasoningEngine; this
            result = await self._reasoning.generate(structured)  # covers JSON drift
            prompt_tokens += result.prompt_tokens
            completion_tokens += result.completion_tokens
            try:
                spec = self._extract_json(result.text)
                return GenerationPlan(
                    spec=spec, grounded=grounded,
                    source_knowledge_ids=knowledge_ids,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    llm_provider=result.provider, llm_model=result.model,
                )
            except (json.JSONDecodeError, PlanningError) as e:
                last_error = e
        raise PlanningError(f"LLM did not return a valid generation spec: {last_error}")

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        cleaned = re.sub(r"```(?:json)?", "", text).strip()
        match = _JSON_BLOCK.search(cleaned)
        if not match:
            raise PlanningError("no JSON object in response")
        spec = json.loads(match.group(0))
        if not isinstance(spec, dict):
            raise PlanningError("top-level JSON is not an object")
        return spec
