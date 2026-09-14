"""
Conversation Gateway (Objective 1) — validates conversation state, mints the
turn, attaches correlation, then executes the ConversationPlan through every
layer in order. It owns the transaction boundary for one turn (commits on
every exit path), the same way the workers own it for their jobs.

Decisions live in the planner; execution order lives here; logic lives in
the layers. No layer below this one knows any other layer exists.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.document_platform.conversation.assistant import answer_directly
from app.document_platform.conversation.attribution import attribute
from app.document_platform.conversation.citations import CitationBuilder, CitationOutcome
from app.document_platform.conversation.context import ConversationContext
from app.document_platform.conversation.context_builder import ContextBuilder, ContextBundle
from app.document_platform.conversation.events import (
    ConversationEvent,
    ConversationEventType,
    PersistingConversationEventPublisher,
)
from app.document_platform.conversation.intent import IntentType, get_intent_classifier
from app.document_platform.conversation.llm import STREAM_SLICE, get_llm_provider
from app.document_platform.conversation.memory import ConversationMemory
from app.document_platform.conversation.metrics import ConversationMetricsCollector
from app.document_platform.conversation.planner import ConversationPlanner
from app.document_platform.conversation.prompts import (
    REFUSAL_SENTENCE,
    UNVERIFIED_SENTENCE,
    PromptBuilder,
    StructuredPrompt,
)
from app.document_platform.conversation.ranking import RankingEngine
from app.document_platform.conversation.reasoning import ReasoningEngine, ReasoningError
from app.document_platform.conversation.repository import ConversationRepository
from app.document_platform.conversation.retrieval import RetrievalEngine, RetrievalResult
from app.document_platform.conversation.streaming import StreamingEngine
from app.document_platform.conversation.validator import ResponseValidator
from app.document_platform.semantic.repository import SemanticRepository


_UNKNOWN_MARKER = re.compile(r"\s*\[S\d+\]")


def _recoverable(refusal_reason: str | None) -> bool:
    """True when the answer failed over its markers and nothing else.

    Two failures qualify, and they are the same failure wearing different
    clothes. ``missing_citations`` is a model that wrote none;
    ``invented_citations`` is a model that wrote ones that do not resolve -
    measured, it produced [S3] and [S4] against a two-source bundle. Neither
    says anything about whether the sources support the answer, which is the
    question that actually matters and is settled further down by asking the
    sources.

    A grounding score below the floor is NOT recoverable: there the citation
    resolved and the source it points at does not support the claim well
    enough, which is a real verdict and must stand.
    """
    if not refusal_reason or not refusal_reason.startswith("validation_failed:"):
        return False
    reasons = refusal_reason.split(":", 1)[1].split(";")
    return all(
        reason == "missing_citations" or reason.startswith("invented_citations")
        for reason in reasons
    )


def _strip_unknown_markers(text: str, bundle: ContextBundle) -> str:
    """Delete citation markers that point at no source.

    A marker that resolves to nothing conveys nothing, so removing it loses no
    information - and what is left is either an answer with real citations, or
    an uncited answer that then has to earn its attribution like any other.
    Keeping it would be the actual danger: it looks like provenance and is not.
    """
    known = bundle.source_ids
    return _UNKNOWN_MARKER.sub(
        lambda m: m.group(0) if m.group(0).strip() in
        {f"[{sid}]" for sid in known} else "",
        text,
    )


def _scalar_doc(document_id: str | list[str] | None) -> str | None:
    """The turn row's document_id column stores a single id; a multi-document
    scope is tracked by the workspace layer's conversation_documents table."""
    if isinstance(document_id, list):
        return document_id[0] if len(document_id) == 1 else None
    return document_id


@dataclass
class TurnResult:
    turn_id: str
    conversation_id: str
    correlation_id: str
    status: str                      # completed | rejected | failed
    intent: str
    answer: Optional[str]
    grounded: bool
    grounding_score: Optional[float]
    refusal_reason: Optional[str]
    citations: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class ConversationGateway:
    def __init__(self, db: AsyncSession) -> None:
        cfg = get_settings()
        self._db = db
        self._repo = ConversationRepository(db)
        self._events = PersistingConversationEventPublisher(self._repo)
        self._intent = get_intent_classifier()
        self._planner = ConversationPlanner(cfg.dip_retrieval_top_k)
        self._retrieval = RetrievalEngine(SemanticRepository(db))
        self._ranking = RankingEngine()
        self._context_builder = ContextBuilder(cfg.dip_context_token_budget)
        self._prompt_builder = PromptBuilder()
        self._reasoning = ReasoningEngine(get_llm_provider(), cfg.dip_llm_max_retries)
        self._memory = ConversationMemory(self._repo, cfg.dip_history_max_turns)
        self._citation_builder = CitationBuilder()
        self._validator = ResponseValidator(cfg.dip_grounding_min_score)
        self._streaming = StreamingEngine()
        self._min_score = cfg.dip_grounding_min_score
        self._min_support = cfg.dip_attribution_min_support

    # ── Conversation lifecycle ───────────────────────────────────────────────

    async def start_conversation(self, user_id: str, org_id: str, title: str = ""):
        conv = await self._repo.create_conversation(user_id, org_id, title)
        await self._events.publish(ConversationEvent(
            event_type=ConversationEventType.CONVERSATION_STARTED,
            conversation_id=conv.id, correlation_id=conv.correlation_id,
        ))
        await self._db.commit()
        return conv

    # ── One turn, non-streaming ──────────────────────────────────────────────

    async def ask(
        self, conversation, question: str,
        document_id: str | list[str] | None = None,
    ) -> TurnResult:
        turn = await self._repo.create_turn(
            conversation, question, _scalar_doc(document_id))
        ctx = ConversationContext(
            conversation_id=conversation.id, turn_id=turn.id,
            user_id=conversation.user_id, org_id=conversation.org_id,
            question=question, correlation_id=turn.correlation_id,
            document_id=document_id,
        )
        collector = ConversationMetricsCollector()
        try:
            prepared = None
            async for kind, _payload in self._prepare_events(ctx, collector):
                if kind != "stage":                     # "refused" | "prepared"
                    prepared = _payload
            if isinstance(prepared, TurnResult):        # refused before the LLM
                await self._persist(turn, ctx, prepared, collector)
                return prepared

            prompt, bundle = prepared
            result = await self._answer_and_validate(ctx, prompt, bundle, collector)
            await self._persist(turn, ctx, result, collector)
            return result
        except ReasoningError as e:
            result = self._failure(ctx, str(e), collector)
            await self._persist(turn, ctx, result, collector)
            return result
        except Exception as e:
            logger.exception(f"Turn {turn.id} crashed: {e}")
            result = self._failure(ctx, f"internal error: {e}", collector)
            await self._persist(turn, ctx, result, collector)
            return result

    # ── One turn, streaming (SSE event tuples; router wraps in sse()) ────────

    async def ask_stream(
        self, conversation, question: str,
        document_id: str | list[str] | None = None,
    ) -> AsyncIterator[str]:
        turn = await self._repo.create_turn(
            conversation, question, _scalar_doc(document_id))
        ctx = ConversationContext(
            conversation_id=conversation.id, turn_id=turn.id,
            user_id=conversation.user_id, org_id=conversation.org_id,
            question=question, correlation_id=turn.correlation_id,
            document_id=document_id,
        )
        collector = ConversationMetricsCollector()
        fmt = self._streaming.format
        try:
            # meta first (the client learns the turn id immediately), then live
            # per-stage progress events while retrieval/ranking/context run —
            # the UI shows what is actually happening, not a generic spinner.
            yield fmt("meta", {
                "turn_id": turn.id, "conversation_id": conversation.id,
                "correlation_id": ctx.correlation_id,
            })
            prepared = None
            async for kind, _payload in self._prepare_events(ctx, collector):
                if kind == "stage":
                    yield fmt("stage", _payload)
                else:                                   # "refused" | "prepared"
                    prepared = _payload
            if isinstance(prepared, TurnResult):        # refused before the LLM
                await self._persist(turn, ctx, prepared, collector)
                # Stream the refusal like any other answer. A turn that ends
                # before the model is reached - nothing retrieved, nothing
                # confident enough, nothing supported - still has something to
                # say, and it was being put in the `done` frame only. The
                # surface builds its bubble from `token` frames, so the user
                # saw an empty reply and no reason for it: the question looked
                # answered and wasn't. This is the state a document sits in
                # while it is still queued for processing, which is exactly
                # when a person is most likely to ask about it.
                refused = prepared.answer or ""
                for index in range(0, len(refused), STREAM_SLICE):
                    yield fmt("token", {"text": refused[index : index + STREAM_SLICE]})
                yield fmt("citations", {"citations": [], "grounded": False,
                                        "grounding_score": 0.0})
                yield fmt("done", {"status": prepared.status,
                                   "refusal_reason": prepared.refusal_reason,
                                   "answer": prepared.answer,
                                   "intent": prepared.intent,
                                   "metrics": prepared.metrics})
                return

            prompt, bundle = prepared
            yield fmt("stage", {"stage": "generating_answer",
                                "detail": {"model": self._reasoning.provider.model_name}})
            await self._publish(ctx, ConversationEventType.RESPONSE_STREAM_STARTED)

            # Generate, validate, persist - and only then emit. Tokens used to
            # go out as they arrived, before the validator had seen them, so a
            # rejected answer was read by the user and then stored as NULL: it
            # was on screen, and gone on the next page load, with nothing to
            # explain where it went. There is no real token stream behind this
            # (both providers fetch the whole answer and pace it out), so
            # nothing is lost by deciding first and showing second.
            result = await self._answer_and_validate(ctx, prompt, bundle, collector)
            await self._persist(turn, ctx, result, collector)

            # Exactly what was saved, paced out so the surface still fills in.
            shown = result.answer or ""
            with collector.timed("streaming_ms"):
                for index in range(0, len(shown), STREAM_SLICE):
                    yield fmt("token", {"text": shown[index : index + STREAM_SLICE]})
            yield fmt("citations", {"citations": result.citations,
                                    "grounded": result.grounded,
                                    "grounding_score": result.grounding_score})
            yield fmt("done", {"status": result.status,
                               "refusal_reason": result.refusal_reason,
                               "metrics": result.metrics})
        except Exception as e:
            logger.exception(f"Streaming turn {turn.id} crashed: {e}")
            result = self._failure(ctx, str(e), collector)
            try:
                await self._persist(turn, ctx, result, collector)
            except Exception:
                logger.exception("Failed to persist failed streaming turn")
            yield fmt("error", {"message": "The response could not be generated.",
                                "turn_id": turn.id})

    # ── Shared pipeline stages ───────────────────────────────────────────────

    async def _prepare_events(
        self, ctx: ConversationContext, collector: ConversationMetricsCollector,
    ):
        """Intent → plan → retrieve → rank → context → prompt, as an event
        stream. Yields ("stage", {stage, detail}) progress tuples as each
        phase actually runs, then exactly one terminal tuple: ("refused",
        TurnResult) or ("prepared", (prompt, bundle)). One pipeline serves
        both ask() (which ignores stages) and ask_stream() (which forwards
        them as SSE so the UI can show real progress)."""
        yield "stage", {"stage": "understanding_question", "detail": {}}
        ctx.intent = self._intent.classify(ctx.question)
        await self._publish(ctx, ConversationEventType.INTENT_DETECTED,
                            detail={"intent": ctx.intent.value})
        ctx.plan = self._planner.plan(ctx.intent, ctx.document_id)

        if ctx.intent is IntentType.CONVERSATIONAL:
            # Spoken to, not searched. This never touches retrieval, so there
            # is nothing to cite and nothing to validate - and the turn is
            # recorded as ungrounded, which is the honest description of a
            # greeting and keeps it out of the grounded history the document
            # path reads back.
            yield "stage", {"stage": "thinking", "detail": {}}
            history = await self._memory.chat_window(ctx.conversation_id)
            reply = await answer_directly(
                ctx.question, reasoning=self._reasoning,
                conversation_id=ctx.conversation_id, user_id=ctx.user_id,
                org_id=ctx.org_id, history=history,
            )
            if reply is not None:
                yield "refused", TurnResult(
                    turn_id=ctx.turn_id, conversation_id=ctx.conversation_id,
                    correlation_id=ctx.correlation_id, status="completed",
                    intent=ctx.intent.value, answer=reply.text,
                    grounded=False, grounding_score=0.0, refusal_reason=None,
                    metrics={"answered_from": reply.source, "model": reply.model},
                )
                return
            # Nothing could answer even a greeting: fall through and let the
            # normal path produce its normal refusal rather than silence.

        if ctx.intent is IntentType.UNSUPPORTED:
            yield "refused", self._refusal(
                ctx, "unsupported_request",
                "This request isn't supported yet — I can answer questions about "
                "the documents in your knowledge base, but I can't generate files, "
                "code, or images.",
            )
            return

        yield "stage", {"stage": "searching_knowledge",
                        "detail": {"intent": ctx.intent.value}}
        with collector.timed("retrieval_ms"):
            retrieval: RetrievalResult = await self._retrieval.retrieve(
                ctx.plan.retrieval_strategy, ctx.question, ctx.org_id,
                ctx.plan.top_k, ctx.document_id,
            )
        await self._publish(ctx, ConversationEventType.RETRIEVAL_COMPLETED,
                            duration_ms=collector.metrics.retrieval_ms,
                            detail={"hits": len(retrieval.chunks),
                                    "dropped_stale": retrieval.dropped_stale})
        if not retrieval.chunks:
            yield "refused", self._refusal(ctx, "no_knowledge_found", REFUSAL_SENTENCE)
            return

        yield "stage", {"stage": "ranking_sources",
                        "detail": {"hits": len(retrieval.chunks)}}
        with collector.timed("ranking_ms"):
            ranked = self._ranking.rank(retrieval.chunks, retrieval.manifest_facts)
        await self._publish(ctx, ConversationEventType.RANKING_COMPLETED,
                            duration_ms=collector.metrics.ranking_ms,
                            detail={"top_confidence": round(ranked[0].confidence, 4)})

        yield "stage", {"stage": "reading_documents",
                        "detail": {"sources": len(ranked)}}
        facts = await self._repo.document_facts(
            sorted({r.chunk.document_id for r in ranked if r.chunk.document_id})
        )
        bundle = self._context_builder.build(ranked, facts)
        await self._publish(ctx, ConversationEventType.CONTEXT_BUILT,
                            detail={"sources": len(bundle.sources),
                                    "tokens": bundle.total_tokens,
                                    "truncated": bundle.truncated})
        if bundle.best_confidence < self._min_score:
            yield "refused", self._refusal(ctx, "low_confidence", REFUSAL_SENTENCE)
            return

        yield "stage", {"stage": "preparing_prompt",
                        "detail": {"sources": len(bundle.sources)}}
        history = await self._memory.window(ctx.conversation_id, ctx.document_id)
        prompt = self._prompt_builder.build(
            ctx.plan.reasoning_strategy, ctx.question, bundle, history,
        )
        await self._publish(ctx, ConversationEventType.PROMPT_GENERATED,
                            detail={"strategy": prompt.strategy,
                                    "history_turns": len(history)})
        yield "prepared", (prompt, bundle)

    async def _finalize(
        self, ctx: ConversationContext, answer_text: str, bundle: ContextBundle,
        collector: ConversationMetricsCollector,
    ) -> TurnResult:
        """Citations → validation → TurnResult."""
        all_chunk_ids = [cid for s in bundle.sources for cid in s.chunk_ids]
        pages = await self._repo.chunk_pages(all_chunk_ids)
        outcome: CitationOutcome = self._citation_builder.build(answer_text, bundle, pages)
        validation = self._validator.validate(answer_text, outcome, bundle)
        await self._publish(ctx, ConversationEventType.RESPONSE_VALIDATED,
                            status="completed" if validation.valid else "failed",
                            detail={"grounded": validation.grounded,
                                    "grounding_score": validation.grounding_score,
                                    "reasons": validation.reasons})
        collector.metrics.grounding_score = validation.grounding_score
        collector.metrics.citation_count = len(outcome.citations)

        if not validation.valid:
            # The model's text is not shown - it failed the grounding contract
            # and letting it through is exactly what the validator is for. But
            # the turn still gets a visible answer, because a turn stored with
            # no answer renders as a question the assistant never replied to,
            # and the user is left thinking their chat lost messages.
            return TurnResult(
                turn_id=ctx.turn_id, conversation_id=ctx.conversation_id,
                correlation_id=ctx.correlation_id, status="rejected",
                intent=ctx.intent.value if ctx.intent else "",
                answer=UNVERIFIED_SENTENCE, grounded=False,
                grounding_score=validation.grounding_score,
                refusal_reason="validation_failed:" + ";".join(validation.reasons),
            )
        return TurnResult(
            turn_id=ctx.turn_id, conversation_id=ctx.conversation_id,
            correlation_id=ctx.correlation_id, status="completed",
            intent=ctx.intent.value if ctx.intent else "",
            answer=answer_text, grounded=validation.grounded,
            grounding_score=validation.grounding_score,
            refusal_reason="no_knowledge_found" if validation.is_refusal else None,
            citations=[asdict(c) for c in outcome.citations],
        )

    async def _answer_and_validate(
        self, ctx: ConversationContext, prompt: StructuredPrompt,
        bundle: ContextBundle, collector: ConversationMetricsCollector,
    ) -> TurnResult:
        """Generate, validate, and repair a missing citation once.

        Only ``missing_citations`` is repaired. An invented citation or a
        grounding score below the floor means the answer is not supported by
        the sources, and asking again would be asking the model to justify
        something it should not have said.
        """
        with collector.timed("llm_ms"):
            llm_result = await self._reasoning.generate(prompt)
        collector.metrics.prompt_tokens = llm_result.prompt_tokens
        collector.metrics.completion_tokens = llm_result.completion_tokens
        await self._publish(ctx, ConversationEventType.REASONING_COMPLETED,
                            duration_ms=llm_result.latency_ms,
                            detail={"model": llm_result.model,
                                    "completion_tokens": llm_result.completion_tokens})

        result = await self._finalize(ctx, llm_result.text, bundle, collector)
        if result.status != "rejected" or not _recoverable(result.refusal_reason):
            return result

        # Markers pointing at nothing come off first. Often that alone settles
        # it: an answer citing [S1] and a hallucinated [S3] is a correctly
        # cited answer once the hallucination is gone.
        text = _strip_unknown_markers(llm_result.text, bundle)
        if text != llm_result.text:
            logger.info(f"Turn {ctx.turn_id}: dropped citations that resolve to nothing")
            cleaned = await self._finalize(ctx, text, bundle, collector)
            if cleaned.status == "completed":
                return cleaned

        logger.info(f"Turn {ctx.turn_id}: answer was uncited, asking for citations")
        repair = self._prompt_builder.build_repair(
            ctx.question, bundle, text,
        )
        try:
            repaired = await self._reasoning.generate(repair)
        except ReasoningError:
            repaired = None        # fall through to attribution
        if repaired is not None:
            collector.metrics.completion_tokens += repaired.completion_tokens
            second = await self._finalize(ctx, repaired.text, bundle, collector)
            if second.status == "completed":
                return second

        # The model would not mark its own answer - measured, it hands the
        # draft back unchanged - so the link is established from the evidence
        # instead: a paragraph whose content words are present in a source did
        # come from that source, whatever the model chose to type. This is a
        # stricter test than the marker it skipped, because a marker can sit
        # under an invented sentence and this cannot.
        attribution = attribute(text, bundle, self._min_support)
        if not attribution.attached:
            logger.info(
                f"Turn {ctx.turn_id}: no source supports this answer "
                f"(best {attribution.best_support}); the refusal stands"
            )
            return result
        logger.info(
            f"Turn {ctx.turn_id}: attributed {attribution.attached} paragraph(s) "
            f"to their sources by content (best {attribution.best_support})"
        )
        # Straight back through the same validator: the citations still have to
        # resolve and the grounding score still has to clear its floor.
        third = await self._finalize(ctx, attribution.text, bundle, collector)
        return third if third.status == "completed" else result

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _refusal(self, ctx: ConversationContext, reason: str, message: str) -> TurnResult:
        return TurnResult(
            turn_id=ctx.turn_id, conversation_id=ctx.conversation_id,
            correlation_id=ctx.correlation_id, status="completed",
            intent=ctx.intent.value if ctx.intent else "",
            answer=message, grounded=False, grounding_score=0.0,
            refusal_reason=reason,
        )

    def _failure(
        self, ctx: ConversationContext, error: str,
        collector: ConversationMetricsCollector,
    ) -> TurnResult:
        return TurnResult(
            turn_id=ctx.turn_id, conversation_id=ctx.conversation_id,
            correlation_id=ctx.correlation_id, status="failed",
            intent=ctx.intent.value if ctx.intent else "",
            answer=None, grounded=False, grounding_score=None,
            refusal_reason=None, error=error,
        )

    async def _persist(
        self, turn, ctx: ConversationContext, result: TurnResult,
        collector: ConversationMetricsCollector,
    ) -> None:
        metrics = collector.finish()
        # Anything the turn already recorded about itself survives. The timing
        # numbers are collected here, but facts like which engine answered are
        # known only where the answering happened, and overwriting the whole
        # dict silently dropped them on the way to the client.
        carried = dict(result.metrics or {})
        result.metrics = {
            "retrieval_ms": metrics.retrieval_ms, "ranking_ms": metrics.ranking_ms,
            "llm_ms": metrics.llm_ms, "streaming_ms": metrics.streaming_ms,
            "total_ms": metrics.total_ms, "prompt_tokens": metrics.prompt_tokens,
            "completion_tokens": metrics.completion_tokens,
            "total_tokens": metrics.total_tokens,
            "cost_estimate": metrics.cost_estimate,
            "grounding_score": metrics.grounding_score,
            "citation_count": metrics.citation_count,
        }
        result.metrics.update(
            {k: v for k, v in carried.items() if k not in result.metrics}
        )
        await self._repo.finish_turn(
            turn, status=result.status, answer=result.answer,
            intent=result.intent, grounded=result.grounded,
            refusal_reason=result.refusal_reason,
            citations_json=json.dumps(result.citations) if result.citations else None,
            metrics=metrics, llm_provider=self._reasoning.provider.name,
            llm_model=self._reasoning.provider.model_name, error=result.error,
        )
        event_type = (
            ConversationEventType.RESPONSE_FAILED if result.status == "failed"
            else ConversationEventType.RESPONSE_COMPLETED
        )
        await self._publish(
            ctx, event_type,
            status="failed" if result.status == "failed" else "completed",
            duration_ms=metrics.total_ms,
            detail={"status": result.status, "grounded": result.grounded,
                    "citation_count": metrics.citation_count},
        )
        await self._db.commit()

    async def _publish(
        self, ctx: ConversationContext, event_type: ConversationEventType,
        status: str = "completed", duration_ms: int | None = None,
        detail: dict | None = None,
    ) -> None:
        await self._events.publish(ConversationEvent(
            event_type=event_type, conversation_id=ctx.conversation_id,
            correlation_id=ctx.correlation_id, turn_id=ctx.turn_id,
            status=status, duration_ms=duration_ms, detail=detail or {},
        ))
