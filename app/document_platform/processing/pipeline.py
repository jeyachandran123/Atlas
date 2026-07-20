"""
Backward-compatibility shim.

The coordination logic that used to live here moved to orchestrator.py
(Architecture Foundation Hardening, Objective 1). `DocumentProcessingPipeline`
is kept as an alias so any existing import of this module keeps working
unchanged.
"""
from __future__ import annotations

from app.document_platform.processing.orchestrator import (
    ProcessingFailure,
    ProcessingOrchestrator as DocumentProcessingPipeline,
)

__all__ = ["DocumentProcessingPipeline", "ProcessingFailure"]
