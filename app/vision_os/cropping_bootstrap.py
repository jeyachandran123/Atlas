"""Composition root for Flow 5 — the Crop Manager.

Assembles M8 against an already-built platform and registry. The manager holds
``TriggerPolicyPort``, ``QualityEstimatorPort``, ``CropStrategyPort`` and
``CropExtractorPort``; which implementation satisfies each is decided **only
here**.

Every adapter is run through its conformance kit before use. An adapter that has
not passed its kit is never activated — invariant V3 as a gate rather than an
aspiration (06_PORTS section 5).

**This is also where the seam is wired.** The Crop Runtime attaches to the
Registry Runtime's ``sink``, which the Flow 4 report names as the Flow 5
extension point. Flow 4 remains unaware of the Crop Manager: it holds a callable
and never learns what implements it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .adapters.cropping import (
    CROP_STRATEGY_FACTORIES,
    QUALITY_ESTIMATOR_FACTORIES,
    TRIGGER_POLICY_FACTORIES,
    ReferenceCropExtractor,
)
from .bootstrap import VisionPlatform
from .conformance import CROP_STRATEGY_KIT, QUALITY_ESTIMATOR_KIT, TRIGGER_POLICY_KIT
from .core.errors import CropError
from .core.model.ids import ConfigRevision, ModuleId, ObjectId
from .core.model.provenance import Provenance
from .core.model.timebase import Duration
from .kernel.plugins.manifest import PortCatalogue
from .perception.cropping import (
    CropManager,
    CropRuntime,
    DemandRegistry,
    GateThresholds,
    QualityGate,
    UnderstandingBudget,
)
from .perception.cropping.demands import CapabilityView
from .registry_bootstrap import RegistryLayer

CROPPING_MODULE = ModuleId("crop_manager")
CROPPING_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class CroppingLayer:
    """Everything Flow 5 assembled, for tests and operators to reach into."""

    manager: CropManager
    runtime: CropRuntime
    demands: DemandRegistry
    budget: UnderstandingBudget

    @property
    def policy_id(self) -> str:
        return self.manager._policy.policy_id  # noqa: SLF001 - diagnostic accessor


def build_gate_thresholds(platform: VisionPlatform) -> GateThresholds:
    """Translate configuration into gate thresholds. Pure mapping."""
    settings = platform.config.cropping()
    return GateThresholds(
        min_scale_pixels=settings.min_scale_pixels,
        max_truncation=settings.max_truncation,
        max_occlusion=settings.max_occlusion,
        max_blur=settings.max_blur,
        max_crowding=settings.max_crowding,
        reject_extreme_exposure=settings.reject_extreme_exposure,
    )


def build_trigger_policy(platform: VisionPlatform):
    """Select a trigger policy by name.

    Raises:
        CropError: the configured policy is unknown. Refusing beats defaulting:
            a typo that silently fell back to the default policy would change
            what the platform pays attention to, with no signal.
    """
    settings = platform.config.cropping()
    factory = TRIGGER_POLICY_FACTORIES.get(settings.trigger_policy)
    if factory is None:
        raise CropError(
            f"unknown trigger policy '{settings.trigger_policy}'; known policies "
            f"are {sorted(TRIGGER_POLICY_FACTORIES)}",
            requested=settings.trigger_policy,
        )
    return factory(
        appearance_threshold=settings.appearance_change_threshold,
        low_confidence=settings.low_confidence_threshold,
        refresh_interval=Duration.from_millis(settings.periodic_refresh_ms),
    )


def build_quality_estimator(platform: VisionPlatform):
    settings = platform.config.cropping()
    factory = QUALITY_ESTIMATOR_FACTORIES.get(settings.quality_estimator)
    if factory is None:
        raise CropError(
            f"unknown quality estimator '{settings.quality_estimator}'; known "
            f"estimators are {sorted(QUALITY_ESTIMATOR_FACTORIES)}",
            requested=settings.quality_estimator,
        )
    if factory.__name__ == "AlwaysUsableEstimator":
        return factory()
    return factory(
        min_scale_pixels=settings.min_scale_pixels,
        good_scale_pixels=settings.good_scale_pixels,
        max_blur=settings.max_blur,
        max_truncation=settings.max_truncation,
        max_occlusion=settings.max_occlusion,
    )


def build_crop_strategy(platform: VisionPlatform):
    settings = platform.config.cropping()
    factory = CROP_STRATEGY_FACTORIES.get(settings.crop_strategy)
    if factory is None:
        raise CropError(
            f"unknown crop strategy '{settings.crop_strategy}'; known strategies "
            f"are {sorted(CROP_STRATEGY_FACTORIES)}",
            requested=settings.crop_strategy,
        )
    output_size = (settings.crop_width, settings.crop_height)
    if settings.crop_strategy == "crop.tight":
        return factory(output_size=output_size, preserve_aspect=settings.preserve_aspect)
    return factory(
        padding=settings.crop_padding,
        output_size=output_size,
        preserve_aspect=settings.preserve_aspect,
    )


def build_cropping_layer(
    platform: VisionPlatform,
    registry_layer: RegistryLayer,
    *,
    policy=None,
    estimator=None,
    strategy=None,
    extractor=None,
    capabilities: CapabilityView | None = None,
    crop_sink=None,
    attach: bool = True,
) -> CroppingLayer:
    """Assemble Flow 5 against an already-built platform and registry.

    Args:
        capabilities: What the platform can actually produce. **Empty by
            default**, which is the honest state until Flow 6 binds an
            understander — every demand is admitted and immediately marked
            unsatisfiable with ``NO_CAPABLE_MODEL``, rather than accepted and
            left waiting forever.
        attach: Wire the runtime to the registry's sink. False leaves the layer
            assembled but unconnected, which is what a unit test wants.

    Raises:
        CropError: cropping is disabled, or an adapter failed its conformance kit.
    """
    settings = platform.config.cropping()

    if not settings.enabled:
        raise CropError(
            "cropping.enabled is false; a site that does not want attention "
            "should not build the layer rather than build one that decides "
            "nothing"
        )

    selected_policy = policy or build_trigger_policy(platform)
    selected_estimator = estimator or build_quality_estimator(platform)
    selected_strategy = strategy or build_crop_strategy(platform)
    selected_extractor = extractor or ReferenceCropExtractor(
        interpolation=settings.interpolation
    )

    _gate_adapter(platform, PortCatalogue.TRIGGER_POLICY, TRIGGER_POLICY_KIT, selected_policy)
    _gate_adapter(
        platform, PortCatalogue.QUALITY_ESTIMATOR, QUALITY_ESTIMATOR_KIT, selected_estimator
    )
    _gate_adapter(
        platform, PortCatalogue.CROP_STRATEGY, CROP_STRATEGY_KIT, selected_strategy
    )

    platform_config = platform.config.platform()
    provenance = Provenance(
        producer_module=CROPPING_MODULE,
        producer_version=CROPPING_VERSION,
        config_revision=ConfigRevision(str(platform.config.revision())),
        deterministic=platform_config.deterministic,
    )

    demands = DemandRegistry(capabilities=capabilities or CapabilityView())
    budget = UnderstandingBudget(
        ceiling_per_hour=settings.understanding_calls_per_hour,
        window=Duration.from_millis(settings.budget_window_ms),
        now=platform.clock.monotonic(),
    )

    manager = CropManager(
        clock=platform.clock,
        metrics=platform.metrics,
        events=platform.bus,
        config=settings,
        policy=selected_policy,
        estimator=selected_estimator,
        strategy=selected_strategy,
        extractor=selected_extractor,
        provenance=provenance,
        demands=demands,
        budget=budget,
        gate=QualityGate(build_gate_thresholds(platform)),
    )

    runtime = CropRuntime(
        clock=platform.clock,
        metrics=platform.metrics,
        health=platform.health,
        manager=manager,
        config=settings,
        buffer=platform.buffer,
        sink=crop_sink,
        regions_of=_region_lookup(registry_layer),
    )

    if attach:
        _attach(registry_layer, runtime)

    return CroppingLayer(
        manager=manager, runtime=runtime, demands=demands, budget=budget
    )


def _gate_adapter(platform: VisionPlatform, port, kit, adapter) -> None:
    """Run an adapter's conformance kit before it is ever used.

    The registered kit wins over the shipped one when a deployment has
    registered its own — but *some* kit must run. An adapter activated without a
    kit is invariant V3 reduced to a claim in a document.
    """
    registered = platform.conformance.get(port)
    effective = registered or kit
    report = effective.run(adapter, fast_only=True)
    if not report.passed:
        raise CropError(
            f"adapter for {port} failed conformance: {'; '.join(report.failures)}",
            port=str(port),
        )


def _region_lookup(registry_layer: RegistryLayer):
    """Region membership, read from M7 rather than recomputed.

    M7 owns region membership (§M7 State Ownership). Recomputing it here would
    create a second answer to "is this object in that region", and the two would
    disagree the moment geometry was reloaded.
    """

    def lookup(object_id: ObjectId) -> frozenset:
        for camera_id in registry_layer.registry.partitions:
            tracker = registry_layer.registry.region_tracker(camera_id)
            if tracker is None:
                continue
            membership = tracker.membership(object_id)
            if membership:
                return frozenset(membership)
        return frozenset()

    return lookup


def _attach(registry_layer: RegistryLayer, runtime: CropRuntime) -> None:
    """Wire the crop runtime to the registry's declared extension point.

    The registry's sink is synchronous while ``on_registered`` is a coroutine, so
    the update is scheduled rather than awaited. That is deliberate: making the
    registry await attention would put the cheapest layer's latency on the
    critical path of the layer beneath it, and V9 says a failure at L3 may not
    stop L2.
    """
    import asyncio

    existing = getattr(registry_layer.runtime, "_sink", None)

    def sink(update) -> None:
        if existing is not None:
            existing(update)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No loop — a synchronous test harness. Run to completion so the
            # update is not silently dropped.
            asyncio.run(runtime.on_registered(update))
            return
        loop.create_task(runtime.on_registered(update))

    registry_layer.runtime._sink = sink  # noqa: SLF001 - the declared seam
