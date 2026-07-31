"""Port protocols — Flow 1 subset (06_PORTS_AND_ADAPTERS).

A port is three things, not one::

    Port = Interface  +  Semantic Contract  +  Conformance Kit
           (shape)       (meaning)             (executable proof)

The interface lives here. The semantic contract lives in each protocol's
docstring. The conformance kit lives in ``vision_os.conformance`` and is run by
the Plugin Manager **before an adapter is activated** — which is what converts
"every model is replaceable" from a claim into a gate.

Flow 1 implements 11 of the catalogue's 32 ports:

    P1  SourcePort            P5  AdmissionPolicyPort   P23 ConfigSourcePort
    P2  DecoderPort           P6  ChangeDetectorPort    P24 SecretProviderPort
    P3  PrivacyMaskPort       P7  AllocatorPort         P29 EventTransportPort
    P4  ClockSyncPort         --  Clock (kernel)        P30 MetricsExportPort

The remaining 21 ports belong to later flows and are deliberately absent.
"""

from __future__ import annotations

from .acquisition import (
    CaptureEstimate,
    ClockSyncPort,
    DecodeOutcome,
    DecoderCapabilities,
    DecoderPort,
    MaskOutcome,
    PrivacyMaskPort,
    SourceCapabilities,
    SourceHandle,
    SourcePacket,
    SourcePort,
)
from .buffer import Allocation, AllocatorPort, AllocatorStats, WritableSlot
from .clock import Clock
from .configuration import ConfigSourcePort, SecretProviderPort
from .observability import EventTransportPort, MetricsExportPort, MetricsSnapshotView
from .scheduling import (
    AdmissionContext,
    AdmissionPolicyPort,
    AdmissionVerdict,
    ChangeDetectorPort,
    ChangeVerdict,
    DropReason,
    Fidelity,
)

__all__ = [
    "AdmissionContext",
    "AdmissionPolicyPort",
    "AdmissionVerdict",
    "Allocation",
    "AllocatorPort",
    "AllocatorStats",
    "CaptureEstimate",
    "ChangeDetectorPort",
    "ChangeVerdict",
    "Clock",
    "ClockSyncPort",
    "ConfigSourcePort",
    "DecodeOutcome",
    "DecoderCapabilities",
    "DecoderPort",
    "DropReason",
    "EventTransportPort",
    "Fidelity",
    "MaskOutcome",
    "MetricsExportPort",
    "MetricsSnapshotView",
    "PrivacyMaskPort",
    "SecretProviderPort",
    "SourceCapabilities",
    "SourceHandle",
    "SourcePacket",
    "SourcePort",
    "WritableSlot",
]
