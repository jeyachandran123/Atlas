"""
Processing Profiles (Objective 6).

A profile configures the tunable knobs of a processing run. Only "standard"
is implemented — its values match today's hardcoded defaults exactly, so
processing behaviour is byte-identical to before this hardening. Future
profiles (fast, ocr_optimized, financial, legal, medical) are new registry
entries; the orchestrator never changes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessingProfile:
    name: str
    chunk_target_tokens: int = 400
    chunk_max_tokens: int = 600
    enable_ocr: bool = True
    enable_tables: bool = True
    enable_images: bool = True


_PROFILES: dict[str, ProcessingProfile] = {
    "standard": ProcessingProfile(name="standard"),
    # Future: "fast" (larger chunks, OCR disabled), "ocr_optimized" (OCR forced,
    # smaller chunks), "financial"/"legal"/"medical" (domain-tuned chunking) —
    # each is one new entry here, zero orchestrator changes.
}

DEFAULT_PROFILE = "standard"


def get_profile(name: str | None) -> ProcessingProfile:
    """Unknown or missing profile names fall back to standard rather than
    failing the whole document — profile selection must never be a hard error."""
    return _PROFILES.get(name or DEFAULT_PROFILE, _PROFILES[DEFAULT_PROFILE])


def list_profiles() -> list[str]:
    return sorted(_PROFILES.keys())
