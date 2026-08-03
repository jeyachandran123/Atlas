"""Executable port conformance kits (06_PORTS_AND_ADAPTERS section 5).

The mechanism that converts invariant V3 — "every model is replaceable" — from a
claim in a document into a gate in the loader.
"""

from __future__ import annotations

from .detector_kit import DETECTOR_KIT, detector_kit_checks
from .flow1_kits import ALL_FLOW1_KITS, flow1_registry, platform_registry
from .kit import (
    ConformanceCheck,
    ConformanceKit,
    ConformanceRegistry,
    ConformanceReport,
    KitSection,
)
from .model_kits import (
    ALL_MODEL_KITS,
    ARTIFACT_STORE_KIT,
    DEVICE_KIT,
    MODEL_RUNTIME_KIT,
)
from .tracker_kit import DETERMINISM_CHECK, TRACKER_KIT

__all__ = [
    "ALL_FLOW1_KITS",
    "ALL_MODEL_KITS",
    "ARTIFACT_STORE_KIT",
    "DETECTOR_KIT",
    "DETERMINISM_CHECK",
    "DEVICE_KIT",
    "MODEL_RUNTIME_KIT",
    "TRACKER_KIT",
    "ConformanceCheck",
    "ConformanceKit",
    "ConformanceRegistry",
    "ConformanceReport",
    "KitSection",
    "detector_kit_checks",
    "flow1_registry",
    "platform_registry",
]
