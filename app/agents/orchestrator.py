"""
LangGraph orchestrator — V3 Conversation Intelligence Engine.

Graph flow:
  START
    ↓
  intelligence_prepare  ConversationIntelligenceEngine.prepare()
                        (intent → complexity → conversation → policy →
                         persona → strategy → context → tool_plan → prompt)
    ↓
  load_memory           load session + long-term memory
    ↓
  retrieve_context      fetch relevant code from ChromaDB
    ↓
  plan_tools            LLM-based tool planning (fallback / refinement)
    ↓
  ┌─────────────────────────────────────────────────┐
  │ Tool Loop (max 5 iterations)                    │
  │   execute_tools → coding_agent → should_continue│
  └─────────────────────────────────────────────────┘
    ↓
  self_correct          detect contradictions, inject corrections
    ↓
  should_review?
    ├── yes → review_agent → check_revision
    │           ├── needs_revision → increment_revision → plan_tools
    │           └── approved → finalise
    └── no  → finalise
    ↓
  END
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
from app.agents.tool_planner import get_tool_planner
from app.memory import MemoryManager, get_memory_manager
from app.ollama_client import get_ollama_client
from app.prompts.composer import PromptComposer, get_composer
from app.retrieval.context_builder import ContextBuilder
from app.retrieval.retriever import CodeRetriever
from app.vector_store.base import VectorStore
from app.intelligence.context.resolver import ContextResolutionEngine, get_context_resolution_engine
from app.intelligence.engine import ConversationIntelligenceEngine, get_engine


# ── Intent detection ──────────────────────────────────────────────────────────

def _detect_intent(message: str, agent_mode: str = "auto") -> str:
    lower = message.lower()

    if agent_mode == "business":
        return "chat"

    if agent_mode == "auto":
        code_kw = ["write code", "implement", "build a", "create a function",
                   "debug", "fix this code", "refactor", "write a script"]
        return "code" if any(k in lower for k in code_kw) else "chat"

    # Code mode — if the message is clearly non-code topic, treat as chat
    # regardless of any incidentally matched keywords in pasted content
    from app.prompts.enhancer import _is_non_code_topic
    if _is_non_code_topic(message):
        return "chat"

    # Code mode — full detection
    if any(k in lower for k in ["review", "audit", "critique", "analyze code"]):
        return "review"
    if any(k in lower for k in ["write test", "add test", "unit test", "test case"]):
        return "test"
    if any(k in lower for k in ["fix", "bug", "error", "broken", "failing", "debug", "crash"]):
        return "fix"
    if any(k in lower for k in ["explain", "what does", "how does", "what is", "describe"]):
        return "explain"
    if any(k in lower for k in ["find", "where", "search", "locate", "which file"]) and "how" not in lower:
        return "search"

    gen_kw = ["create", "add", "implement", "write", "build", "generate", "refactor", "update"]
    if len(lower.strip()) < 60 and not any(k in lower for k in gen_kw):
        return "chat"
    return "code"


# ── Context detection helpers ─────────────────────────────────────────────────

_LANG_MAP = {
    "typescript": "typescript", ".tsx": "typescript", ".ts ": "typescript",
    "javascript": "javascript", " js ": "javascript",
    "python": "python", ".py": "python",
    "c#": "csharp", "csharp": "csharp",
    "java ": "java", "kotlin": "kotlin",
    " go ": "go", "golang": "go",
    "rust": "rust", "php": "php", "swift": "swift", "dart": "dart",
}

_FRAMEWORK_MAP = {
    "react": "react", "next.js": "nextjs", "nextjs": "nextjs",
    "vue": "vue", "nuxt": "nuxtjs", "angular": "angular", "svelte": "svelte",
    "react native": "react_native", "flutter": "flutter",
    "fastapi": "fastapi", "django": "django", "flask": "flask",
    "express": "express", "nestjs": "nestjs", "nest.js": "nestjs",
    "asp.net": "aspnet", "spring boot": "spring_boot", "laravel": "laravel",
}

_DB_MAP = {
    "postgresql": "postgresql", "postgres": "postgresql",
    "mysql": "mysql", "sql server": "mssql", "mssql": "mssql",
    "mongodb": "mongodb", "mongo": "mongodb",
    "redis": "redis", "elasticsearch": "elasticsearch",
    "dynamodb": "dynamodb", "firestore": "firebase_db", "firebase": "firebase_db",
}

_CLOUD_MAP = {
    "aws": "aws", "amazon web": "aws",
    "azure": "azure", "google cloud": "gcp", "gcp": "gcp",
    "docker": "docker", "kubernetes": "kubernetes", "k8s": "kubernetes",
    "terraform": "terraform", "github actions": "github_actions",
}

_BUSINESS_MAP = {
    "hotel": "hotel", "pms": "hotel", "reservation": "hotel",
    "check-in": "hotel", "revpar": "hotel",
    "erp": "erp", "procurement": "erp", "purchase order": "erp",
    "pos": "pos", "point of sale": "pos", "cashier": "pos",
    "inventory": "inventory", "warehouse": "inventory", "stock": "inventory",
    "payroll": "hrms", "hrms": "hrms",
    "crm": "crm", "lead": "crm",
    "finance": "finance", "accounting": "finance", "invoice": "finance",
}

_ARCH_MAP = {
    "clean architecture": "clean_architecture",
    "domain driven": "ddd", "ddd": "ddd",
    "microservice": "microservices",
    "event driven": "event_driven", "event sourcing": "event_driven", "cqrs": "event_driven",
}

_TEST_MAP = {
    "unit test": "unit_testing", "integration test": "integration_testing",
    "e2e": "e2e_testing", "playwright": "e2e_testing", "cypress": "e2e_testing",
    "pytest": "pytest", "jest": "unit_testing", "vitest": "unit_testing",
}

_SECURITY_KW = ["security", "owasp", "authentication", "auth", "jwt", "oauth",
                "injection", "xss", "csrf", "vulnerability", "api key"]

_AI_KW = ["langgraph", "langchain", "rag", "retrieval", "embedding", "vector",
          "multi-agent", "multi agent", "ollama", "llm", "agent"]

_FACTUAL_KW = ["when was", "what year", "released", "published", "version",
               "history", "invented", "created", "founded", "launched",
               "book", "movie", "show", "season", "episode"]


def _first_match(lower: str, mapping: dict[str, str]) -> str:
    for kw, val in mapping.items():
        if kw in lower:
            return val
    return ""


class AgentOrchestrator:
    """
    V2 LangGraph orchestrator with dynamic prompt composition.
    """

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        coding_agent: Optional[CodingAgent] = None,
        review_agent: Optional[ReviewAgent] = None,
        retriever: Optional[CodeRetriever] = None,
        context_builder: Optional[ContextBuilder] = None,
        memory_manager: Optional[MemoryManager] = None,
        composer: Optional[PromptComposer] = None,
        intelligence_engine: Optional[ConversationIntelligenceEngine] = None,
        context_resolver: Optional[ContextResolutionEngine] = None,
    ) -> None:
        self._vs = vector_store
        self._coding_agent = coding_agent or CodingAgent()
        self._review_agent = review_agent or ReviewAgent()
        self._retriever = retriever
        self._context_builder = context_builder or ContextBuilder()
        self._memory = memory_manager or get_memory_manager()
        self._tool_planner = get_tool_planner()
        self._tool_executor = get_tool_executor()
        self._composer = composer or get_composer()
        self._intelligence = intelligence_engine or get_engine()
        self._context_resolver = context_resolver or get_context_resolution_engine()
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(AgentState)

        graph.add_node("intelligence_prepare", self._intelligence_prepare_node)
        graph.add_node("route_intent",      self._route_intent_node)
        graph.add_node("detect_context",    self._detect_context_node)
        graph.add_node("compose_prompt",    self._compose_prompt_node)
        graph.add_node("load_memory",       self._load_memory_node)
        graph.add_node("retrieve_context",  self._retrieve_context_node)
        graph.add_node("plan_tools",        self._plan_tools_node)
        graph.add_node("execute_tools",     self._execute_tools_node)
        graph.add_node("coding_agent",      self._coding_agent_node)
        graph.add_node("should_continue",   self._should_continue_node)
        graph.add_node("self_correct",      self._self_correct_node)
        graph.add_node("review_agent",      self._review_agent_node)
        graph.add_node("increment_revision",self._increment_revision_node)
        graph.add_node("finalise",          self._finalise_node)

        graph.add_edge(START,               "intelligence_prepare")
        # V3 success → skip legacy nodes; V3 failure → run legacy fallback pipeline
        graph.add_conditional_edges(
            "intelligence_prepare",
            lambda s: "load_memory" if s.get("intelligence_context") else "route_intent",
            {"load_memory": "load_memory", "route_intent": "route_intent"},
        )
        graph.add_edge("route_intent",      "detect_context")
        graph.add_edge("detect_context",    "compose_prompt")
        graph.add_edge("compose_prompt",    "load_memory")
        graph.add_edge("load_memory",       "retrieve_context")
        graph.add_edge("retrieve_context",  "plan_tools")

        graph.add_conditional_edges(
            "plan_tools",
            lambda s: "tools" if s["tool_calls"] else "agent",
            {"tools": "execute_tools", "agent": "coding_agent"},
        )

        graph.add_edge("execute_tools",     "coding_agent")
        graph.add_edge("coding_agent",      "should_continue")

        def _continue_router(s: AgentState) -> str:
            if s["current_step"] < s["max_steps"] and s.get("tool_calls"):
                return "plan_tools"
            return "self_correct"

        graph.add_conditional_edges(
            "should_continue",
            _continue_router,
            {"plan_tools": "plan_tools", "self_correct": "self_correct"},
        )

        def _after_self_correct(s: AgentState) -> str:
            if should_review_decision(s) == "review":
                return "review"
            return "finalise"

        graph.add_conditional_edges(
            "self_correct",
            _after_self_correct,
            {"review": "review_agent", "finalise": "finalise"},
        )

        graph.add_conditional_edges(
            "review_agent",
            check_revision_decision,
            {"revise": "increment_revision", "finalise": "finalise"},
        )

        graph.add_edge("increment_revision", "plan_tools")
        graph.add_edge("finalise",           END)

        return graph.compile()

    # ── Nodes ─────────────────────────────────────────────────────────────────

    async def _intelligence_prepare_node(self, state: AgentState) -> AgentState:
        """
        V3: Run the full ConversationIntelligenceEngine pre-LLM pipeline.
        Replaces route_intent + detect_context + compose_prompt in one call.
        Stores intelligence_trace in state for observability.
        """
        from loguru import logger
        try:
            result = await self._intelligence.prepare(state)

            if result.is_blocked:
                return {
                    **state,
                    "intent": "chat",
                    "system_prompt": "",
                    "draft_output": result.block_response or "I cannot help with that request.",
                    "refused": True,
                    "intelligence_trace": result.trace,
                }

            # Map intelligence intent back to legacy intent string for downstream nodes
            primary_intent = result.context.intent_analysis.primary.intent.value
            legacy_intent_map = {
                "coding": "code", "debugging": "fix", "testing": "test",
                "refactoring": "code", "repository_question": "search",
                "documentation": "explain", "learning": "explain",
                "deep_teaching": "explain", "general_chat": "chat",
            }
            legacy_intent = legacy_intent_map.get(primary_intent, "chat")

            return {
                **state,
                "intent": legacy_intent,
                "system_prompt": result.system_prompt,
                "intelligence_context": result.context,
                "intelligence_trace": result.trace,
                "intelligence_reasoning_result": result.reasoning_result,
                # Populate detected_* fields for backward compat with existing nodes
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
            logger.error(f"Intelligence engine prepare failed: {e}")
            # Graceful degradation: fall back to legacy intent detection
            intent = _detect_intent(state["user_message"], state.get("agent_mode", "auto"))
            system_prompt = self._composer.compose(state)
            return {**state, "intent": intent, "system_prompt": system_prompt}

    async def _route_intent_node(self, state: AgentState) -> AgentState:
        intent = _detect_intent(state["user_message"], state.get("agent_mode", "auto"))
        # If code mode and non-code topic, mark as refused so finalise short-circuits
        from app.prompts.enhancer import _is_non_code_topic, _is_adult_content
        agent_mode = state.get("agent_mode", "auto")
        if agent_mode == "code" and _is_non_code_topic(state["user_message"]):
            return {**state, "intent": intent, "refused": True}
        return {**state, "intent": intent}

    async def _detect_context_node(self, state: AgentState) -> AgentState:
        """
        Detect language, framework, database, cloud, business domain from message.
        Populates detected_* fields used by PromptComposer.
        """
        lower = state["user_message"].lower()
        return {
            **state,
            "detected_language":        _first_match(lower, _LANG_MAP),
            "detected_framework":       _first_match(lower, _FRAMEWORK_MAP),
            "detected_database":        _first_match(lower, _DB_MAP),
            "detected_cloud":           _first_match(lower, _CLOUD_MAP),
            "detected_business_domain": _first_match(lower, _BUSINESS_MAP),
            "detected_architecture":    _first_match(lower, _ARCH_MAP),
            "detected_testing":         _first_match(lower, _TEST_MAP),
            "detected_security":        any(k in lower for k in _SECURITY_KW),
            "detected_ai_domain":       any(k in lower for k in _AI_KW),
        }

    async def _compose_prompt_node(self, state: AgentState) -> AgentState:
        """
        Build the dynamic system prompt using PromptComposer.
        Stores result in state["system_prompt"].
        """
        system_prompt = self._composer.compose(state)
        return {**state, "system_prompt": system_prompt}

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

            # ── Context Resolution: filter messages by topic relevance ────────
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

            # If topic changed, don't include old memory context either
            if resolution.topic_changed:
                memory_context = ""

            return {
                **state,
                "session_messages": filtered_messages,
                "memory_context": memory_context,
            }
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to load memory: {e}")
            return {**state, "session_messages": [], "memory_context": ""}

    async def _retrieve_context_node(self, state: AgentState) -> AgentState:
        if not state.get("repo_id") or not self._retriever:
            return {**state, "context_block": "", "code_context": [], "context_chunks_used": 0}
        results = await self._retriever.retrieve(
            query=state["user_message"], repo_id=state["repo_id"], top_k=8, fetch_k=20,
        )
        context_window = self._context_builder.build(results)
        context_block = self._context_builder.format_context_block(context_window)
        return {**state, "code_context": results, "context_block": context_block,
                "context_chunks_used": len(results)}

    async def _plan_tools_node(self, state: AgentState) -> AgentState:
        tool_calls = await self._tool_planner.plan(state)
        return {**state, "tool_calls": tool_calls}

    async def _execute_tools_node(self, state: AgentState) -> AgentState:
        if not state["tool_calls"]:
            return state
        from app.db.repositories import RepositoryRepo
        from app.database import get_db_session
        repo_path = None
        if state.get("repo_id"):
            try:
                async with get_db_session() as session:
                    repo = await RepositoryRepo(session).get_by_id(state["repo_id"])
                    if repo:
                        repo_path = repo.local_path
            except Exception:
                pass

        # Drop any file/git/command tools if there is no repo_path.
        # These tools will always fail without it — no point executing them.
        _REPO_REQUIRED_TOOLS = {"write_file", "read_file", "git_diff", "run_command"}
        if not repo_path:
            filtered = [tc for tc in state["tool_calls"] if tc.tool_name not in _REPO_REQUIRED_TOOLS]
            if len(filtered) < len(state["tool_calls"]):
                from loguru import logger
                dropped = [tc.tool_name for tc in state["tool_calls"] if tc.tool_name in _REPO_REQUIRED_TOOLS]
                logger.warning(f"Dropped tool calls (no repo connected): {dropped}")
            if not filtered:
                return {**state, "tool_calls": []}
            state = {**state, "tool_calls": filtered}

        context = {
            "user_id": state["user_id"], "org_id": state["org_id"],
            "repo_id": state.get("repo_id"), "conversation_id": state["conversation_id"],
            "request_id": state["request_id"], "repo_path": repo_path,
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
        if state["current_step"] >= state["max_steps"]:
            return {**state, "tool_calls": []}
        draft = state.get("draft_output", "").lower()
        continuation_phrases = [
            "need to see", "need to check", "need to read", "need to search",
            "let me search", "let me check", "let me read",
            "i need to", "i should check", "first, let me",
        ]
        if any(p in draft for p in continuation_phrases):
            tool_calls = await self._tool_planner.plan(state)
            if tool_calls:
                return {**state, "tool_calls": tool_calls}
        return {**state, "tool_calls": []}

    async def _self_correct_node(self, state: AgentState) -> AgentState:
        """
        Truthfulness & self-correction node.

        Scans draft_output for:
        1. Contradictions with conversation history
        2. Fabricated entities (non-existent libraries, APIs, books)
        3. Chronological impossibilities

        Injects corrections into state["self_corrections"] and
        state["truthfulness_warnings"] so the next revision pass
        (or the final response) includes explicit corrections.

        Confidence scoring:
        - 1.0: no issues detected
        - 0.7: minor uncertainty detected
        - 0.4: potential contradiction detected
        - 0.1: likely fabrication detected
        """
        draft = state.get("draft_output", "")
        warnings: list[str] = list(state.get("truthfulness_warnings", []))
        corrections: list[str] = list(state.get("self_corrections", []))
        confidence = state.get("confidence_score", 1.0)
        uncertainty_level = "none"

        if not draft:
            return state

        draft_lower = draft.lower()

        # ── Check 1: Detect overconfident fabrication signals ─────────────────
        fabrication_signals = [
            "definitely released", "was published in", "was released in",
            "the book states", "according to the official", "as documented in",
        ]
        for signal in fabrication_signals:
            if signal in draft_lower:
                warnings.append(
                    f"Response contains potentially unverified factual claim: '{signal}'. "
                    "Verify before presenting as fact."
                )
                confidence = min(confidence, 0.7)
                uncertainty_level = "medium"

        # ── Check 2: Detect contradiction with session history ────────────────
        session = state.get("session_messages", [])
        if session and len(session) >= 2:
            # Look for direct contradictions in last assistant message
            last_assistant = next(
                (m["content"] for m in reversed(session) if m.get("role") == "assistant"),
                ""
            )
            if last_assistant:
                # Simple heuristic: if draft says "X is Y" but history said "X is Z"
                # This is a lightweight check — full NLI would require a classifier
                contradiction_pairs = [
                    ("not released", "was released"),
                    ("does not exist", "exists"),
                    ("deprecated", "is current"),
                    ("was removed", "is available"),
                ]
                for neg, pos in contradiction_pairs:
                    if neg in draft_lower and pos in last_assistant.lower():
                        corrections.append(
                            f"Note: This response may contradict a previous statement. "
                            f"Previous response mentioned '{pos}' but current draft says '{neg}'. "
                            f"Please verify which is correct."
                        )
                        confidence = min(confidence, 0.4)
                        uncertainty_level = "high"

        # ── Check 3: Detect unreleased/non-existent entity claims ─────────────
        # Known unreleased items as of training data
        known_unreleased = [
            "winds of winter",
            "a dream of spring",
            "half-life 3",
        ]
        for item in known_unreleased:
            if item in draft_lower and any(
                word in draft_lower for word in ["released", "published", "available", "out now"]
            ):
                corrections.append(
                    f"CORRECTION NEEDED: '{item}' has not been officially released. "
                    f"Do not state it as released."
                )
                confidence = min(confidence, 0.1)
                uncertainty_level = "high"

        # ── Determine final uncertainty level ─────────────────────────────────
        if confidence < 0.3:
            uncertainty_level = "high"
        elif confidence < 0.6:
            uncertainty_level = "medium"
        elif confidence < 0.85:
            uncertainty_level = "low"

        return {
            **state,
            "truthfulness_warnings": warnings,
            "self_corrections": corrections,
            "confidence_score": confidence,
            "uncertainty_level": uncertainty_level,
        }

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

    async def _finalise_node(self, state: AgentState) -> AgentState:
        final = state.get("draft_output", "")
        if not final and state.get("error"):
            final = f"I encountered an error: {state['error']}"

        # Only prepend corrections if they are genuine and response is non-empty
        corrections = state.get("self_corrections", [])
        if corrections and final:
            # Filter out corrections that reference empty/missing prior context
            real_corrections = [
                c for c in corrections
                if not c.startswith("Note: This response may contradict")
                or len(state.get("session_messages", [])) >= 2
            ]
            if real_corrections:
                correction_block = "\n".join(f"> {c}" for c in real_corrections)
                final = f"{correction_block}\n\n{final}"

        try:
            await self._memory.add_message(
                user_id=state["user_id"], conversation_id=state["conversation_id"],
                role="user", content=state["user_message"],
                agent_mode=state.get("agent_mode", "auto"),
            )
            if final:
                await self._memory.add_message(
                    user_id=state["user_id"], conversation_id=state["conversation_id"],
                    role="assistant", content=final,
                    agent_mode=state.get("agent_mode", "auto"),
                )
            await self._memory.consolidate_async(
                user_id=state["user_id"], org_id=state["org_id"],
                conversation_id=state["conversation_id"], repo_id=state.get("repo_id"),
            )
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to save memory: {e}")

        return {**state, "final_response": final}

    # ── Public interface ──────────────────────────────────────────────────────

    async def run(self, state: AgentState) -> AgentState:
        return await self._graph.ainvoke(state)

    async def stream(self, state: AgentState):
        """
        Streaming: runs detect_context + compose_prompt + memory + retrieval
        pipeline first, then streams the LLM response token-by-token.
        """
        from loguru import logger

        # Phase 0: pre-save user message
        try:
            await self._memory.add_message(
                user_id=state["user_id"], conversation_id=state["conversation_id"],
                role="user", content=state["user_message"],
                agent_mode=state.get("agent_mode", "auto"),
            )
        except Exception as e:
            logger.warning(f"Failed to pre-save user message: {e}")

        # Phase 1: Intelligence pipeline (no streaming)
        try:
            # V3: Run the full intelligence engine
            state = await self._intelligence_prepare_node(state)

            # Short-circuit on policy block
            if state.get("refused"):
                block_response = state.get("draft_output", "I cannot help with that request.")
                yield block_response
                try:
                    await self._memory.add_message(
                        user_id=state["user_id"], conversation_id=state["conversation_id"],
                        role="assistant", content=block_response,
                        agent_mode=state.get("agent_mode", "auto"),
                    )
                except Exception:
                    pass
                return

            state = await self._load_memory_node(state)
            state = await self._retrieve_context_node(state)
            state = await self._plan_tools_node(state)

            for _ in range(state["max_steps"]):
                if not state.get("tool_calls"):
                    break
                state = await self._execute_tools_node(state)
                state = await self._plan_tools_node(state)

            state = await self._self_correct_node(state)

        except Exception as e:
            logger.error(f"Stream pipeline failed: {e}")
            yield f"I encountered an error setting up the response: {str(e)}"
            return

        # Phase 2: stream LLM response
        from app.prompts.coding import build_user_prompt

        system_prompt = state.get("system_prompt") or ""
        user_prompt = build_user_prompt(
            message=state["user_message"],
            context_block=state["context_block"],
            session_messages=state["session_messages"],
            tool_results=state["tool_results"],
            review_feedback=state["review_feedback"],
            intent=state["intent"],
            agent_mode=state.get("agent_mode", "auto"),
            truthfulness_warnings=state.get("truthfulness_warnings", []),
            self_corrections=state.get("self_corrections", []),
        )

        # ── DEBUG: print final prompts sent to LLM ────────────────────────────
        from app.config import get_settings as _gs
        _cfg = _gs()
        _sep = "=" * 80
        _debug_output = (
            f"\n{_sep}\n"
            f"[FINAL PROMPT → LLM]\n"
            f"  provider : {_cfg.llm_provider}\n"
            f"  model    : {self._coding_agent._get_model(state.get('agent_mode', 'auto'))}\n"
            f"  intent   : {state.get('intent')}  |  mode: {state.get('agent_mode', 'auto')}\n"
            f"  temp     : {self._coding_agent._get_temperature(state['intent'], state.get('agent_mode', 'auto'))}\n"
            f"\n--- SYSTEM PROMPT ({len(system_prompt)} chars) ---\n"
            f"{system_prompt}\n"
            f"\n--- USER PROMPT ({len(user_prompt)} chars) ---\n"
            f"{user_prompt}\n"
            f"{_sep}"
        )
        print(_debug_output, flush=True)
        logger.debug(_debug_output)

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
            yield f"\n\nError generating response: {str(e)}"

        # Phase 3: Post-LLM review + format via intelligence engine
        intel_context = state.get("intelligence_context")
        reasoning_result = state.get("intelligence_reasoning_result")
        if full_response and intel_context:
            try:
                reviewed = self._intelligence.review(
                    full_response, intel_context, reasoning_result
                )
                full_response = reviewed.response
                if reviewed.review_issues:
                    logger.debug(
                        f"Response reviewer flagged issues: {reviewed.review_issues}",
                        extra={"request_id": state.get("request_id", "")},
                    )
            except Exception as e:
                logger.warning(f"Response review failed (non-blocking): {e}")

        # Phase 4: save assistant response
        try:
            if full_response:
                await self._memory.add_message(
                    user_id=state["user_id"], conversation_id=state["conversation_id"],
                    role="assistant", content=full_response,
                    agent_mode=state.get("agent_mode", "auto"),
                )
        except Exception as e:
            logger.warning(f"Failed to save stream memory: {e}")


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
