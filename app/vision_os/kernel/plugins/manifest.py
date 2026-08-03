"""Plugin manifests and the port registry (05_KERNEL M17, 06_PORTS §2).

A manifest is a plugin's declaration of what it is, what it implements, what it
needs, and what it can produce. Declaring capabilities **honestly** is adapter
obligation A1: it is what lets the platform report a capability gap immediately
rather than leaving a consumer waiting forever for data that will never arrive.

The port catalogue is closed in the same spirit as the object ontology: adding a
port is a deliberate, reviewed act, not something a plugin can do by asserting a
new name.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

from ...core.model.ids import PluginId, PortId


class IsolationLevel(enum.Enum):
    """How a plugin is invoked (05_KERNEL M17 performance).

    The same plugin moves between levels **by configuration alone**, which is
    what allows a detector to run in-process on an edge box and on a remote
    inference server in a cluster with no code difference.
    """

    IN_PROCESS = "in_process"
    SUBPROCESS = "subprocess"
    REMOTE = "remote"


class PortCatalogue:
    """The 32 ports of 06_PORTS_AND_ADAPTERS §2.

    All are named so that manifests referencing a later-flow port fail
    validation with a clear message rather than a confusing lookup error. Only
    the Flow 1 subset is *bindable*; see ``FLOW1_PORTS``.
    """

    SOURCE = PortId("P1.SourcePort")
    DECODER = PortId("P2.DecoderPort")
    PRIVACY_MASK = PortId("P3.PrivacyMaskPort")
    CLOCK_SYNC = PortId("P4.ClockSyncPort")
    ADMISSION_POLICY = PortId("P5.AdmissionPolicyPort")
    CHANGE_DETECTOR = PortId("P6.ChangeDetectorPort")
    ALLOCATOR = PortId("P7.AllocatorPort")
    DETECTOR = PortId("P8.DetectorPort")
    TRACKER = PortId("P9.TrackerPort")
    EMBEDDING = PortId("P10.EmbeddingPort")
    IDENTITY_RESOLVER = PortId("P11.IdentityResolverPort")
    TRIGGER_POLICY = PortId("P12.TriggerPolicyPort")
    QUALITY_ESTIMATOR = PortId("P13.QualityEstimatorPort")
    CROP_STRATEGY = PortId("P14.CropStrategyPort")
    UNDERSTANDER = PortId("P15.UnderstanderPort")
    OUTPUT_COERCION = PortId("P16.OutputCoercionPort")
    PROMPT_SOURCE = PortId("P17.PromptSourcePort")
    SUPPRESSION_POLICY = PortId("P18.SuppressionPolicyPort")
    OBSERVATION_SINK = PortId("P19.ObservationSinkPort")
    OBSERVATION_LOG = PortId("P20.ObservationLogPort")
    STATE_STORE = PortId("P21.StateStorePort")
    EVIDENCE_STORE = PortId("P22.EvidenceStorePort")
    CONFIG_SOURCE = PortId("P23.ConfigSourcePort")
    SECRET_PROVIDER = PortId("P24.SecretProviderPort")
    ARTIFACT_STORE = PortId("P25.ArtifactStorePort")
    MODEL_RUNTIME = PortId("P26.ModelRuntimePort")
    DEVICE = PortId("P27.DevicePort")
    CALIBRATION = PortId("P28.CalibrationPort")
    EVENT_TRANSPORT = PortId("P29.EventTransportPort")
    METRICS_EXPORT = PortId("P30.MetricsExportPort")
    AUTHORIZATION = PortId("P31.AuthorizationPort")
    API_TRANSPORT = PortId("P32.ApiTransportPort")


ALL_PORTS: frozenset[PortId] = frozenset(
    value for key, value in vars(PortCatalogue).items() if not key.startswith("_")
)

#: Ports implemented by Flow 1.
FLOW1_PORTS: frozenset[PortId] = frozenset(
    {
        PortCatalogue.SOURCE,
        PortCatalogue.DECODER,
        PortCatalogue.PRIVACY_MASK,
        PortCatalogue.CLOCK_SYNC,
        PortCatalogue.ADMISSION_POLICY,
        PortCatalogue.CHANGE_DETECTOR,
        PortCatalogue.ALLOCATOR,
        PortCatalogue.CONFIG_SOURCE,
        PortCatalogue.SECRET_PROVIDER,
        PortCatalogue.EVENT_TRANSPORT,
        PortCatalogue.METRICS_EXPORT,
    }
)

#: Ports implemented by Flow 2 — detection and the model substrate that serves it.
FLOW2_PORTS: frozenset[PortId] = frozenset(
    {
        PortCatalogue.DETECTOR,
        PortCatalogue.ARTIFACT_STORE,
        PortCatalogue.MODEL_RUNTIME,
        PortCatalogue.DEVICE,
    }
)

#: Everything currently bindable. Binding anything else is rejected, because a
#: plugin for a port whose owning module does not exist yet cannot be activated —
#: which is how "no future flow is implemented early" stays enforceable.
BINDABLE_PORTS: frozenset[PortId] = FLOW1_PORTS | FLOW2_PORTS


@dataclass(frozen=True, slots=True)
class VersionRange:
    """An inclusive-exclusive semantic version range, ``>=min <max``."""

    minimum: tuple[int, int, int]
    maximum: tuple[int, int, int]

    @classmethod
    def parse(cls, text: str) -> VersionRange:
        """Parse ``">=1.2 <2.0"``."""
        minimum = (0, 0, 0)
        maximum = (999, 0, 0)
        for token in text.split():
            if token.startswith(">="):
                minimum = _parse_version(token[2:])
            elif token.startswith("<"):
                maximum = _parse_version(token[1:])
            else:
                raise ValueError(f"malformed version range token: {token!r}")
        return cls(minimum, maximum)

    def contains(self, version: str) -> bool:
        parsed = _parse_version(version)
        return self.minimum <= parsed < self.maximum

    def __str__(self) -> str:
        return f">={_fmt(self.minimum)} <{_fmt(self.maximum)}"


def _parse_version(text: str) -> tuple[int, int, int]:
    parts = text.strip().split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as exc:
        raise ValueError(f"malformed version: {text!r}") from exc


def _fmt(version: tuple[int, int, int]) -> str:
    return ".".join(str(v) for v in version)


@dataclass(frozen=True, slots=True)
class ResourceDeclaration:
    """What a plugin claims it needs. A declaration is a contract, not a hint."""

    device: str = "cpu"
    memory_bytes: int = 0
    vram_bytes: int = 0
    exclusive: bool = False


@dataclass(frozen=True, slots=True)
class PluginManifest:
    """A plugin's self-declaration (06_PORTS §3, 05_KERNEL M17)."""

    plugin_id: PluginId
    version: str
    port_id: PortId
    port_version_range: VersionRange
    platform_range: VersionRange
    isolation: IsolationLevel = IsolationLevel.IN_PROCESS
    resources: ResourceDeclaration = ResourceDeclaration()
    thread_safe: bool = True
    """Declared, and honoured by the runtime: a plugin declaring itself
    single-threaded gets a dedicated worker rather than an unsafe shared one."""

    deterministic: bool = True
    """V13 replay must know what to expect."""

    capabilities: dict[str, str] = field(default_factory=dict)
    """Published so capability gaps are detectable (V8)."""

    signature: str | None = None
    conformance_kit_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if not self.plugin_id:
            raise ValueError("plugin_id is required")
        if not self.version:
            raise ValueError("version is required")
        _parse_version(self.version)
