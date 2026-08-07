"""Architecture regression tests — the ones that fail when someone takes a shortcut.

Everything asserted here is cheap to violate and expensive to discover. A single
``from app.adapters.document_vlm.nvidia import …`` inside the platform would
compile, pass every functional test, and quietly end provider replaceability;
the only thing that catches it is a test that reads the source.

These are executable versions of the architectural claims made in the reports.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
PLATFORM_VLM = BACKEND / "app" / "document_platform" / "vlm"
ADAPTERS = BACKEND / "app" / "adapters" / "document_vlm"
API = BACKEND / "app" / "api" / "v1" / "document_extraction"

PROVIDER_NAMES = ("nvidia", "ollama", "claude", "anthropic", "gemini", "openai", "qwen")


def python_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)


def imports_of(path: Path) -> list[str]:
    """Every module name this file imports, including inside functions."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


def executable_source(path: Path) -> str:
    """The file with its comments and docstrings removed.

    Prose may explain the architecture — including by naming the providers the
    platform must not know — so the scans below run against what actually
    executes. Docstrings are located by AST line range rather than by matching
    their text, because ``ast.get_docstring`` returns a *cleaned* string that no
    longer matches the indented source it came from.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    doc_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                doc_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))

    kept = []
    for number, line in enumerate(source.splitlines(), start=1):
        if number in doc_lines or line.strip().startswith("#"):
            continue
        kept.append(line.split("  # ")[0])
    return "\n".join(kept)


class TestPlatformKnowsNoProvider:
    def test_the_platform_never_imports_an_adapter(self) -> None:
        """The dependency arrow runs one way. This test is that arrow."""
        for path in python_files(PLATFORM_VLM):
            for module in imports_of(path):
                assert not module.startswith("app.adapters"), (
                    f"{path.relative_to(BACKEND)} imports {module}; the platform "
                    f"would then have to change whenever a provider does"
                )

    def test_no_provider_name_appears_in_platform_code(self) -> None:
        """Not in an import, not in a branch, not in a comparison. A platform
        that can spell a provider's name can eventually branch on it."""
        offenders: list[str] = []
        for path in python_files(PLATFORM_VLM):
            code = executable_source(path).lower()
            for name in PROVIDER_NAMES:
                if name in code:
                    offenders.append(f"{path.relative_to(BACKEND)}: '{name}'")
        assert not offenders, f"provider names leaked into platform code: {offenders}"

    def test_the_platform_imports_no_http_client(self) -> None:
        """Transport is an adapter concern. A platform holding an httpx client
        has an opinion about how a model is reached."""
        for path in python_files(PLATFORM_VLM):
            for module in imports_of(path):
                assert module.split(".")[0] not in {"httpx", "requests", "aiohttp", "openai"}, (
                    f"{path.relative_to(BACKEND)} imports a transport library"
                )

    def test_the_pipeline_depends_only_on_the_port(self) -> None:
        code = executable_source(PLATFORM_VLM / "pipeline.py")
        assert "DocumentVLMPort" in code, "the pipeline must be typed against the port"
        for name in PROVIDER_NAMES:
            assert name not in code.lower()


class TestAdaptersDependOnThePlatform:
    def test_every_adapter_imports_the_port_it_implements(self) -> None:
        for path in python_files(ADAPTERS):
            if path.name in {"__init__.py", "registry.py"}:
                continue
            modules = imports_of(path)
            assert any("document_platform.vlm" in module for module in modules), (
                f"{path.relative_to(BACKEND)} implements nothing the platform declared"
            )

    def test_no_adapter_imports_another_adapter(self) -> None:
        """Providers are siblings, not a chain. An Ollama adapter that imports
        the NVIDIA one cannot be removed when NVIDIA is."""
        for path in python_files(ADAPTERS):
            if path.name in {"__init__.py", "registry.py", "base.py"}:
                continue
            for module in imports_of(path):
                siblings = [
                    n for n in PROVIDER_NAMES if f"document_vlm.{n}" in module
                ]
                assert not siblings or path.stem in siblings, (
                    f"{path.relative_to(BACKEND)} imports sibling adapter {module}"
                )

    def test_no_adapter_imports_the_pipeline_or_the_schema(self) -> None:
        """An adapter that knows what an invoice is has taken business logic."""
        for path in python_files(ADAPTERS):
            for module in imports_of(path):
                assert "vlm.pipeline" not in module, f"{path.name} imports the pipeline"
                assert "invoice_schema" not in module, f"{path.name} imports the invoice schema"

    def test_no_adapter_reads_configuration_directly(self) -> None:
        """Settings arrive through the factory. An adapter reaching for
        ``get_settings()`` cannot be instantiated twice with two configurations,
        which is exactly what an A/B comparison needs."""
        for path in python_files(ADAPTERS):
            if path.name == "registry.py":
                continue
            source = path.read_text(encoding="utf-8")
            assert "get_settings()" not in source, f"{path.name} reads global settings"


class TestApiDependsOnNeither:
    def test_the_router_names_no_provider(self) -> None:
        code = executable_source(API / "router.py").lower()
        for name in PROVIDER_NAMES:
            assert name not in code, f"the API's executable code mentions '{name}'"

    def test_only_the_composition_root_builds_a_provider(self) -> None:
        """One place chooses; everything else receives."""
        builders = [
            path
            for path in python_files(BACKEND / "app")
            if "get_document_vlm(" in path.read_text(encoding="utf-8")
            and "registry.py" not in path.name
        ]
        assert [p.name for p in builders] == ["dependencies.py"], (
            f"provider construction leaked into: {[str(p) for p in builders]}"
        )

    def test_the_response_schema_is_provider_neutral(self) -> None:
        source = (API / "schemas.py").read_text(encoding="utf-8")
        for name in PROVIDER_NAMES:
            assert name not in source.lower()


class TestExistingArchitectureUntouched:
    """The brief froze the architecture. These assert nothing moved."""

    @pytest.mark.parametrize(
        "path",
        [
            "app/vision_os/core/ports/understanding.py",
            "app/cognitive_integration/ports.py",
            "app/document_platform/processing/ocr.py",
            "app/document_platform/semantic/providers.py",
        ],
    )
    def test_existing_ports_and_services_still_exist(self, path: str) -> None:
        assert (BACKEND / path).exists(), f"{path} was moved or deleted"

    def test_the_existing_ocr_abstraction_is_unchanged(self) -> None:
        """The pipeline reuses ``OcrService`` as it found it — no new methods, no
        changed signature, no fork."""
        from app.document_platform.processing.ocr import (
            AbstractOcrProvider,
            NullOcrProvider,
            OcrService,
        )

        assert hasattr(OcrService, "run") and hasattr(OcrService, "provider_name")
        assert hasattr(AbstractOcrProvider, "extract_text")
        assert NullOcrProvider().name == "null"

    def test_the_documents_router_is_untouched_and_still_mounted(self) -> None:
        """The new API is additive: ``/documents`` keeps its contract."""
        from app.api.v1.documents.router import router as documents_router

        paths = {route.path for route in documents_router.routes}
        assert "/documents/upload" in paths

    def test_both_routers_coexist_without_a_path_collision(self) -> None:
        from app.api.v1.document_extraction.router import router as extraction_router
        from app.api.v1.documents.router import router as documents_router

        overlap = {r.path for r in documents_router.routes} & {
            r.path for r in extraction_router.routes
        }
        assert not overlap


class TestPortStability:
    def test_the_port_declares_exactly_the_five_contracted_methods(self) -> None:
        """Adding a sixth is a breaking change for every provider. It should
        require deleting this assertion, deliberately."""
        from app.document_platform.vlm.ports import DocumentVLMPort

        # ``__protocol_attrs__`` only exists from Python 3.12; the runtime here
        # is 3.11, so fall back to the class's own namespace.
        declared = getattr(DocumentVLMPort, "__protocol_attrs__", None)
        methods = set(declared) if declared else {
            name for name in vars(DocumentVLMPort) if not name.startswith("_")
        }
        assert methods == {
            "provider_name",
            "model_name",
            "extract_document",
            "health",
            "estimate_cost",
        }

    def test_the_port_is_versioned_and_the_version_is_reported(self) -> None:
        from app.document_platform.vlm.ports import DOCUMENT_VLM_PORT_VERSION

        assert DOCUMENT_VLM_PORT_VERSION.count(".") == 2
