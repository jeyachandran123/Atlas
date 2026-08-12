"""Which detector a deployment binds — resolved here, like the understander.

The sibling of ``understander_providers``, and for the same reasons: a closed
factory table keyed by configuration, environment read at this seam rather than
inside an adapter, and the platform never told the name. ``build_detection_layer``
takes a ``detector_factory`` and calls it with a declaration; what that factory
returns is a composition decision, not a platform one.

### Why the class list is not in this file

``open_onnx_detector_session`` reads the names out of the graph's own metadata,
and the ``TaxonomyMapping`` built here is derived from that list. A COCO constant
written into this repository would silently mislabel every object the day
somebody binds a model trained on something else — and a mislabelled detection is
worse than a missing one, because it is wrong with full confidence and it
propagates into tracking, cropping, prompts and observations before anyone
notices.

So the model declares what it can name, this module maps those names onto
platform classes, and a deployment may narrow the result but never invent it.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ...core.model.ids import AdapterId, ClassId, ModelId
from ...core.model.taxonomy import MappingEntry, TaxonomyMapping, UnmappedPolicy

#: Selector. ``yolo`` is the default because a scripted detector must never be
#: what a demo or a deployment runs by accident: it answers with the same box on
#: every frame regardless of the pixels, and everything downstream — tracking,
#: crops, prompts, attributes, observations — is then real machinery operating on
#: a fiction.
PROVIDER_ENV = "VISION_DETECTOR_PROVIDER"
WEIGHTS_ENV = "VISION_DETECTOR_WEIGHTS"
CLASSES_ENV = "VISION_DETECTOR_CLASSES"
CONFIDENCE_ENV = "VISION_DETECTOR_CONFIDENCE"
IOU_ENV = "VISION_DETECTOR_IOU"

DEFAULT_PROVIDER = "yolo"
DEFAULT_WEIGHTS = "models/yolov8n.onnx"


class DetectorConfigurationError(ValueError):
    """A detector was named that cannot be built. Raised at composition time."""


def resolve_detector_provider(env: Mapping[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return ((source.get(PROVIDER_ENV) or "").strip().lower()) or DEFAULT_PROVIDER


def default_weights_path() -> Path:
    """``backend/models/yolov8n.onnx``, relative to this package."""
    return Path(__file__).resolve().parents[4] / DEFAULT_WEIGHTS


def _setting(env: Mapping[str, str], name: str, default: str = "") -> str:
    return (env.get(name) or "").strip() or default


class BoundDetector:
    """What a composition root needs to wire a detector into the platform.

    The detector alone is not enough: the config document must declare the same
    class list and the same artifact hash, and the Crop Manager and the
    Observation API must be told which classes exist. Returning them together
    stops those four places drifting apart — which they did, silently, when the
    taxonomy said ``person`` and the detector could produce eighty things.
    """

    __slots__ = ("adapter_id", "classes", "detector", "mappings", "model_id",
                 "model_version", "artifact_hash", "artifact_path", "note")

    def __init__(
        self,
        *,
        detector: Any,
        adapter_id: str,
        classes: tuple[ClassId, ...],
        mappings: tuple[MappingEntry, ...],
        model_id: str,
        model_version: str,
        artifact_hash: str,
        artifact_path: str,
        note: str,
    ) -> None:
        self.detector = detector
        # Carried rather than read off the detector: `DetectorPort` declares
        # `capabilities`, `detect` and `warm` and nothing else. `adapter_id` is
        # an understander concept, and reaching for one here would work by
        # accident on adapters that happen to have it.
        self.adapter_id = adapter_id
        self.classes = classes
        self.mappings = mappings
        self.model_id = model_id
        self.model_version = model_version
        self.artifact_hash = artifact_hash
        self.artifact_path = artifact_path
        self.note = note

    def declaration(self, *, detector_id: str, artifact_uri: str) -> dict[str, Any]:
        """The config-document entry describing this binding.

        Written before ``build_platform`` reads configuration, because the
        platform reads it once at construction: mutating the document afterwards
        leaves a running platform bound to a detector list it never saw.
        """
        return {
            "detector_id": detector_id,
            "adapter_id": self.adapter_id,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "artifact_uri": artifact_uri,
            "artifact_hash": self.artifact_hash,
            "role": "primary_detector",
            "mappings": [
                {"native_label": entry.native_label, "class_id": str(entry.class_id)}
                for entry in self.mappings
            ],
        }


def _build_yolo(*, clock, env: Mapping[str, str], **_: Any) -> BoundDetector:
    from ..detection.yolo import YoloDetector
    from ..models.runtimes import open_onnx_detector_session

    path = Path(_setting(env, WEIGHTS_ENV) or default_weights_path())
    if not path.is_file():
        raise DetectorConfigurationError(
            f"detector weights not found at '{path}'. Set {WEIGHTS_ENV} to an ONNX "
            f"detection graph. Binding a scripted detector instead would answer "
            f"with the same box on every frame, and nothing downstream could tell."
        )

    session = open_onnx_detector_session(
        str(path),
        conf_threshold=float(_setting(env, CONFIDENCE_ENV, "0.25")),
        iou_threshold=float(_setting(env, IOU_ENV, "0.45")),
    )

    # The model's own names, optionally narrowed. `UnmappedPolicy.DROP` then
    # discards anything outside the selection at the adapter boundary, so a
    # narrowed deployment never sees a class its taxonomy does not define.
    declared = list(session.class_names())
    wanted = {
        name.strip().lower()
        for name in _setting(env, CLASSES_ENV).split(",")
        if name.strip()
    }
    selected = [name for name in declared if not wanted or name.lower() in wanted]
    if not selected:
        raise DetectorConfigurationError(
            f"{CLASSES_ENV} selected none of the model's {len(declared)} classes; "
            f"a detector that can produce nothing would never be routed to"
        )

    mappings = tuple(
        MappingEntry(native_label=name, class_id=ClassId(_platform_class(name)))
        for name in selected
    )
    model_id = path.stem
    artifact_hash = f"blake2b:{_digest(path)}"

    detector = YoloDetector(
        clock=clock,
        session=session,
        mapping=TaxonomyMapping(
            adapter_id=AdapterId("detector.yolo"),
            model_id=ModelId(model_id),
            entries=mappings,
            unmapped_policy=UnmappedPolicy.DROP,
            native_label_space="coco" if len(declared) == 80 else "custom",
        ),
        model_id=ModelId(model_id),
        model_version="1.0.0",
        artifact_hash=artifact_hash,
    )

    return BoundDetector(
        detector=detector,
        adapter_id="detector.yolo",
        classes=tuple(dict.fromkeys(entry.class_id for entry in mappings)),
        mappings=mappings,
        model_id=model_id,
        model_version="1.0.0",
        artifact_hash=artifact_hash,
        artifact_path=str(path),
        note=(
            f"yolo ({model_id}, {len(selected)} of {len(declared)} classes"
            + (", narrowed by configuration" if wanted else "")
            + ")"
        ),
    )


def _build_reference(*, clock, env: Mapping[str, str], **_: Any) -> BoundDetector:
    """The scripted detector. **For fixtures, never for a demo or a deployment.**

    It answers with a fixed box on every frame regardless of the pixels, which
    makes it invaluable for testing the letterbox inverse without a GPU and
    actively misleading anywhere else. Selecting it is therefore explicit, and
    the note says plainly what it is so the model panel cannot imply otherwise.
    """
    from ..detection.reference import ReferenceDetector, ScriptedDetection
    from ...core.model.space import Box

    person = ClassId("person")
    return BoundDetector(
        detector=ReferenceDetector(
            clock=clock,
            producible_classes=(person,),
            script=(ScriptedDetection(person, Box(0.3, 0.15, 0.62, 0.9), 0.92),),
        ),
        adapter_id="detector.reference",
        classes=(person,),
        mappings=(MappingEntry(native_label="person", class_id=person),),
        model_id="reference-detector",
        model_version="1.0.0",
        artifact_hash=f"blake2b:{hashlib.blake2b(b'reference', digest_size=32).hexdigest()}",
        artifact_path="",
        note="reference (scripted — a fixed box, not real detection)",
    )


#: A closed table, like the understander, crop-strategy and coercion factories.
DETECTOR_FACTORIES: Mapping[str, Any] = {
    "yolo": _build_yolo,
    "reference": _build_reference,
}


def build_detector(
    *,
    clock,
    provider: str | None = None,
    env: Mapping[str, str] | None = None,
) -> BoundDetector:
    """Build the configured detector, or say clearly why not.

    Raises:
        DetectorConfigurationError: the provider is unknown, or its weights are
            missing. Both are composition-time failures, and neither falls back
            to the scripted detector: a demo that silently degraded to a fixed
            box would show a working pipeline built on a constant.
    """
    source = dict(os.environ if env is None else env)
    name = (provider or resolve_detector_provider(source)).strip().lower()
    factory = DETECTOR_FACTORIES.get(name)
    if factory is None:
        raise DetectorConfigurationError(
            f"{PROVIDER_ENV}='{name}' is not a registered detector provider. "
            f"Available: {', '.join(sorted(DETECTOR_FACTORIES))}."
        )
    return factory(clock=clock, env=source)


def _platform_class(native_label: str) -> str:
    """COCO labels contain spaces; platform class ids use underscores."""
    return native_label.strip().lower().replace(" ", "_")


def _digest(path: Path) -> str:
    hasher = hashlib.blake2b(digest_size=32)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(block)
    return hasher.hexdigest()


__all__ = [
    "CLASSES_ENV",
    "DEFAULT_PROVIDER",
    "DETECTOR_FACTORIES",
    "PROVIDER_ENV",
    "WEIGHTS_ENV",
    "BoundDetector",
    "DetectorConfigurationError",
    "build_detector",
    "default_weights_path",
    "resolve_detector_provider",
]
