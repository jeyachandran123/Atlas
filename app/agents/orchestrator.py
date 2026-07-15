"""
LangGraph orchestrator — V3 Execution Pipeline.

Graph flow:
  START
    ↓
  intelligence_prepare   Full ConversationIntelligenceEngine pipeline:
                         intent → complexity → conversation → policy →
                         persona → strategy → context → tool_plan →
                         reasoning → prompt composition
    ↓
  [POLICY BLOCK?]  → finalise (immediate refusal, no LLM)
    ↓
  [CLARIFY?]       → finalise (return clarification question, no LLM)
    ↓
  load_memory            load + filter session memory via ContextResolutionEngine
    ↓
  retrieve_context       fetch relevant code from ChromaDB (demand-driven)
    ↓
  plan_tools             IntelligenceToolPlanner (heuristic, no LLM call)
    ↓
  ┌──────────────────────────────────────────────────┐
  │ Tool Loop (max 5 iterations)                     │
  │   execute_tools → coding_agent → should_continue │
  └──────────────────────────────────────────────────┘
    ↓
  review_agent (optional — complex/code intents only)
    ↓
  finalise               ResponseReviewer + ResponseFormatter + memory save
    ↓
  END

Key changes from V2:
  - Removed _detect_intent(), _LANG_MAP, _FRAMEWORK_MAP and all duplicate keyword maps
  - Removed _self_correct_node (replaced by ResponseReviewer in finalise)
  - Removed LLM-based ToolPlanner (replaced by IntelligenceToolPlanner)
  - Clarification short-circuit: returns question before any LLM call
  - rewritten_query flows through state and is used by CodingAgent
  - execution_plan_summary flows through state for observability
  - IntelligenceTrace returned in final state for API-level observability
  - Corrections handled by ResponseFormatter, not blockquote injection
"""

from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph

from app.agents.coding_agent import CodingAgent
from app.agents.review_agent import (
    ReviewAgent,
    check_revision_decision,
    should_review_decision,
)
from app.agents.state import AgentState
from app.agents.tool_executor import get_tool_executor
from app.intelligence.context.resolver import ContextResolutionEngine, get_context_resolution_engine
from app.intelligence.engine import ConversationIntelligenceEngine, get_engine
from app.intelligence.models import ReviewDecision
from app.intelligence.tools.planner import IntelligenceToolPlanner, get_intelligence_tool_planner
from app.memory import MemoryManager, get_memory_manager
from app.ollama_client import get_ollama_client
from app.retrieval.context_builder import ContextBuilder
from app.retrieval.retriever import CodeRetriever
from app.shared.schemas import ToolCall
from app.vector_store.base import VectorStore


# ── Minimal safe fallback system prompt ──────────────────────────────────────
_FALLBACK_SYSTEM_PROMPT = (
    "You are Atlas, an AI engineering platform. "
    "Help the user with their software engineering question clearly and accurately."
)


class AgentOrchestrator:
    """
    V3 LangGraph orchestrator — Execution Pipeline Architecture.

    The backend owns all application-level decisions.
    The LLM owns only reasoning and generation.
    """

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        coding_agent: Optional[CodingAgent] = None,
        review_agent: Optional[ReviewAgent] = None,
        retriever: Optional[CodeRetriever] = None,
        context_builder: Optional[ContextBuilder] = None,
        memory_manager: Optional[MemoryManager] = None,
        intelligence_engine: Optional[ConversationIntelligenceEngine] = None,
        context_resolver: Optional[ContextResolutionEngine] = None,
        tool_planner: Optional[IntelligenceToolPlanner] = None,
    ) -> None:
        self._vs = vector_store
        self._coding_agent = coding_agent or CodingAgent()
        self._review_agent = review_agent or ReviewAgent()
        self._retriever = retriever
        self._context_builder = context_builder or ContextBuilder()
        self._memory = memory_manager or get_memory_manager()
        self._intelligence = intelligence_engine or get_engine()
        self._context_resolver = context_resolver or get_context_resolution_engine()
        # V3: heuristic tool planner — no LLM call required
        self._tool_planner = tool_planner or get_intelligence_tool_planner()
        self._tool_executor = get_tool_executor()
        self._graph = self._build_graph()

    # ── Graph construction ────────────────────────────────────────────────────

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(AgentState)

        graph.add_node("intelligence_prepare", self._intelligence_prepare_node)
        graph.add_node("load_memory",          self._load_memory_node)
        graph.add_node("retrieve_context",     self._retrieve_context_node)
        graph.add_node("plan_tools",           self._plan_tools_node)
        graph.add_node("execute_tools",        self._execute_tools_node)
        graph.add_node("coding_agent",         self._coding_agent_node)
        graph.add_node("should_continue",      self._should_continue_node)
        graph.add_node("review_agent",         self._review_agent_node)
        graph.add_node("increment_revision",   self._increment_revision_node)
        graph.add_node("finalise",             self._finalise_node)
        graph.add_node("post_review_finalise", self._post_review_finalise_node)

        graph.add_edge(START, "intelligence_prepare")

        # Short-circuit: policy block or clarification needed → skip LLM entirely
        graph.add_conditional_edges(
            "intelligence_prepare",
            self._after_intelligence,
            {
                "finalise":       "finalise",
                "load_memory":    "load_memory",
            },
        )

        graph.add_edge("load_memory",      "retrieve_context")
        graph.add_edge("retrieve_context", "plan_tools")

        graph.add_conditional_edges(
            "plan_tools",
            lambda s: "tools" if s["tool_calls"] else "agent",
            {"tools": "execute_tools", "agent": "coding_agent"},
        )

        graph.add_edge("execute_tools",  "coding_agent")
        graph.add_edge("coding_agent",   "should_continue")

        graph.add_conditional_edges(
            "should_continue",
            self._continue_router,
            {"plan_tools": "plan_tools", "finalise": "finalise"},
        )

        # After finalise: optionally run review for complex responses
        graph.add_conditional_edges(
            "finalise",
            lambda s: "review" if should_review_decision(s) == "review" and not s.get("refused") and not s.get("should_clarify") else "end",
            {"review": "review_agent", "end": END},
        )

        graph.add_conditional_edges(
            "review_agent",
            check_revision_decision,
            {"revise": "increment_revision", "finalise": "post_review_finalise"},
        )

        graph.add_edge("post_review_finalise", END)
        graph.add_edge("increment_revision", "plan_tools")

        return graph.compile()

    # ── Routing helpers ───────────────────────────────────────────────────────

    def _after_intelligence(self, state: AgentState) -> str:
        """Route after intelligence_prepare: short-circuit or proceed."""
        if state.get("refused"):
            return "finalise"
        if state.get("should_clarify"):
            return "finalise"
        return "load_memory"

    def _continue_router(self, state: AgentState) -> str:
        if state["current_step"] < state["max_steps"] and state.get("tool_calls"):
            return "plan_tools"
        return "finalise"

    # ── Nodes ─────────────────────────────────────────────────────────────────

    async def _intelligence_prepare_node(self, state: AgentState) -> AgentState:
        """
        V3: Full pre-LLM intelligence pipeline.

        Runs:
          IntentDetector → ComplexityAnalyzer → ConversationAnalyzer →
          PolicyEngine → PersonaEngine → StrategyPlanner →
          ContextBuilder → IntelligenceToolPlanner →
          ReasoningEngine (goal, rewrite, decompose, plan, confidence) →
          DynamicPromptComposer

        Outputs written to state:
          - intent, system_prompt
          - rewritten_query (from QueryRewriter)
          - should_clarify, clarification_question (from ConfidenceEvaluator)
          - execution_plan_summary (from ExecutionPlanner)
          - refused (from PolicyEngine BLOCK)
          - intelligence_context, intelligence_trace, intelligence_reasoning_result
        """
        from loguru import logger
        try:
            result = await self._intelligence.prepare(state)

            # ── Policy BLOCK ──────────────────────────────────────────────────
            if result.is_blocked:
                return {
                    **state,
                    "intent": "chat",
                    "system_prompt": "",
                    "draft_output": result.block_response or "I cannot help with that request.",
                    "refused": True,
                    "intelligence_context": result.context,
                    "intelligence_trace": result.trace,
                }

            # ── Extract rewritten query ───────────────────────────────────────
            rewritten_query = state["user_message"]
            reasoning = result.reasoning_result
            if reasoning and reasoning.rewritten_query.enrichments_applied:
                rewritten_query = reasoning.rewritten_query.rewritten

            # ── Extract clarification decision ────────────────────────────────
            should_clarify = False
            clarification_question = ""
            if reasoning and reasoning.should_clarify:
                should_clarify = True
                clarification_question = reasoning.clarification_question

            # ── Extract execution plan summary ────────────────────────────────
            execution_plan_summary = ""
            if reasoning and reasoning.execution_plan:
                execution_plan_summary = reasoning.execution_plan.plan_rationale

            # ── Map intelligence intent to legacy string ───────────────────────
            primary_intent = result.context.intent_analysis.primary.intent.value
            _intent_map = {
                "coding": "code", "debugging": "fix", "testing": "test",
                "refactoring": "code", "repository_question": "search",
                "documentation": "explain", "learning": "explain",
                "deep_teaching": "explain", "general_chat": "chat",
                "architecture": "code", "git_operations": "search",
                "tool_execution": "code", "planning": "chat",
                "brainstorming": "chat", "recommendation": "chat",
                "comparison": "chat", "research": "chat",
            }
            legacy_intent = _intent_map.get(primary_intent, "chat")

            return {
                **state,
                "intent": legacy_intent,
                "system_prompt": result.system_prompt,
                "rewritten_query": rewritten_query,
                "should_clarify": should_clarify,
                "clarification_question": clarification_question,
                "execution_plan_summary": execution_plan_summary,
                "intelligence_context": result.context,
                "intelligence_trace": result.trace,
                "intelligence_reasoning_result": reasoning,
                "refused": False,
                # Clear legacy detection fields — intelligence engine owns these now
                "detected_language": "",
                "detected_framework": "",
                "detected_database": "",
                "detected_cloud": "",
                "detected_business_domain": "",
                "detected_architecture": "",
                "detected_testing": "",
                "detected_security": False,
                "detected_ai_domain": False,
            }

        except Exception as e:
            logger.error(f"Intelligence engine failed: {e} — using safe fallback")
            # Minimal safe fallback: no duplicate keyword maps, no LLM call
            return {
                **state,
                "intent": "chat",
                "system_prompt": _FALLBACK_SYSTEM_PROMPT,
                "rewritten_query": state["user_message"],
                "should_clarify": False,
                "clarification_question": "",
                "execution_plan_summary": "",
                "refused": False,
            }

    async def _load_memory_node(self, state: AgentState) -> AgentState:
        try:
            memory_context = await self._memory.get_context(
                user_id=state["user_id"],
                conversation_id=state["conversation_id"],
                org_id=state["org_id"],
                repo_id=state.get("repo_id"),
                query=state["user_message"],
                session_limit=10,
                ltm_limit=3,
            )
            session_messages = await self._memory.get_messages(
                user_id=state["user_id"],
                conversation_id=state["conversation_id"],
                limit=10,
            )

            # Context Resolution: filter messages by topic relevance
            resolution = self._context_resolver.resolve(
                message=state["user_message"],
                session_messages=session_messages,
                conversation_id=state["conversation_id"],
                intent=state.get("intent", ""),
            )
            filtered_messages = self._context_resolver.filter_messages(
                session_messages, resolution
            )

            from loguru import logger
            logger.debug(
                f"Context resolution: {resolution.relation.value} | "
                f"{len(session_messages)} → {len(filtered_messages)} messages | "
                f"topic_changed={resolution.topic_changed}"
            )

            # Topic changed: discard old memory context entirely
            if resolution.topic_changed:
                memory_context = ""

            return {
                **state,
                "session_messages": filtered_messages,
                "memory_context": memory_context,
            }
        except Exception as e:
            from loguru import logger
            logger.warning(f"Memory load failed: {e}")
            return {**state, "session_messages": [], "memory_context": ""}

    async def _retrieve_context_node(self, state: AgentState) -> AgentState:
        """
        Demand-driven repository retrieval.
        Only executes when a repo is connected AND the intent warrants it.
        """
        _NO_RETRIEVAL_INTENTS = {"chat"}
        if (
            not state.get("repo_id")
            or not self._retriever
            or state.get("intent") in _NO_RETRIEVAL_INTENTS
        ):
            return {**state, "context_block": "", "code_context": [], "context_chunks_used": 0}

        try:
            results = await self._retriever.retrieve(
                query=state["rewritten_query"],  # V3: use enriched query
                repo_id=state["repo_id"],
                top_k=8,
                fetch_k=20,
            )
            context_window = self._context_builder.build(results)
            context_block = self._context_builder.format_context_block(context_window)
            return {
                **state,
                "code_context": results,
                "context_block": context_block,
                "context_chunks_used": len(results),
            }
        except Exception as e:
            from loguru import logger
            logger.warning(f"Context retrieval failed: {e}")
            return {**state, "context_block": "", "code_context": [], "context_chunks_used": 0}

    async def _plan_tools_node(self, state: AgentState) -> AgentState:
        """
        V3: Heuristic tool planning — no LLM call.
        Uses IntelligenceToolPlanner based on intent + context signals.
        """
        intel_context = state.get("intelligence_context")
        if not intel_context:
            return {**state, "tool_calls": []}

        tool_plan = self._tool_planner.plan(intel_context)

        if not tool_plan.should_use_tools:
            return {**state, "tool_calls": []}

        message = state.get("rewritten_query") or state.get("user_message", "")
        tool_calls = []
        for name in tool_plan.tools:
            args = self._extract_tool_args(name, message, state)
            tool_calls.append(ToolCall(tool_name=name, args=args, rationale=tool_plan.rationale))
        return {**state, "tool_calls": tool_calls}

    @staticmethod
    def _extract_tool_args(tool_name: str, message: str, state: AgentState) -> dict:
        """Extract tool arguments from the user message heuristically."""
        import re
        if tool_name == "read_file":
            # Match patterns like: read src/main.py, show me app/auth.py, open utils/helper.js
            match = re.search(
                r"(?:read|show|open|display|get|view|cat)\s+(?:the\s+)?(?:file\s+)?([\w./\\-]+\.\w+)",
                message, re.IGNORECASE
            )
            if match:
                return {"file_path": match.group(1)}
            # Fallback: any path-like token with extension
            match = re.search(r"([\w./\\-]+\.(?:py|ts|tsx|js|jsx|java|go|rs|cs|cpp|c|rb|php|yaml|yml|json|md|txt|sh|env))", message)
            if match:
                return {"file_path": match.group(1)}
            return {"file_path": ""}
        if tool_name == "search_code":
            return {"query": message}
        if tool_name == "list_directory":
            import re
            match = re.search(r"(?:in|inside|under|of)\s+([\w./\\-]+)", message, re.IGNORECASE)
            path = match.group(1) if match else "."
            return {"path": path, "depth": 3}
        if tool_name == "git_diff":
            match = re.search(r"([\w./\\-]+\.\w+)", message)
            return {"file_path": match.group(1)} if match else {}
        if tool_name == "run_command":
            match = re.search(r"(?:run|execute)\s+[\`'\"]{0,1}(.+?)[\`'\"]{0,1}$", message, re.IGNORECASE)
            return {"command": match.group(1)} if match else {"command": message}
        return {}

    async def _execute_tools_node(self, state: AgentState) -> AgentState:
        if not state["tool_calls"]:
            return state

        repo_path = None
        if state.get("repo_id"):
            try:
                from app.db.repositories import RepositoryRepo
                from app.database import get_db_session
                async with get_db_session() as session:
                    repo = await RepositoryRepo(session).get_by_id(state["repo_id"])
                    if repo:
                        repo_path = repo.local_path
            except Exception:
                pass

        _REPO_REQUIRED = {"write_file", "read_file", "git_diff", "run_command"}
        if not repo_path:
            filtered = [tc for tc in state["tool_calls"] if tc.tool_name not in _REPO_REQUIRED]
            if not filtered:
                return {**state, "tool_calls": []}
            state = {**state, "tool_calls": filtered}

        context = {
            "user_id": state["user_id"],
            "org_id": state["org_id"],
            "repo_id": state.get("repo_id"),
            "conversation_id": state["conversation_id"],
            "request_id": state["request_id"],
            "repo_path": repo_path,
        }
        tool_results = await self._tool_executor.execute_batch(state["tool_calls"], context)
        files_modified = list(state["files_modified"])
        for result in tool_results:
            if result.success and result.metadata:
                path = result.metadata.get("path")
                if path and path not in files_modified:
                    files_modified.append(path)

        return {
            **state,
            "tool_results": state["tool_results"] + tool_results,
            "current_step": state["current_step"] + 1,
            "tool_calls": [],
            "files_modified": files_modified,
        }

    async def _coding_agent_node(self, state: AgentState) -> AgentState:
        return await self._coding_agent.run(state)

    async def _should_continue_node(self, state: AgentState) -> AgentState:
        """Check if the draft output signals a need for more tool calls."""
        if state["current_step"] >= state["max_steps"]:
            return {**state, "tool_calls": []}

        draft = state.get("draft_output", "").lower()
        continuation_phrases = [
            "need to see", "need to check", "need to read", "need to search",
            "let me search", "let me check", "let me read",
            "i need to", "i should check", "first, let me",
        ]
        if any(p in draft for p in continuation_phrases):
            intel_context = state.get("intelligence_context")
            if intel_context:
                tool_plan = self._tool_planner.plan(intel_context)
                if tool_plan.should_use_tools:
                    message = state.get("rewritten_query") or state.get("user_message", "")
                    tool_calls = [
                        ToolCall(tool_name=name, args=self._extract_tool_args(name, message, state), rationale=tool_plan.rationale)
                        for name in tool_plan.tools
                    ]
                    return {**state, "tool_calls": tool_calls}

        return {**state, "tool_calls": []}

    async def _review_agent_node(self, state: AgentState) -> AgentState:
        return await self._review_agent.run(state)

    async def _increment_revision_node(self, state: AgentState) -> AgentState:
        return {
            **state,
            "revision_count": state["revision_count"] + 1,
            "draft_output": "",
            "current_step": 0,
            "tool_calls": [],
        }

    async def _post_review_finalise_node(self, state: AgentState) -> AgentState:
        """
        Lightweight finalise after review approval.
        Applies ResponseReviewer + ResponseFormatter to the reviewed draft,
        then saves to memory. Does NOT re-enter the review loop.
        """
        from loguru import logger
        final = state.get("draft_output", "") or state.get("final_response", "")

        intel_context = state.get("intelligence_context")
        reasoning_result = state.get("intelligence_reasoning_result")
        if final and intel_context:
            try:
                reviewed = self._intelligence.review(final, intel_context, reasoning_result)
                final = reviewed.response
            except Exception as e:
                logger.warning(f"Post-review format failed (non-blocking): {e}")

        try:
            if final:
                await self._memory.add_message(
                    user_id=state["user_id"],
                    conversation_id=state["conversation_id"],
                    role="assistant",
                    content=final,
                    agent_mode=state.get("agent_mode", "auto"),
                )
        except Exception as e:
            logger.warning(f"Post-review memory save failed: {e}")

        return {**state, "final_response": final}

    async def _finalise_node(self, state: AgentState) -> AgentState:
        """
        V3 finalise node.

        Handles three cases:
        1. Policy block / refusal → return block_response directly
        2. Clarification needed → return clarification_question directly
        3. Normal response → run ResponseReviewer + ResponseFormatter, save memory
        """
        from loguru import logger

        # ── Case 1: Policy block ──────────────────────────────────────────────
        if state.get("refused"):
            final = state.get("draft_output") or "I cannot help with that request."
            return {**state, "final_response": final}

        # ── Case 2: Clarification needed ──────────────────────────────────────
        if state.get("should_clarify") and state.get("clarification_question"):
            final = state["clarification_question"]
            try:
                await self._memory.add_message(
                    user_id=state["user_id"],
                    conversation_id=state["conversation_id"],
                    role="user",
                    content=state["user_message"],
                    agent_mode=state.get("agent_mode", "auto"),
                )
                await self._memory.add_message(
                    user_id=state["user_id"],
                    conversation_id=state["conversation_id"],
                    role="assistant",
                    content=final,
                    agent_mode=state.get("agent_mode", "auto"),
                )
            except Exception as e:
                logger.warning(f"Memory save failed (clarification): {e}")
            return {**state, "final_response": final}

        # ── Case 3: Normal response ───────────────────────────────────────────
        final = state.get("draft_output", "")
        if not final and state.get("error"):
            final = f"I encountered an error: {state['error']}"

        # Run ResponseReviewer + ResponseFormatter via intelligence engine
        intel_context = state.get("intelligence_context")
        reasoning_result = state.get("intelligence_reasoning_result")
        if final and intel_context:
            try:
                reviewed = self._intelligence.review(final, intel_context, reasoning_result)
                final = reviewed.response
                if reviewed.review_issues:
                    logger.debug(f"Response reviewer flagged: {reviewed.review_issues}")
            except Exception as e:
                logger.warning(f"Response review failed (non-blocking): {e}")

        # Save to memory
        try:
            await self._memory.add_message(
                user_id=state["user_id"],
                conversation_id=state["conversation_id"],
                role="user",
                content=state["user_message"],
                agent_mode=state.get("agent_mode", "auto"),
            )
            if final:
                await self._memory.add_message(
                    user_id=state["user_id"],
                    conversation_id=state["conversation_id"],
                    role="assistant",
                    content=final,
                    agent_mode=state.get("agent_mode", "auto"),
                )
            await self._memory.consolidate_async(
                user_id=state["user_id"],
                org_id=state["org_id"],
                conversation_id=state["conversation_id"],
                repo_id=state.get("repo_id"),
            )
        except Exception as e:
            logger.warning(f"Memory save failed: {e}")

        return {**state, "final_response": final}

    # ── Public interface ──────────────────────────────────────────────────────

    async def run(self, state: AgentState) -> AgentState:
        return await self._graph.ainvoke(state)

    async def stream(self, state: AgentState):
        """
        Streaming pipeline.

        Phase 1: Full intelligence pipeline (no streaming) — produces system_prompt,
                 rewritten_query, clarification decision, tool plan.
        Phase 2: Tool execution (if needed).
        Phase 3: Stream LLM response token-by-token.
        Phase 4: Post-LLM review + format via intelligence engine.
        Phase 5: Save to memory.
        """
        from loguru import logger

        # Pre-save user message
        try:
            await self._memory.add_message(
                user_id=state["user_id"],
                conversation_id=state["conversation_id"],
                role="user",
                content=state["user_message"],
                agent_mode=state.get("agent_mode", "auto"),
            )
        except Exception as e:
            logger.warning(f"Pre-save user message failed: {e}")

        # Phase 1: Intelligence pipeline
        try:
            state = await self._intelligence_prepare_node(state)

            # Short-circuit: policy block
            if state.get("refused"):
                block_response = state.get("draft_output", "I cannot help with that request.")
                yield block_response
                try:
                    await self._memory.add_message(
                        user_id=state["user_id"],
                        conversation_id=state["conversation_id"],
                        role="assistant",
                        content=block_response,
                        agent_mode=state.get("agent_mode", "auto"),
                    )
                except Exception:
                    pass
                return

            # Short-circuit: clarification needed
            if state.get("should_clarify") and state.get("clarification_question"):
                clarification = state["clarification_question"]
                yield clarification
                try:
                    await self._memory.add_message(
                        user_id=state["user_id"],
                        conversation_id=state["conversation_id"],
                        role="assistant",
                        content=clarification,
                        agent_mode=state.get("agent_mode", "auto"),
                    )
                except Exception:
                    pass
                return

            state = await self._load_memory_node(state)
            state = await self._retrieve_context_node(state)
            state = await self._plan_tools_node(state)

            # Tool execution loop
            for _ in range(state["max_steps"]):
                if not state.get("tool_calls"):
                    break
                state = await self._execute_tools_node(state)
                state = await self._plan_tools_node(state)

        except Exception as e:
            logger.error(f"Stream pipeline setup failed: {e}")
            yield f"I encountered an error setting up the response: {str(e)}"
            return

        # Phase 2: Stream LLM response
        from app.prompts.coding import build_user_prompt

        # Build repo file tree for context (accurate structure, no hallucination)
        repo_file_tree = ""
        if state.get("repo_id") and state.get("tool_results") is not None:
            try:
                from app.db.repositories import RepositoryRepo
                from app.database import get_db_session
                from app.agents.tools.file_tool import FileTool
                from app.agents.tools.base import ToolContext
                async with get_db_session() as session:
                    repo = await RepositoryRepo(session).get_by_id(state["repo_id"])
                    if repo and repo.local_path:
                        ft = FileTool()
                        tc = ToolContext(
                            user_id=state["user_id"], org_id=state["org_id"],
                            repo_id=state["repo_id"], conversation_id=state["conversation_id"],
                            request_id=state["request_id"], repo_path=repo.local_path,
                        )
                        result = await ft._execute(tc, operation="list_directory", path=".", depth=4)
                        if result.success:
                            repo_file_tree = str(result.output)
            except Exception:
                pass

        system_prompt = state.get("system_prompt") or _FALLBACK_SYSTEM_PROMPT
        user_prompt = build_user_prompt(
            message=state["rewritten_query"],
            raw_message=state["user_message"],
            context_block=state["context_block"],
            session_messages=state["session_messages"],
            tool_results=state["tool_results"],
            review_feedback=state["review_feedback"],
            intent=state["intent"],
            agent_mode=state.get("agent_mode", "auto"),
            repo_file_tree=repo_file_tree,
        )

        # Debug trace
        from app.config import get_settings as _gs
        _cfg = _gs()
        _sep = "=" * 80
        _debug = (
            f"\n{_sep}\n[FINAL PROMPT → LLM]\n"
            f"  provider : {_cfg.llm_provider}\n"
            f"  model    : {self._coding_agent._get_model(state.get('agent_mode', 'auto'))}\n"
            f"  intent   : {state.get('intent')}  |  mode: {state.get('agent_mode', 'auto')}\n"
            f"  rewritten: {state.get('rewritten_query', '')[:80]}\n"
            f"  clarify  : {state.get('should_clarify')}  |  plan: {state.get('execution_plan_summary', '')[:60]}\n"
            f"\n--- SYSTEM PROMPT ({len(system_prompt)} chars) ---\n{system_prompt}\n"
            f"\n--- USER PROMPT ({len(user_prompt)} chars) ---\n{user_prompt}\n"
            f"{_sep}"
        )
        import sys
        print(_debug, flush=True)

        full_response = ""
        try:
            async for chunk in self._coding_agent._ollama.chat_stream(
                prompt=user_prompt,
                system_prompt=system_prompt,
                model=self._coding_agent._get_model(state.get("agent_mode", "auto")),
                temperature=self._coding_agent._get_temperature(
                    state["intent"], state.get("agent_mode", "auto")
                ),
            ):
                full_response += chunk
                yield chunk
        except Exception as e:
            logger.error(f"Stream LLM call failed: {e}")
            raise

        # Phase 3: Post-LLM review + format
        intel_context = state.get("intelligence_context")
        reasoning_result = state.get("intelligence_reasoning_result")
        if full_response and intel_context:
            try:
                reviewed = self._intelligence.review(full_response, intel_context, reasoning_result)
                full_response = reviewed.response
                if reviewed.review_issues:
                    logger.debug(f"Stream response reviewer flagged: {reviewed.review_issues}")
            except Exception as e:
                logger.warning(f"Stream response review failed (non-blocking): {e}")

        # Phase 4: Save to memory
        try:
            if full_response:
                await self._memory.add_message(
                    user_id=state["user_id"],
                    conversation_id=state["conversation_id"],
                    role="assistant",
                    content=full_response,
                    agent_mode=state.get("agent_mode", "auto"),
                )
        except Exception as e:
            logger.warning(f"Stream memory save failed: {e}")


# ── Singleton factory ─────────────────────────────────────────────────────────

_orchestrator: AgentOrchestrator | None = None


def get_orchestrator(vector_store: Optional[VectorStore] = None) -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        retriever = CodeRetriever(vector_store) if vector_store else None
        _orchestrator = AgentOrchestrator(
            vector_store=vector_store,
            retriever=retriever,
        )
    return _orchestrator


def get_orchestrator_dep() -> AgentOrchestrator:
    return get_orchestrator()
