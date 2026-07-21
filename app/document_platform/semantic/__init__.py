"""
Semantic Intelligence Layer (Phase 3).

Converts Knowledge Objects into semantic representations (embeddings,
vectors, an index) that future retrieval/reasoning subsystems will consume.

This package deliberately does NOT implement retrieval, RAG, chat, or any
LLM reasoning — it stops at "ready for retrieval". It consumes the frozen
Knowledge Platform (Phase 2/2.5/2.6) read-only and never modifies it.
"""
