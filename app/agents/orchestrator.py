"""
LangGraph orchestrator — the StateGraph that connects all nodes.

V1 graph is intentionally simple:
  START → retrieve_context → route → coding_agent → END

No review loop in V1 (adds 10-20s latency for marginal quality gain).
ReviewAgent added in V2 with explicit user trigger.

Adding a node in V2/V3 = add a function + add_node() + add_conditional_edges().
The graph structure makes the agent flow explicit and testable.
"""

from __future__ import annotations

from typing import Literal, Optional

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
from app.retrieval.context_builder import ContextBuilder
from app.retrieval.retriever import CodeRetriever
from app.vector_store.base import VectorStore


def _detect_intent(message: str) -> str:
    """
    Simple rule-based intent detection.
    In V2: replace with a fast LLM classification call.

    Returns one of: code | review | explain | search | chat | fix | test
    """
    lower = message.lower()

    review_keywords = ["review", "check", "audit", "critique", "quality", "smell"]
    explain_keywords = ["explain", "what does", "how does", "what is", "describe", "walk me through"]
    search_keywords = ["find", "where", "search", "locate", "show me", "which file"]
    fix_keywords = ["fix", "bug", "error", "broken", "failing", "issue", "problem", "debug"]
    test_keywords = ["test", "write test", "add test", "test case", "unit test"]

    if any(k in lower for k in review_keywords):
        return "review"
    if any(k in lower for k in test_keywords):
        return "test"
    if any(k in lower for k in fix_keywords):
        return "fix"
    if any(k in lower for k in explain_keywords):
        return "explain"
    if any(k in lower for k in search_keywords) and "how" not in lower:
        return "search"
    # Default to code for generation tasks
    return "code"


class AgentOrchestrator:
    """
    Builds and runs the LangGraph StateGraph.

    The graph is compiled once and reused for all requests.
    Each request gets a fresh AgentState.
    """

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        coding_agent: Optional[CodingAgent] = None,
        review_agent: Optional[ReviewAgent] = None,
        retriever: Optional[CodeRetriever] = None,
        context_builder: Optional[ContextBuilder] = None,
        memory_manager: Optional[MemoryManager] = None,
    ) -> None:
        self._vs = vector_store
        self._coding_agent = coding_agent or CodingAgent()
        self._review_agent = review_agent or ReviewAgent()
        self._retriever = retriever
        self._context_builder = context_builder or ContextBuilder()
        self._memory = memory_manager or get_memory_manager()
        self._tool_planner = get_tool_planner()
        self._tool_executor = get_tool_executor()
        self._graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """
        Define the V1.2 agent graph with tool-use loop + review loop:

          START
            ↓
          route_intent      (detect what the user wants)
            ↓
          load_memory       (load conversation history)
            ↓
          retrieve_context  (fetch relevant code from ChromaDB)
            ↓
          plan_tools        (decide which tools to call)
            ↓
          ┌─────────────────────────┐
          │ Tool Loop (max 5 steps) │
          │  execute_tools          │
          │     ↓                   │
          │  coding_agent           │
          │     ↓                   │
          │  should_continue?       │
          └─────────────────────────┘
            ↓
          should_review? (conditional: fix/test/review intents)
            ├── yes → review_agent → check_revision
            │                          ├── needs_revision → increment_revision → plan_tools (loop)
            │                          └── approved → finalise
            └── no  → finalise
            ↓
          END
        """
        graph = StateGraph(AgentState)

        # Nodes
        graph.add_node("route_intent", self._route_intent_node)
        graph.add_node("load_memory", self._load_memory_node)
        graph.add_node("retrieve_context", self._retrieve_context_node)
        graph.add_node("plan_tools", self._plan_tools_node)
        graph.add_node("execute_tools", self._execute_tools_node)
        graph.add_node("coding_agent", self._coding_agent_node)
        graph.add_node("should_continue", self._should_continue_node)
        graph.add_node("review_agent", self._review_agent_node)
        graph.add_node("increment_revision", self._increment_revision_node)
        graph.add_node("finalise", self._finalise_node)

        # Edges
        graph.add_edge(START, "route_intent")
        graph.add_edge("route_intent", "load_memory")
        graph.add_edge("load_memory", "retrieve_context")
        graph.add_edge("retrieve_context", "plan_tools")
        
        # Conditional: if tools planned, execute them; otherwise go straight to agent
        graph.add_conditional_edges(
            "plan_tools",
            lambda s: "tools" if s["tool_calls"] else "agent",
            {"tools": "execute_tools", "agent": "coding_agent"},
        )
        
        graph.add_edge("execute_tools", "coding_agent")
        graph.add_edge("coding_agent", "should_continue")
        
        # Conditional: continue tool loop, proceed to review, or finalize
        # Combines two decisions: (1) need more tools? (2) need review?
        def should_continue_router(s: AgentState) -> str:
            # First check: do we need more tools?
            if s["current_step"] < s["max_steps"] and len(s.get("tool_calls", [])) > 0:
                return "plan_tools"
            
            # Tool loop done. Check if we should review
            if should_review_decision(s) == "review":
                return "review"
            
            # No tools, no review -> finalize
            return "finalise"
        
        graph.add_conditional_edges(
            "should_continue",
            should_continue_router,
            {"plan_tools": "plan_tools", "review": "review_agent", "finalise": "finalise"},
        )
        
        # After review, check if we need to revise
        graph.add_conditional_edges(
            "review_agent",
            check_revision_decision,
            {"revise": "increment_revision", "finalise": "finalise"},
        )
        
        # Increment revision counter and loop back to plan_tools
        graph.add_edge("increment_revision", "plan_tools")
        
        graph.add_edge("finalise", END)

        return graph.compile()

    # ── Nodes ─────────────────────────────────────────────────────────────────

    async def _route_intent_node(self, state: AgentState) -> AgentState:
        """Detect user intent from the message."""
        intent = _detect_intent(state["user_message"])
        return {**state, "intent": intent}

    async def _load_memory_node(self, state: AgentState) -> AgentState:
        """
        Load conversation memory (session + long-term).
        Adds memory context to session_messages for the agent.
        """
        try:
            # Get memory context (both session and long-term)
            memory_context = await self._memory.get_context(
                user_id=state["user_id"],
                conversation_id=state["conversation_id"],
                org_id=state["org_id"],
                repo_id=state.get("repo_id"),
                query=state["user_message"],
                session_limit=10,  # Last 10 messages
                ltm_limit=3,  # Top 3 relevant memories
            )
            
            # Get structured session messages for the agent
            session_messages = await self._memory.get_messages(
                user_id=state["user_id"],
                conversation_id=state["conversation_id"],
                limit=10,
            )
            
            return {
                **state,
                "session_messages": session_messages,
                "memory_context": memory_context,
            }
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to load memory: {e}")
            return {**state, "session_messages": [], "memory_context": ""}

    async def _retrieve_context_node(self, state: AgentState) -> AgentState:
        """
        Retrieve relevant code chunks from ChromaDB.
        Skipped if no repo_id or retriever not available.
        """
        if not state.get("repo_id") or not self._retriever:
            return {**state, "context_block": "", "code_context": [], "context_chunks_used": 0}

        results = await self._retriever.retrieve(
            query=state["user_message"],
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

    async def _plan_tools_node(self, state: AgentState) -> AgentState:
        """Use LLM to decide which tools to call based on user request and state."""
        tool_calls = await self._tool_planner.plan(state)
        return {**state, "tool_calls": tool_calls}

    async def _execute_tools_node(self, state: AgentState) -> AgentState:
        """Execute all planned tool calls and store results."""
        if not state["tool_calls"]:
            return state

        # Build context dict for tools
        from app.db.repositories import RepositoryRepo
        from app.database import get_db_session

        # Get repo path if we have a repo_id
        repo_path = None
        if state.get("repo_id"):
            try:
                async with get_db_session() as session:
                    repo_repo = RepositoryRepo(session)
                    repo = await repo_repo.get_by_id(state["repo_id"])
                    if repo:
                        repo_path = repo.local_path
            except Exception:
                pass  # Continue without repo path

        context = {
            "user_id": state["user_id"],
            "org_id": state["org_id"],
            "repo_id": state.get("repo_id"),
            "conversation_id": state["conversation_id"],
            "request_id": state["request_id"],
            "repo_path": repo_path,
        }

        # Execute tools sequentially
        tool_results = await self._tool_executor.execute_batch(
            state["tool_calls"], context
        )

        # Extract modified file paths from tool results
        files_modified = list(state["files_modified"])  # Copy existing list
        for result in tool_results:
            if result.success and result.metadata:
                # Track files modified by write or apply_patch operations
                path = result.metadata.get("path")
                if path and path not in files_modified:
                    files_modified.append(path)

        # Increment step counter
        return {
            **state,
            "tool_results": state["tool_results"] + tool_results,
            "current_step": state["current_step"] + 1,
            "tool_calls": [],  # Clear for next iteration
            "files_modified": files_modified,
        }

    async def _coding_agent_node(self, state: AgentState) -> AgentState:
        """Run the CodingAgent."""
        return await self._coding_agent.run(state)

    async def _should_continue_node(self, state: AgentState) -> AgentState:
        """
        Decide whether to continue the tool loop or finalize.
        Agent can request more tools by mentioning them in draft_output.
        """
        # Check if we've hit max steps
        if state["current_step"] >= state["max_steps"]:
            return {**state, "tool_calls": []}  # Force exit

        # Check if agent explicitly requests more tools in its output
        draft = state.get("draft_output", "").lower()
        
        # Look for phrases that indicate agent needs more information
        needs_more = any(
            phrase in draft
            for phrase in [
                "need to see",
                "need to check",
                "need to read",
                "let me search",
                "let me check",
                "i need to",
            ]
        )

        if needs_more and state["current_step"] < state["max_steps"]:
            # Re-plan tools based on agent's output
            tool_calls = await self._tool_planner.plan(state)
            return {**state, "tool_calls": tool_calls}
        
        # No more tools needed - proceed to review or finalize
        return {**state, "tool_calls": []}

    async def _review_agent_node(self, state: AgentState) -> AgentState:
        """Run the ReviewAgent."""
        return await self._review_agent.run(state)

    async def _increment_revision_node(self, state: AgentState) -> AgentState:
        """
        Increment revision counter and clear draft for next iteration.
        Called when review says NEEDS_REVISION.
        """
        return {
            **state,
            "revision_count": state["revision_count"] + 1,
            "draft_output": "",  # Clear draft so coding agent generates fresh response
            "current_step": 0,  # Reset step counter for new iteration
            "tool_calls": [],  # Will be re-planned
        }

    async def _finalise_node(self, state: AgentState) -> AgentState:
        """
        Set the final response and save to memory.
        In V2: ReviewAgent runs here before finalising.
        """
        final = state.get("draft_output", "")
        if not final and state.get("error"):
            final = f"I encountered an error: {state['error']}"

        # Save user message and assistant response to session memory
        try:
            await self._memory.add_message(
                user_id=state["user_id"],
                conversation_id=state["conversation_id"],
                role="user",
                content=state["user_message"],
            )
            
            if final:
                await self._memory.add_message(
                    user_id=state["user_id"],
                    conversation_id=state["conversation_id"],
                    role="assistant",
                    content=final,
                )
            
            # Consolidate learnings asynchronously (fire-and-forget)
            await self._memory.consolidate_async(
                user_id=state["user_id"],
                org_id=state["org_id"],
                conversation_id=state["conversation_id"],
                repo_id=state.get("repo_id"),
            )
        except Exception as e:
            from loguru import logger
            logger.warning(f"Failed to save memory: {e}")

        return {**state, "final_response": final}

    # ── Public interface ──────────────────────────────────────────────────────

    async def run(self, state: AgentState) -> AgentState:
        """
        Execute the full agent graph.
        Returns the final AgentState with final_response populated.
        """
        result = await self._graph.ainvoke(state)
        return result

    async def stream(self, state: AgentState):
        """
        Streaming version: yields text tokens as the agent generates them.
        Used by the chat WebSocket endpoint.
        """
        # Run retrieval and routing synchronously first
        state = await self._route_intent_node(state)
        state = await self._retrieve_context_node(state)

        # Stream from the coding agent
        full_response = ""
        async for chunk in self._coding_agent.stream(state):
            full_response += chunk
            yield chunk

        # Finalise state (not yielded — used for persistence)
        state = {**state, "draft_output": full_response, "final_response": full_response}


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
    """FastAPI dependency that returns the singleton orchestrator."""
    return get_orchestrator()