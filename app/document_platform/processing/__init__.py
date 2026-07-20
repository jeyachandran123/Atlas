"""
DIP Phase 2 — Document Processing & Knowledge Foundation.

Pipeline: load → detect → parse → (ocr?) → normalize → metadata → structure →
tables → images → language → clean → chunk → knowledge object → store.

Every stage is an independent, injectable service. Parsers never normalize,
never chunk, never OCR. No AI calls exist in this package — the embedding
provider is an interface only, wired in Phase 3.
"""
