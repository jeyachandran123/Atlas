"""
Intelligent Content Generation Platform (Phase 5).

The LLM plans (a strict-JSON GenerationSpec); the Transformation Engine
shapes it into the canonical ContentModel; deterministic builders render
bytes; BlobStorage stores; the Download Service serves signed URLs.

The LLM never writes file bytes. Builders never call the LLM.
"""
