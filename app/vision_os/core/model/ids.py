"""Identifier construction (02_VISION_OBJECT_MODEL §4.1).

Identity is where vision systems most often accumulate permanent, invisible
corruption. Two constructions here carry outsized weight:

``FrameRef``
    ``(camera_id, stream_epoch, frame_seq)``. Every RTSP source eventually
    reconnects, and every naive implementation restarts frame numbering at zero
    — so frame 100 before the reconnect and frame 100 after it compare equal
    while describing different instants. The epoch makes reconnection explicit
    and keeps ``FrameRef`` genuinely unique for the deployment's lifetime.

``ULID``
    Time-sortable, mintable by any partition on any node without coordination.
    A central sequence would make identity allocation a distributed bottleneck
    at exactly the scale where it must not be.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import NewType

TenantId = NewType("TenantId", str)
SiteId = NewType("SiteId", str)
CameraId = NewType("CameraId", str)
RegionId = NewType("RegionId", str)
CalibrationId = NewType("CalibrationId", str)
ConfigRevision = NewType("ConfigRevision", str)
PluginId = NewType("PluginId", str)
PortId = NewType("PortId", str)
AdapterId = NewType("AdapterId", str)
ModuleId = NewType("ModuleId", str)
ProfileId = NewType("ProfileId", str)
PrivacyPolicyId = NewType("PrivacyPolicyId", str)

StreamEpoch = NewType("StreamEpoch", int)
FrameSeq = NewType("FrameSeq", int)


# --- ULID ---------------------------------------------------------------- #

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_LEN = 26


def new_ulid(now_ms: int | None = None) -> str:
    """Mint a lexicographically time-sortable 26-character ULID.

    Pure stdlib by design — ``core`` may not depend on third-party packages.
    Randomness comes from ``os.urandom`` rather than ``random`` so that IDs are
    not predictable from one another.

    Args:
        now_ms: Millisecond timestamp to encode. Defaults to the wall clock.
            Callers on a deterministic path pass an explicit value so that ID
            generation does not reintroduce hidden time (invariant V13).
    """
    timestamp = int(time.time() * 1000) if now_ms is None else now_ms
    randomness = int.from_bytes(os.urandom(10), "big")
    value = (timestamp << 80) | randomness
    out = [""] * _ULID_LEN
    for i in range(_ULID_LEN - 1, -1, -1):
        out[i] = _CROCKFORD[value & 0x1F]
        value >>= 5
    return "".join(out)


def ulid_timestamp_ms(ulid: str) -> int:
    """Recover the millisecond timestamp encoded in a ULID."""
    if len(ulid) != _ULID_LEN:
        raise ValueError(f"malformed ULID: expected {_ULID_LEN} chars, got {len(ulid)}")
    value = 0
    for char in ulid:
        index = _CROCKFORD.find(char.upper())
        if index < 0:
            raise ValueError(f"malformed ULID: illegal character {char!r}")
        value = (value << 5) | index
    return value >> 80


# --- FrameRef ------------------------------------------------------------ #


@dataclass(frozen=True, slots=True, order=True)
class FrameRef:
    """Globally unique, totally ordered reference to one decoded instant.

    Ordering is defined per camera. Comparing frames across cameras by ``FrameRef``
    is meaningless — cross-camera ordering uses ``t_capture`` with its declared
    uncertainty (02_VOM §5.2 rule 3).
    """

    camera_id: CameraId
    stream_epoch: StreamEpoch
    frame_seq: FrameSeq

    def __post_init__(self) -> None:
        if self.stream_epoch < 0:
            raise ValueError(f"stream_epoch must be non-negative, got {self.stream_epoch}")
        if self.frame_seq < 0:
            raise ValueError(f"frame_seq must be non-negative, got {self.frame_seq}")

    def follows_in_same_epoch(self, other: FrameRef) -> bool:
        """True when this frame is strictly later than ``other`` in the same epoch.

        The tracker and every order-dependent stage asserts on this rather than
        degrading quietly when frames arrive out of order (06_PORTS T1).
        """
        return (
            self.camera_id == other.camera_id
            and self.stream_epoch == other.stream_epoch
            and self.frame_seq > other.frame_seq
        )

    def __str__(self) -> str:
        return f"{self.camera_id}/e{self.stream_epoch}/f{self.frame_seq}"
