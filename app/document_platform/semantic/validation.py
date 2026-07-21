"""
Embedding Validation (Objective 5). Runs before every registration —
an invalid embedding must never reach the registry or vector store.

EmbeddingValidationError subclasses ValueError deliberately: the existing
RetryPolicy in processing/retry.py already treats ValueError as
non-retryable, so this reuses that classification without touching the
frozen retry module — a bad/malformed vector will not regenerate the same
way on retry, so retrying it is pointless.
"""
from __future__ import annotations

import math

from app.document_platform.semantic.providers import EmbeddingResult


class EmbeddingValidationError(ValueError):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


class EmbeddingValidator:
    def validate(
        self,
        result: EmbeddingResult,
        *,
        expected_dimensions: int,
        knowledge_exists: bool,
        is_duplicate: bool,
    ) -> None:
        reasons: list[str] = []

        if not result.vector:
            reasons.append("embedding vector is empty")
        else:
            if expected_dimensions and len(result.vector) != expected_dimensions:
                reasons.append(
                    f"dimension mismatch: got {len(result.vector)}, expected {expected_dimensions}"
                )
            if any(math.isnan(x) or math.isinf(x) for x in result.vector):
                reasons.append("vector contains NaN or Inf values")
            if all(x == 0.0 for x in result.vector):
                reasons.append("vector is all-zero (likely a provider failure, not a real embedding)")

        if not knowledge_exists:
            reasons.append("knowledge object does not exist")
        if is_duplicate:
            reasons.append("embedding already registered for this chunk at this version")

        if reasons:
            raise EmbeddingValidationError(reasons)
