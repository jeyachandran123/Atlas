"""
Document Intelligence Platform (DIP).

Phase 1 — storage foundation: upload, validate, store (blob storage + metadata),
list/search, signed download, soft delete, audit. No parsing, no embeddings,
no AI. Later phases (chunking, RAG, generation) build on the Document entity
and the service layer defined here without modifying them.
"""
