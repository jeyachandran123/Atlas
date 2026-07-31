"""Architecture boundary tests — the invariants, enforced mechanically.

An invariant with no test is a slogan (14_TESTING §11). These tests read the
source tree and fail the build when a boundary is crossed, so the constitution is
defended by CI rather than by memory.

The most valuable test here is ``test_no_domain_vocabulary_in_platform_code``.
It is crude on purpose: it catches the *first* leak, which is the one that
establishes precedent. Every general vision platform that became a vertical
product did so through a series of individually reasonable exceptions.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import app.vision_os as vision_os_pkg
from app.vision_os.kernel.config.schema import ALLOWED_TOP_LEVEL, SECTION_TYPES, allowed_keys
from app.vision_os.kernel.plugins.manifest import FLOW1_PORTS

ROOT = Path(vision_os_pkg.__file__).parent

CORE = ROOT / "core"
KERNEL = ROOT / "kernel"
ACQUISITION = ROOT / "acquisition"
ADAPTERS = ROOT / "adapters"
CONFORMANCE = ROOT / "conformance"


def _python_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)


def _module_of(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append("." * node.level + (node.module or ""))
            elif node.module:
                found.append(node.module)
    return found


# --- V3: ports over implementations ------------------------------------------ #

STDLIB_ALLOWED = {
    "__future__", "abc", "ast", "asyncio", "collections", "collections.abc",
    "contextlib", "dataclasses", "datetime", "enum", "functools", "hashlib",
    "heapq", "itertools", "json", "math", "os", "pathlib", "random", "re",
    "secrets", "tempfile", "threading", "time", "typing", "uuid", "weakref",
}

THIRD_PARTY_MARKERS = (
    "numpy", "cv2", "torch", "tensorflow", "onnx", "ultralytics", "PIL",
    "redis", "sqlalchemy", "fastapi", "pydantic", "psycopg", "kafka",
    "prometheus_client", "boto3", "requests", "httpx", "aiohttp", "chromadb",
    "langchain", "transformers", "tensorrt", "pycuda",
)


class TestCoreIsPure:
    """``core`` is contracts only: stdlib-only, no I/O, no vendor knowledge."""

    def test_core_imports_no_third_party_packages(self) -> None:
        offenders: list[str] = []
        for path in _python_files(CORE):
            for imported in _imports(path):
                root = imported.split(".")[0]
                if root in THIRD_PARTY_MARKERS:
                    offenders.append(f"{_module_of(path)} imports {imported}")
        assert not offenders, (
            "core must be stdlib-only so the platform never depends on a vendor:\n"
            + "\n".join(offenders)
        )

    def test_core_imports_only_stdlib_and_itself(self) -> None:
        offenders: list[str] = []
        for path in _python_files(CORE):
            for imported in _imports(path):
                if imported.startswith("."):
                    continue
                root = imported.split(".")[0]
                if root in STDLIB_ALLOWED:
                    continue
                offenders.append(f"{_module_of(path)} imports {imported}")
        assert not offenders, "unexpected core dependency:\n" + "\n".join(offenders)

    def test_core_does_not_import_kernel_or_layers(self) -> None:
        """Contracts may not depend on the machinery that implements them."""
        offenders: list[str] = []
        for path in _python_files(CORE):
            text = path.read_text(encoding="utf-8")
            for forbidden in ("vision_os.kernel", "vision_os.acquisition", "vision_os.adapters"):
                if forbidden in text:
                    offenders.append(f"{_module_of(path)} references {forbidden}")
        assert not offenders, "\n".join(offenders)


class TestNoExternalTechnologyInPlatform:
    def test_only_adapters_may_touch_external_technology(self) -> None:
        """External technology never enters the core (invariant V3).

        Detectors, codecs, databases and queues live behind ports. Today no
        adapter needs a third-party package either — the Flow 1 reference set is
        dependency-free — but the boundary is enforced now so it holds when
        NVDEC and RTSP arrive.
        """
        offenders: list[str] = []
        for directory in (CORE, KERNEL, ACQUISITION, CONFORMANCE):
            for path in _python_files(directory):
                for imported in _imports(path):
                    root = imported.split(".")[0]
                    if root in THIRD_PARTY_MARKERS:
                        offenders.append(f"{_module_of(path)} imports {imported}")
        assert not offenders, (
            "external technology must live behind an adapter:\n" + "\n".join(offenders)
        )


class TestLayerDependencyLaw:
    """Flow layers depend downward only; the kernel depends on none of them."""

    def test_kernel_never_imports_a_flow_layer(self) -> None:
        """The kernel law: no L0 module knows what a frame is.

        This is what allows the kernel to be reused unchanged by a future
        UnityWorks Audio OS, and what stops L0 becoming the place where layering
        rules go to die.
        """
        offenders: list[str] = []
        for path in _python_files(KERNEL):
            for imported in _imports(path):
                if "acquisition" in imported or "adapters" in imported:
                    offenders.append(f"{_module_of(path)} imports {imported}")
        assert not offenders, (
            "kernel must not depend on a flow layer:\n" + "\n".join(offenders)
        )

    def test_acquisition_never_imports_adapters(self) -> None:
        """A module that names a concrete adapter has bypassed its port."""
        offenders: list[str] = []
        for path in _python_files(ACQUISITION):
            for imported in _imports(path):
                if "adapters" in imported:
                    offenders.append(f"{_module_of(path)} imports {imported}")
        assert not offenders, "\n".join(offenders)

    def test_platform_modules_do_not_name_concrete_adapters(self) -> None:
        concrete = (
            "HostMemoryPool", "InMemoryRawSource", "PassthroughDecoder",
            "CadenceAdmissionPolicy", "StaticZoneMask", "JsonFileConfigSource",
            "NullEventTransport", "SampledDigestChangeDetector",
        )
        offenders: list[str] = []
        for directory in (CORE, KERNEL, ACQUISITION):
            for path in _python_files(directory):
                text = path.read_text(encoding="utf-8")
                for name in concrete:
                    if name in text:
                        offenders.append(f"{_module_of(path)} names {name}")
        assert not offenders, (
            "platform modules must reference ports, never adapters:\n" + "\n".join(offenders)
        )


class TestInjectedClock:
    """Invariant V13 — a module that reads the system clock can never be replayed."""

    def test_no_module_reads_the_wall_clock_directly(self) -> None:
        pattern = re.compile(r"\btime\.(time|time_ns|monotonic|monotonic_ns)\s*\(")
        allowed = {"kernel/clock.py", "core/model/ids.py"}
        offenders: list[str] = []
        for directory in (CORE, KERNEL, ACQUISITION, ADAPTERS):
            for path in _python_files(directory):
                module = _module_of(path)
                if module in allowed:
                    continue
                if pattern.search(path.read_text(encoding="utf-8")):
                    offenders.append(module)
        assert not offenders, (
            "time must be injected, not read (invariant V13):\n" + "\n".join(offenders)
        )

    def test_no_module_calls_datetime_now(self) -> None:
        offenders: list[str] = []
        for directory in (CORE, KERNEL, ACQUISITION, ADAPTERS):
            for path in _python_files(directory):
                text = path.read_text(encoding="utf-8")
                if "datetime.now(" in text or "datetime.utcnow(" in text:
                    offenders.append(_module_of(path))
        assert not offenders, "\n".join(offenders)


class TestDependencyInjection:
    """No global state, no hidden singletons, no service locators."""

    def test_no_module_level_mutable_singletons(self) -> None:
        offenders: list[str] = []
        for directory in (KERNEL, ACQUISITION):
            for path in _python_files(directory):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in tree.body:
                    if not isinstance(node, ast.Assign):
                        continue
                    for target in node.targets:
                        if not isinstance(target, ast.Name) or target.id.startswith("_"):
                            continue
                        if target.id.isupper():
                            continue  # module constants are fine
                        if isinstance(node.value, ast.Dict | ast.List | ast.Set | ast.Call):
                            offenders.append(f"{_module_of(path)}::{target.id}")
        assert not offenders, (
            "mutable module-level state is a hidden singleton:\n" + "\n".join(offenders)
        )

    def test_every_module_takes_its_collaborators_by_constructor(self) -> None:
        import inspect

        from app.vision_os.acquisition import (
            CameraManager,
            FrameBuffer,
            FrameScheduler,
            VideoSourceManager,
        )
        from app.vision_os.kernel.config import ConfigurationManager
        from app.vision_os.kernel.events import EventBus
        from app.vision_os.kernel.health import HealthMonitor
        from app.vision_os.kernel.metrics import MetricsEngine
        from app.vision_os.kernel.plugins import PluginManager
        from app.vision_os.kernel.runtime import VisionRuntime

        for cls in (
            CameraManager, FrameBuffer, FrameScheduler, VideoSourceManager,
            ConfigurationManager, EventBus, HealthMonitor, MetricsEngine,
            PluginManager, VisionRuntime,
        ):
            signature = inspect.signature(cls.__init__)
            parameters = [p for p in signature.parameters if p != "self"]
            assert parameters, f"{cls.__name__} must receive dependencies by constructor"


# --- V1 / V2: the semantic ceiling and vertical neutrality --------------------- #

#: Terms that may never appear as an identifier token in platform code.
#:
#: Deliberately restricted to vocabulary with **no legitimate engineering
#: meaning**, so the guard has no false positives and therefore never gets
#: disabled. Words like "violation" (schema validation) and "factory" (the
#: construction pattern) are excluded precisely because they are ambiguous —
#: the real ceiling enforcement is the closed config schema here, and the
#: attribute registry in Flow 5.
DOMAIN_VOCABULARY = (
    # roles a crop cannot evidence
    "waiter", "chef", "cashier", "patient", "nurse", "doctor", "customer",
    "employee", "shopper", "clerk",
    # verticals
    "restaurant", "kitchen", "hospital", "warehouse", "retail", "clinic",
    # vertical objects
    "biryani", "menu", "checkout", "shelf", "till",
    # judgments and conclusions
    "unproductive", "suspicious", "loitering", "shoplifting", "anomaly",
    "alert", "unauthorized", "noncompliant", "infraction",
)

_TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+")


def _tokens(identifier: str) -> set[str]:
    """Split an identifier into lowercase word tokens.

    Whole-token matching rather than substring, so ``_sleepers`` does not trip
    on "sleep" and ``violations`` does not trip on a business "violation".
    """
    return {token.lower() for token in _TOKEN.findall(identifier)}


class TestSemanticCeiling:
    """Invariant V1/V2 — the platform reports what is visible, never what it means."""

    def test_no_domain_vocabulary_in_platform_code(self) -> None:
        """Catches the first leak, which is the one that sets precedent.

        Crude, and effective. Docstrings are excluded from the scan below only
        where they *explain* the prohibition; identifiers never may.
        """
        offenders: list[str] = []
        for directory in (CORE, KERNEL, ACQUISITION):
            for path in _python_files(directory):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    name = None
                    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                        name = node.name
                    elif isinstance(node, ast.Name):
                        name = node.id
                    elif isinstance(node, ast.arg):
                        name = node.arg
                    elif isinstance(node, ast.Attribute):
                        name = node.attr
                    if not name:
                        continue
                    leaked = _tokens(name) & set(DOMAIN_VOCABULARY)
                    if leaked:
                        offenders.append(
                            f"{_module_of(path)}::{name} uses {sorted(leaked)}"
                        )
        assert not offenders, (
            "domain knowledge has leaked into the platform (V1/V2):\n" + "\n".join(offenders)
        )

    def test_config_schema_is_closed(self) -> None:
        """A vertical enters as data through four channels, never as a rule."""
        assert ALLOWED_TOP_LEVEL == frozenset(SECTION_TYPES) | {
            "profiles", "regions", "cameras"
        }

    def test_no_config_section_admits_a_business_threshold(self) -> None:
        forbidden = ("rule", "alert", "threshold_seconds", "policy_action", "violation")
        offenders: list[str] = []
        for section in SECTION_TYPES:
            for key in allowed_keys(section):
                for term in forbidden:
                    if term in key.lower():
                        offenders.append(f"{section}.{key}")
        assert not offenders, "\n".join(offenders)

    def test_region_carries_geometry_and_an_opaque_label_only(self) -> None:
        from app.vision_os.core.model.region import Region

        fields = set(Region.__dataclass_fields__)
        assert fields == {
            "region_id", "geometry", "frame_of_reference", "label", "camera_id", "version"
        }, "a Region must never acquire a semantic field such as zone_type or purpose"


class TestFlowScope:
    """Flow 1 must not implement responsibilities belonging to later flows."""

    def test_only_flow1_ports_are_bindable(self) -> None:
        assert len(FLOW1_PORTS) == 11
        later_flow_ports = {"P8.DetectorPort", "P9.TrackerPort", "P15.UnderstanderPort"}
        assert not (later_flow_ports & set(FLOW1_PORTS))

    def test_no_later_flow_object_kinds_exist(self) -> None:
        """Detection, Track, Crop, Attribute, Observation belong to Flows 2-6."""
        import app.vision_os.core.model as model

        for absent in (
            "Detection", "Track", "VisualObject", "Crop", "Attribute",
            "Observation", "Evidence", "VisionState",
        ):
            assert not hasattr(model, absent), (
                f"{absent} belongs to a later flow and must not exist in Flow 1"
            )

    def test_no_later_flow_modules_exist(self) -> None:
        for absent in ("detection", "tracking", "understanding", "state", "api", "observation"):
            assert not (ROOT / absent).exists(), (
                f"package '{absent}' belongs to a later flow"
            )

    def test_model_manager_is_deferred_to_flow_2(self) -> None:
        """M18's first consumer is the Detection Engine; building it now is speculative."""
        assert not (KERNEL / "models").exists()

    def test_no_observation_types_are_emitted(self) -> None:
        """Coverage *observations* are the Observation Builder's job (Flow 6).

        Flow 1 produces observability state and events only.
        """
        offenders: list[str] = []
        for directory in (KERNEL, ACQUISITION):
            for path in _python_files(directory):
                text = path.read_text(encoding="utf-8")
                if "build_coverage" in text or "ObservationBuilder" in text:
                    offenders.append(_module_of(path))
        assert not offenders, "\n".join(offenders)


class TestSecretHygiene:
    def test_no_hardcoded_credentials_in_platform_code(self) -> None:
        pattern = re.compile(r"(password|passwd|secret_key|api_key)\s*=\s*[\"'][^\"']+[\"']")
        offenders: list[str] = []
        for directory in (CORE, KERNEL, ACQUISITION, ADAPTERS):
            for path in _python_files(directory):
                if pattern.search(path.read_text(encoding="utf-8")):
                    offenders.append(_module_of(path))
        assert not offenders, "\n".join(offenders)


class TestBoundedByConstruction:
    def test_no_unbounded_queue_constructs(self) -> None:
        """An unbounded queue is a memory leak with a delayed fuse."""
        offenders: list[str] = []
        for directory in (KERNEL, ACQUISITION):
            for path in _python_files(directory):
                text = path.read_text(encoding="utf-8")
                if "asyncio.Queue()" in text or "Queue(maxsize=0)" in text:
                    offenders.append(_module_of(path))
        assert not offenders, (
            "queues must be bounded with a declared overflow policy:\n" + "\n".join(offenders)
        )


@pytest.mark.parametrize(
    "package",
    ["core", "kernel", "acquisition", "adapters", "conformance"],
)
def test_every_package_has_a_module_docstring(package: str) -> None:
    """A module still understandable after five years starts with why it exists."""
    missing: list[str] = []
    for path in _python_files(ROOT / package):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if not ast.get_docstring(tree):
            missing.append(_module_of(path))
    assert not missing, "missing module docstrings:\n" + "\n".join(missing)
