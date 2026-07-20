"""LanguageDetector — detects the dominant document language (ISO 639-1)."""
from __future__ import annotations

from loguru import logger


class LanguageDetector:
    SAMPLE_CHARS = 4000
    MIN_CHARS = 20

    def detect(self, text: str) -> str:
        sample = text.strip()[: self.SAMPLE_CHARS]
        if len(sample) < self.MIN_CHARS:
            return "unknown"
        try:
            from langdetect import DetectorFactory, detect
            DetectorFactory.seed = 0  # deterministic
            return detect(sample)
        except Exception as e:
            logger.debug(f"Language detection failed: {e}")
            return "unknown"
