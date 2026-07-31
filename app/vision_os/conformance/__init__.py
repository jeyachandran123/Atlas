"""Executable port conformance kits (06_PORTS_AND_ADAPTERS §5).

The mechanism that converts invariant V3 — "every model is replaceable" — from a
claim in a document into a gate in the loader.
"""

from __future__ import annotations

from .flow1_kits import ALL_FLOW1_KITS, flow1_registry
from .kit import (
    ConformanceCheck,
    ConformanceKit,
    ConformanceRegistry,
    ConformanceReport,
    KitSection,
)

__all__ = [
    "ALL_FLOW1_KITS",
    "ConformanceCheck",
    "ConformanceKit",
    "ConformanceRegistry",
    "ConformanceReport",
    "KitSection",
    "flow1_registry",
]
