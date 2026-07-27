"""Kernel Bootstrapper — the boot sequence.

Boots the kernel like an operating system, in a fixed, observable order:

    Load Configuration → Validate Constitution → Initialize Runtime →
    Initialize Event Bus → Initialize Ledger → Initialize Scheduler →
    Initialize Identity → Initialize Capability Registry →
    Initialize Engine Registry → Initialize Health Monitor → Ready

The sequence **fails safely**: any step's failure triggers a clean rollback of
whatever was partially initialized and transitions the kernel to ``FAILED``.
Nothing self-initializes; the bootstrapper drives every step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import contracts as C
from .errors import BootstrapError
from .kernel import CognitiveKernel, KernelConfig


@dataclass(frozen=True, slots=True)
class BootStep:
    name: str
    run: Callable[[CognitiveKernel], None]


class Bootstrapper:
    """Constructs and boots a :class:`CognitiveKernel`."""

    def boot(self, config: KernelConfig) -> CognitiveKernel:
        kernel = CognitiveKernel(config)
        log = kernel.observability.logger("bootstrap")

        # The ordered boot sequence. Each step is named for observability.
        steps: list[BootStep] = [
            BootStep("load_configuration", self._load_configuration),
            BootStep("validate_constitution", self._validate_constitution),
            BootStep("initialize_runtime", self._initialize_runtime),
            BootStep("initialize_event_bus", self._initialize_event_bus),
            BootStep("initialize_ledger", self._initialize_ledger),
            BootStep("initialize_scheduler", self._initialize_scheduler),
            BootStep("initialize_identity", self._initialize_identity),
            BootStep("initialize_capability_registry", self._initialize_capabilities),
            BootStep("initialize_engine_registry", self._initialize_engine_registry),
            BootStep("initialize_health_monitor", self._initialize_health_monitor),
            BootStep("ready", self._ready),
        ]

        completed: list[str] = []
        try:
            for step in steps:
                kernel.observability.counter("boot.step", step=step.name)
                log.info("boot step", step=step.name)
                step.run(kernel)
                completed.append(step.name)
            log.info("kernel ready", state=kernel.state.value)
            return kernel
        except Exception as exc:
            log.error("boot failed", failed_after=completed[-1] if completed else "<none>", error=repr(exc))
            self._rollback(kernel)
            raise BootstrapError(
                f"Boot failed after steps {completed!r}: {exc!r}"
            ) from exc

    # --- steps ------------------------------------------------------------ #

    def _load_configuration(self, kernel: CognitiveKernel) -> None:
        cfg = kernel._config  # noqa: SLF001 - bootstrapper is the kernel's builder
        if not cfg.identity_name:
            raise ValueError("identity_name is required")

    def _validate_constitution(self, kernel: CognitiveKernel) -> None:
        # Register infra early enough to read the (read-only) constitution.
        kernel.register_infrastructure()
        registry = kernel.container.resolve(C.ConstitutionRegistry)
        version = registry.version()
        if version.law_count <= 0:
            raise ValueError("Constitution is empty; refusing to boot.")

    def _initialize_runtime(self, kernel: CognitiveKernel) -> None:
        kernel.lifecycle.transition(C.KernelState.INITIALIZING)
        kernel.build_services()

    def _initialize_event_bus(self, kernel: CognitiveKernel) -> None:
        _ = kernel.services().events  # resolved; verify presence

    def _initialize_ledger(self, kernel: CognitiveKernel) -> None:
        ledger = kernel.services().ledger
        if not ledger.verify():  # empty chain must verify
            raise RuntimeError("Fresh ledger failed integrity verification.")

    def _initialize_scheduler(self, kernel: CognitiveKernel) -> None:
        _ = kernel.services().scheduler

    def _initialize_identity(self, kernel: CognitiveKernel) -> None:
        kernel.establish_identity()

    def _initialize_capabilities(self, kernel: CognitiveKernel) -> None:
        # Discover faculties from the existing platforms (empty by default; the
        # real Capability Registry integrates via KernelCapabilityRegistry's seam).
        _ = kernel.services().capabilities.discover()

    def _initialize_engine_registry(self, kernel: CognitiveKernel) -> None:
        _ = kernel.engine_registry()
        kernel.wire_ledger_bridge()

    def _initialize_health_monitor(self, kernel: CognitiveKernel) -> None:
        kernel.register_health_probes()
        _ = kernel.services().health.overall()

    def _ready(self, kernel: CognitiveKernel) -> None:
        kernel.lifecycle.transition(C.KernelState.STARTING)
        if kernel._config.run_scheduler_thread:  # noqa: SLF001
            kernel.services().scheduler.start()
        kernel.start_engines()  # zero engines this phase → no-op
        kernel.lifecycle.transition(C.KernelState.RUNNING)

    # --- rollback --------------------------------------------------------- #

    def _rollback(self, kernel: CognitiveKernel) -> None:
        try:
            # Best-effort cleanup of anything partially started.
            if kernel._services is not None:  # noqa: SLF001
                try:
                    kernel._services.scheduler.stop()  # noqa: SLF001
                except Exception:
                    pass
            # Transition to FAILED from wherever we are (all states allow it,
            # except terminal ones which we leave as-is).
            if kernel.lifecycle.can_transition(C.KernelState.FAILED):
                kernel.lifecycle.transition(C.KernelState.FAILED)
        except Exception:
            pass


def boot(config: KernelConfig) -> CognitiveKernel:
    """Convenience: boot a kernel with the default bootstrapper."""
    return Bootstrapper().boot(config)
