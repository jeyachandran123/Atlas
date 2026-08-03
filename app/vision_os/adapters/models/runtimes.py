"""P26 ``ModelRuntimePort`` — turn a verified artifact into an executable session.

This port is what makes an adapter *family* portable. The same YOLO adapter runs
on ultralytics locally and on ONNX at the edge, because the parts that matter for
correctness — letterboxing, coordinate inversion, taxonomy mapping — live in the
adapter, and only the tensor call lives here.

``DetectorSession`` is the narrow contract the detection adapters consume: give
it letterboxed images, get back boxes in letterboxed pixel space. Everything
about inverting that space is the adapter's job and is therefore testable without
a GPU.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from time import sleep
from typing import Protocol, runtime_checkable

from ...core.errors import ModelLoadError
from ...core.ports.models import LoadedModel


@dataclass(frozen=True, slots=True)
class LetterboxTransform:
    """How a source image was fitted into the model's input square.

    Retained so the inverse is exact rather than approximate. Recording the
    transform is what makes two models comparable: evaluating them on
    differently-letterboxed crops is not a fair comparison, and without this
    field nobody finds out.
    """

    scale: float
    pad_x: float
    pad_y: float
    source_width: int
    source_height: int
    target_width: int
    target_height: int

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise ValueError(f"letterbox scale must be positive, got {self.scale}")
        if self.source_width <= 0 or self.source_height <= 0:
            raise ValueError("letterbox source dimensions must be positive")


@dataclass(frozen=True, slots=True)
class LetterboxedImage:
    """One image prepared for inference, with the transform that produced it."""

    pixels: memoryview
    width: int
    height: int
    transform: LetterboxTransform


@dataclass(frozen=True, slots=True)
class RawBox:
    """A model's native output: letterboxed pixel space, native class index."""

    x1: float
    y1: float
    x2: float
    y2: float
    score: float
    class_index: int


@runtime_checkable
class DetectorSession(Protocol):
    """An executable detection model."""

    def infer(
        self, images: Sequence[LetterboxedImage]
    ) -> Sequence[Sequence[RawBox]]:
        """Run inference. Results map 1:1 and in order to ``images``."""
        ...

    def class_names(self) -> Sequence[str]:
        """The model's native label space, indexed by class index."""
        ...

    def close(self) -> None: ...


# --- scripted runtime ------------------------------------------------------- #


@dataclass(slots=True)
class ScriptedSession:
    """A deterministic session that replays scripted boxes.

    The platform's reference detection runtime: dependency-free, exactly
    reproducible, and therefore usable in CI without a GPU or a model file. It is
    what makes the letterbox-inverse tests — the highest-value tests in the
    detection layer — runnable everywhere.
    """

    script: dict[str, Sequence[RawBox]] = field(default_factory=dict)
    default: Sequence[RawBox] = ()
    names: Sequence[str] = ("person", "car")
    calls: int = 0
    fail_after: int = 0
    """Raise on the Nth call onwards, to exercise the failure ladder."""

    stall_after: int = 0
    stall_seconds: float = 0.25
    """Block for ``stall_seconds`` from the Nth call, to exercise the inference
    timeout. Bounded deliberately: a test that sleeps for half a minute to prove
    a timeout works is a test nobody will keep running."""

    closed: bool = False

    def infer(self, images: Sequence[LetterboxedImage]) -> Sequence[Sequence[RawBox]]:
        self.calls += 1
        if self.fail_after and self.calls >= self.fail_after:
            raise RuntimeError("scripted inference failure")
        if self.stall_after and self.calls >= self.stall_after:
            sleep(self.stall_seconds)
        return [self._for(image) for image in images]

    def _for(self, image: LetterboxedImage) -> Sequence[RawBox]:
        key = f"{image.transform.source_width}x{image.transform.source_height}"
        return self.script.get(key, self.default)

    def class_names(self) -> Sequence[str]:
        return self.names

    def close(self) -> None:
        self.closed = True


class ScriptedRuntime:
    """Loads ``ScriptedSession`` instances. The reference P26 adapter."""

    def __init__(
        self,
        *,
        session_factory=None,
        vram_bytes: int = 0,
        warmup_ms: float = 1.0,
    ) -> None:
        self._session_factory = session_factory or (lambda: ScriptedSession())
        self._vram_bytes = vram_bytes
        self._warmup_ms = warmup_ms
        self._lock = threading.Lock()
        self.loaded: list[LoadedModel] = []

    @property
    def runtime_id(self) -> str:
        return "scripted"

    def supports(self, artifact_path: str, precision: str) -> bool:
        return True

    def load(
        self,
        *,
        model_id: str,
        version: str,
        artifact_path: str,
        artifact_hash: str,
        device_id: str,
        precision: str,
        options: dict[str, str] | None = None,
    ) -> LoadedModel:
        session = self._session_factory()
        loaded = LoadedModel(
            model_id=model_id,
            version=version,
            artifact_hash=artifact_hash,
            device_id=device_id,
            precision=precision,
            session=session,
            vram_bytes=self._vram_bytes,
            warmup_ms=self._warmup_ms,
            metadata={"runtime": self.runtime_id},
        )
        with self._lock:
            self.loaded.append(loaded)
        return loaded

    def unload(self, loaded: LoadedModel) -> None:
        session = loaded.session
        if isinstance(session, ScriptedSession):
            session.close()
        with self._lock:
            if loaded in self.loaded:
                self.loaded.remove(loaded)


# --- ultralytics runtime ----------------------------------------------------- #


class UltralyticsSession:
    """Wraps an ultralytics model behind ``DetectorSession``.

    Deliberately thin. Everything that decides whether a box lands in the right
    place lives in the YOLO *adapter*, not here, so the correctness-critical code
    is exercised in CI while this wrapper is the only part that needs a GPU.
    """

    def __init__(self, model, device_id: str, half: bool) -> None:
        self._model = model
        self._device_id = device_id
        self._half = half
        self._lock = threading.Lock()

    def infer(self, images: Sequence[LetterboxedImage]) -> Sequence[Sequence[RawBox]]:
        try:
            import numpy as np  # noqa: PLC0415 - optional, adapter-scoped
        except Exception as exc:  # noqa: BLE001
            raise ModelLoadError("numpy is required by the ultralytics runtime") from exc

        batch = [
            np.frombuffer(image.pixels, dtype=np.uint8).reshape(
                image.height, image.width, 3
            )
            for image in images
        ]
        with self._lock:
            predictions = self._model.predict(
                batch, verbose=False, device=self._device_id, half=self._half
            )

        results: list[list[RawBox]] = []
        for prediction in predictions:
            boxes: list[RawBox] = []
            container = getattr(prediction, "boxes", None)
            if container is not None:
                for row, score, class_index in zip(
                    container.xyxy.tolist(),
                    container.conf.tolist(),
                    container.cls.tolist(),
                    strict=False,
                ):
                    boxes.append(
                        RawBox(
                            x1=float(row[0]),
                            y1=float(row[1]),
                            x2=float(row[2]),
                            y2=float(row[3]),
                            score=float(score),
                            class_index=int(class_index),
                        )
                    )
            results.append(boxes)
        return results

    def class_names(self) -> Sequence[str]:
        names = getattr(self._model, "names", {})
        if isinstance(names, dict):
            return [names[key] for key in sorted(names)]
        return list(names)

    def close(self) -> None:
        self._model = None


class UltralyticsRuntime:
    """Loads YOLO weights through ultralytics.

    The import is deferred to ``load`` so a deployment without ultralytics starts
    normally and simply cannot bind this runtime — an absent optional dependency
    is a capability gap, not a startup failure.
    """

    def __init__(self, *, warmup_enabled: bool = True) -> None:
        self._warmup_enabled = warmup_enabled

    @property
    def runtime_id(self) -> str:
        return "ultralytics"

    def supports(self, artifact_path: str, precision: str) -> bool:
        if precision not in ("fp32", "fp16"):
            return False
        return artifact_path.endswith((".pt", ".pth", ".engine", ".onnx"))

    def load(
        self,
        *,
        model_id: str,
        version: str,
        artifact_path: str,
        artifact_hash: str,
        device_id: str,
        precision: str,
        options: dict[str, str] | None = None,
    ) -> LoadedModel:
        try:
            from ultralytics import YOLO  # noqa: PLC0415 - optional dependency
        except Exception as exc:  # noqa: BLE001
            raise ModelLoadError(
                "the ultralytics runtime is not installed; bind a different "
                "ModelRuntimePort or install the optional dependency",
                model_id=model_id,
            ) from exc

        try:
            model = YOLO(artifact_path)
            if device_id != "cpu":
                model.to(device_id)
        except Exception as exc:  # noqa: BLE001
            raise ModelLoadError(
                f"ultralytics failed to load '{artifact_path}': {exc}",
                model_id=model_id,
            ) from exc

        session = UltralyticsSession(model, device_id, half=precision == "fp16")
        return LoadedModel(
            model_id=model_id,
            version=version,
            artifact_hash=artifact_hash,
            device_id=device_id,
            precision=precision,
            session=session,
            metadata={"runtime": self.runtime_id, "artifact": artifact_path},
        )

    def unload(self, loaded: LoadedModel) -> None:
        session = loaded.session
        if isinstance(session, UltralyticsSession):
            session.close()
