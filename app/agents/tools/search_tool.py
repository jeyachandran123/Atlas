"""
Search tool — semantic code search for agents.

Wraps the retrieval pipeline so agents can search the codebase
the same way the orchestrator does during context retrieval.

The difference from context retrieval:
- Context retrieval is automatic (happens before every agent run)
- Search tool is explicit (agent decides when to call it)
- Useful when the initial context doesn't contain what's needed
"""

from __future__ import annotations

from typing import Any, Optional

from app.agents.tools.base import BaseTool, ToolContext, ToolResult
from app.retrieval.retriever import CodeRetriever
from app.vector_store.base import VectorStore


class SearchTool(BaseTool):
    """
    Semantic and symbol search within the indexed repository.

    Operations:
      semantic(query, top_k)       → ranked code chunks by meaning
      symbol(name)                 → find a specific function/class by name
      find_usages(symbol)          → find all places a symbol is used
    """

    name = "search_tool"
    description = (
        "Search the codebase semantically or by symbol name. "
        "Use semantic search for conceptual queries, symbol search for exact names."
    )

    def __init__(self, vector_store: Optional[VectorStore] = None) -> None:
        self._vs = vector_store
        self._retriever: Optional[CodeRetriever] = None

    def _get_retriever(self) -> Optional[CodeRetriever]:
        if self._retriever is None and self._vs is not None:
            self._retriever = CodeRetriever(self._vs)
        return self._retriever

    async def _execute(self, context: ToolContext, **kwargs: Any) -> ToolResult:
        operation = kwargs.get("operation", "semantic")
        repo_id = context.repo_id

        if not repo_id:
            return ToolResult(self.name, False, error="No repository context available")

        retriever = self._get_retriever()
        if not retriever:
            return ToolResult(self.name, False, error="Search not available — repository not indexed")

        if operation == "semantic":
            return await self._semantic_search(
                retriever, repo_id,
                query=kwargs.get("query", ""),
                top_k=kwargs.get("top_k", 5),
                language=kwargs.get("language"),
            )
        elif operation == "symbol":
            return await self._symbol_search(
                retriever, repo_id,
                symbol_name=kwargs.get("symbol_name", ""),
            )
        else:
            return ToolResult(self.name, False, error=f"Unknown operation: {operation}")

    async def _semantic_search(
        self,
        retriever: CodeRetriever,
        repo_id: str,
        query: str,
        top_k: int = 5,
        language: Optional[str] = None,
    ) -> ToolResult:
        if not query:
            return ToolResult(self.name, False, error="Query is required")

        results = await retriever.retrieve(
            query=query,
            repo_id=repo_id,
            top_k=min(top_k, 10),
            language=language,
        )

        output = [
            {
                "file": r.chunk.file_path,
                "lines": f"{r.chunk.start_line}-{r.chunk.end_line}",
                "type": r.chunk.chunk_type.value,
                "name": r.chunk.function_name or r.chunk.class_name or "",
                "score": round(r.score, 3),
                "preview": r.chunk.content[:300] + "..." if len(r.chunk.content) > 300 else r.chunk.content,
            }
            for r in results
        ]

        return ToolResult(
            self.name, True,
            output=output,
            metadata={"query": query, "results_found": len(output)},
        )

    async def _symbol_search(
        self,
        retriever: CodeRetriever,
        repo_id: str,
        symbol_name: str,
    ) -> ToolResult:
        if not symbol_name:
            return ToolResult(self.name, False, error="symbol_name is required")

        results = await retriever.search_by_symbol(
            symbol_name=symbol_name,
            repo_id=repo_id,
            top_k=5,
        )

        output = [
            {
                "file": r.chunk.file_path,
                "lines": f"{r.chunk.start_line}-{r.chunk.end_line}",
                "type": r.chunk.chunk_type.value,
                "name": r.chunk.function_name or r.chunk.class_name,
                "score": round(r.score, 3),
                "content": r.chunk.content,
            }
            for r in results
        ]

        return ToolResult(
            self.name, True,
            output=output,
            metadata={"symbol": symbol_name, "results_found": len(output)},
        )
