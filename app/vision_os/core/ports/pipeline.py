"""The pipeline continuation seam.

Flow 1's Runtime ends at admission: an admitted frame is counted and released.
This protocol is the **single, documented extension point** at which a later flow
resumes the admitted-frame path (Flow 1 report section 11).

It carries a ``FrameRef``, not a ``Frame``. The consumer takes its own lease from
the Frame Buffer, which means:

* the lease protocol is exercised rather than bypassed, so a frame evicted
  between admission and consumption produces a clean ``FrameUnavailableError``
  degradation instead of a dangling reference;
* the payload stays control-plane sized, so the same seam works when the consumer
  runs in another process or on another node (invariant V12).

Flow 1 remains unaware of any consumer: the Runtime holds this protocol and never
learns what implements it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..model.ids import FrameRef
from .scheduling import Fidelity


@runtime_checkable
class AdmittedFrameConsumer(Protocol):
    """Resumes the pipeline after admission.

    Implementations **must not raise**. A failure in a later stage may never
    terminate the Vision Runtime or a source actor (invariant V9); it degrades,
    counts, and publishes.
    """

    async def on_admitted(self, frame_ref: FrameRef, fidelity: Fidelity) -> None:
        """Consume one admitted frame.

        Args:
            frame_ref: The admitted frame. Take a lease from the Frame Buffer to
                read its pixels; treat ``FrameUnavailableError`` as normal.
            fidelity: The resolution tier and model tier the scheduler selected.
        """
        ...
