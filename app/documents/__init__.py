"""
Documents package — PDF / Word / text file upload, extraction, and Q&A.

Mirrors the vision package architecture:
  extractor.py  → text extraction per file type (pypdf, python-docx, plain text)
  storage.py    → file + extracted-text persistence on disk
  context.py    → per-conversation document context (Redis + memory fallback)
  service.py    → orchestration: upload, prompt building, chat streaming
  schemas.py    → data structures
"""

from app.documents.service import DocumentService, get_document_service

__all__ = ["DocumentService", "get_document_service"]
