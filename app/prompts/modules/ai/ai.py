"""
AI & Agent engineering prompt modules.
"""

from __future__ import annotations

LANGGRAPH = """\
LangGraph expertise: StateGraph design, TypedDict state, node functions, \
conditional edges, tool-use loops, human-in-the-loop checkpoints, \
streaming, and multi-agent subgraphs."""

LANGCHAIN = """\
LangChain expertise: chains, agents, tools, memory, \
document loaders, text splitters, retrievers, \
and LCEL (LangChain Expression Language) composition."""

RAG = """\
RAG (Retrieval-Augmented Generation) expertise: \
chunking strategies (semantic, recursive, AST-based), \
embedding models, vector store selection, \
MMR retrieval, re-ranking, and context window management."""

MULTI_AGENT = """\
Multi-agent system expertise: agent specialization, \
supervisor/worker patterns, message passing, \
shared state management, conflict resolution, \
and orchestration with LangGraph subgraphs."""

PROMPT_ENGINEERING = """\
Prompt engineering expertise: chain-of-thought, \
few-shot examples, structured output (JSON mode), \
system/user/assistant role separation, \
temperature tuning, and prompt injection prevention."""

OLLAMA = """\
Ollama expertise: local model deployment, model selection by task, \
context window management, streaming responses, \
and model quantization trade-offs (Q4 vs Q8)."""

VECTOR_DB = """\
Vector database expertise: embedding dimensionality, \
similarity metrics (cosine, dot product, L2), \
HNSW index parameters, hybrid search (dense + sparse), \
and namespace/collection management."""
