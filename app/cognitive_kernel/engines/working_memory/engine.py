"""The Working Memory Engine — the bounded conscious workspace.

The first true cognitive engine. It maintains a bounded, dynamic workspace of
*references* (never copies) with ephemeral activation. It reads/writes only
through the Cognitive State Manager (R4), executes through the Runtime, and
communicates through the Event Bus. It performs NO selection (Attention), NO
reasoning (Reasoning), NO learning/prediction/executive decisions — it exposes
hooks those future engines drive.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Mapping, Sequence

from ...contracts import (
    CognitiveEngine,
    CognitiveEvent,
    EngineMetadata,
    EventPriority,
    ExecutionContext,
    HealthReport,
    HealthStatus,
    KernelServices,
)
from ...state import CognitiveStateManager, ObjectStatus, Region
from ...state.contracts import RelationshipEdge, RelationshipType
from .capacity import select_eviction_victim
from .contracts import (
    Slot,
    WMConfig,
    WMHealthReport,
    WMMetricsSnapshot,
    WMSnapshot,
    WorkspaceKind,
    Zone,
)
from .activation import refreshed_activation
from .errors import (
    MissingTargetError,
    UnknownOperationError,
    WorkingMemorySecurityError,
)
from .refs import WM_REF_TYPE, activation_edge, build_payload, to_slot
from .workspace import WorkspaceRegistry


class WorkingMemoryEngine(CognitiveEngine):
    ENGINE_NAME = "working_memory"

    def __init__(
        self,
        services: KernelServices,
        state_manager: CognitiveStateManager,
        config: WMConfig | None = None,
    ) -> None:
        self._services = services
        self._state = state_manager
        self._config = config or WMConfig()
        self._workspaces = WorkspaceRegistry()
        self._lock = threading.RLock()
        self._started = False
        self._root = ""
        # metrics
        self._loads = self._evictions = self._overflow_evictions = 0
        self._refreshes = self._chunks = self._consolidations = 0
        self._context_switches = self._simulations = 0

    # --- kernel CognitiveEngine lifecycle -------------------------------- #

    @property
    def metadata(self) -> EngineMetadata:
        return EngineMetadata(name=self.ENGINE_NAME, version="1.0", provides=("working_memory",))

    def initialize(self, services: KernelServices) -> None:  # DI (already injected)
        self._services = services

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._root = self._workspaces.create(WorkspaceKind.ROOT, None, False, self._services.clock.current())
            self._active = self._root
            self._started = True

    def stop(self) -> None:
        with self._lock:
            self._started = False

    def health(self) -> HealthReport:
        return self._health_probe()

    def register(self, kernel, runtime) -> None:
        """Register with the Kernel (discoverable) and the Runtime (executable)."""
        kernel.register_engine(self.metadata, lambda services: self)
        runtime.register_engine(self.ENGINE_NAME, self)
        self._services.health.register_probe("working_memory", self._health_probe)
        self.start()

    # --- runtime ExecutableEngine ---------------------------------------- #

    def execute(self, operation: str, payload: Mapping[str, Any], context: ExecutionContext) -> Any:
        p = payload
        if operation == "load":
            return self.load(
                p["target"], context, workspace=p.get("workspace"),
                activation=p.get("activation", 1.0), salience=p.get("salience", 0.0),
                confidence=p.get("confidence"), provenance=p.get("provenance", ""),
                zone=Zone(p.get("zone", "focus")), pinned=p.get("pinned", False),
            )
        if operation == "refresh":
            return self.refresh(p["ref"], context, boost=p.get("boost"))
        if operation == "evict":
            return self.evict(p["ref"], context)
        if operation == "pin":
            return self.pin(p["ref"], context, pinned=p.get("pinned", True))
        if operation == "chunk":
            return self.chunk(list(p["members"]), context, workspace=p.get("workspace"), provenance=p.get("provenance", ""))
        if operation == "consolidate":
            return self.consolidation_candidates(p.get("workspace"), p.get("threshold", 0.5))
        if operation == "expire":
            return self.expire(context, threshold=p.get("threshold"))
        if operation == "broadcast":
            return [s.handle for s in self.broadcast(p.get("workspace"), context)]
        if operation == "open_workspace":
            return self.open_workspace(WorkspaceKind(p.get("kind", "nested")), context, parent=p.get("parent"), isolated=p.get("isolated", False))
        if operation == "close_workspace":
            return self.close_workspace(p["workspace"], context)
        if operation == "switch_workspace":
            return self.switch_workspace(p["workspace"])
        if operation == "branch_simulation":
            return self.branch_simulation(p["base"], context)
        if operation == "discard_simulation":
            return self.discard_simulation(p["workspace"], context)
        raise UnknownOperationError(f"Unknown WM operation: {operation!r}")

    # --- reference lifecycle (loading / refresh / eviction) -------------- #

    def load(
        self,
        target: str,
        context: ExecutionContext,
        *,
        workspace: str | None = None,
        activation: float = 1.0,
        salience: float = 0.0,
        confidence: float | None = None,
        provenance: str = "",
        zone: Zone = Zone.FOCUS,
        pinned: bool = False,
    ) -> str:
        with self._lock:
            ws = workspace or self._active
            self._workspaces.get(ws)  # raises if unknown
            if not self._state.exists(target):
                raise MissingTargetError(f"Cannot activate reference to missing object: {target}")
            now = self._services.clock.current()
            tx = self._state.begin_transaction(context)
            target_zone = zone
            if zone is Zone.FOCUS and not pinned:
                focus = self._focus_slots(ws)
                if len(focus) >= self._config.focus_capacity:
                    victim = select_eviction_victim(focus, now, self._config.decay_rate)
                    if victim is None:
                        target_zone = Zone.PERIPHERY  # all pinned
                    elif activation > victim.effective_activation(now, self._config.decay_rate):
                        self._demote_to_periphery(tx, ws, victim, now)
                    else:
                        target_zone = Zone.PERIPHERY
            if target_zone is Zone.PERIPHERY:
                self._make_room_in_periphery(tx, ws, now)
            handle = tx.create(
                WM_REF_TYPE,
                payload=build_payload(
                    target=target, workspace=ws, zone=target_zone,
                    base_activation=activation, loaded_seq=now, pinned=pinned, provenance=provenance,
                ),
                salience=salience, confidence=confidence, relationships=(activation_edge(target),),
            )
            tx.commit()
            self._loads += 1
            self._emit("working_memory.loaded", {"ref": handle, "target": target, "workspace": ws, "zone": target_zone.value}, context)
            return handle

    def refresh(self, ref: str, context: ExecutionContext, *, boost: float | None = None) -> None:
        with self._lock:
            slot = to_slot(self._state.get(ref))
            now = self._services.clock.current()
            eff = slot.effective_activation(now, self._config.decay_rate)
            new_base = refreshed_activation(eff, boost if boost is not None else self._config.refresh_boost)
            tx = self._state.begin_transaction(context)
            tx.update(ref, payload_merge={"base_activation": new_base, "loaded_seq": now})
            tx.commit()
            self._refreshes += 1
            self._emit("working_memory.refreshed", {"ref": ref, "activation": new_base}, context)

    def evict(self, ref: str, context: ExecutionContext) -> None:
        with self._lock:
            tx = self._state.begin_transaction(context)
            tx.update(ref, status=ObjectStatus.ARCHIVED)  # target object persists in State
            tx.commit()
            self._evictions += 1
            self._emit("working_memory.evicted", {"ref": ref}, context)

    def pin(self, ref: str, context: ExecutionContext, *, pinned: bool = True) -> None:
        with self._lock:
            tx = self._state.begin_transaction(context)
            tx.update(ref, payload_merge={"pinned": pinned})
            tx.commit()
            self._emit("working_memory.pinned" if pinned else "working_memory.unpinned", {"ref": ref}, context)

    def expire(self, context: ExecutionContext, *, threshold: float | None = None) -> int:
        with self._lock:
            now = self._services.clock.current()
            thr = threshold if threshold is not None else self._config.min_activation
            victims = [
                s for s in self._slots()
                if not s.pinned and not s.is_chunk and s.chunk_of is None
                and s.effective_activation(now, self._config.decay_rate) < thr
            ]
            if victims:
                tx = self._state.begin_transaction(context)
                for s in victims:
                    tx.update(s.handle, status=ObjectStatus.ARCHIVED)
                tx.commit()
                self._evictions += len(victims)
                self._emit("working_memory.expired", {"count": len(victims)}, context)
            return len(victims)

    # --- chunking / binding (CL23) --------------------------------------- #

    def chunk(self, members: list[str], context: ExecutionContext, *, workspace: str | None = None, provenance: str = "") -> str:
        with self._lock:
            ws = workspace or self._active
            now = self._services.clock.current()
            tx = self._state.begin_transaction(context)
            chunk_h = tx.create(
                WM_REF_TYPE,
                payload=build_payload(
                    target=ws, workspace=ws, zone=Zone.FOCUS,
                    base_activation=1.0, loaded_seq=now, is_chunk=True, provenance=provenance,
                ),
                salience=1.0,
                relationships=tuple(RelationshipEdge(RelationshipType.COMPOSITION, m) for m in members),
            )
            for m in members:
                tx.update(m, payload_merge={"chunk_of": chunk_h, "zone": Zone.PERIPHERY.value})
            tx.commit()
            self._chunks += 1
            self._emit("working_memory.chunked", {"chunk": chunk_h, "members": members}, context)
            return chunk_h

    # --- consolidation hook (for Learning; WM never learns) -------------- #

    def consolidation_candidates(self, workspace: str | None = None, threshold: float = 0.5) -> list[Slot]:
        ws = workspace or self._active
        now = self._services.clock.current()
        cands = [s for s in self._slots(ws) if s.effective_activation(now, self._config.decay_rate) >= threshold]
        self._consolidations += 1
        return cands

    # --- reads / broadcast / inspection ---------------------------------- #

    def read_focus(self, workspace: str | None = None) -> Sequence[Slot]:
        ws = workspace or self._active
        now = self._services.clock.current()
        focus = list(self._focus_slots(ws))
        focus.sort(key=lambda s: s.effective_activation(now, self._config.decay_rate), reverse=True)
        return focus

    def contents(self, workspace: str | None = None) -> Sequence[Slot]:
        return self._slots(workspace or self._active)

    def broadcast(self, workspace: str | None, context: ExecutionContext) -> Sequence[Slot]:
        ws = workspace or self._active
        focus = self.read_focus(ws)
        self._emit(
            "working_memory.broadcast",
            {"workspace": ws, "refs": [s.handle for s in focus], "targets": [s.target for s in focus]},
            context, priority=EventPriority.HIGH,
        )
        return focus

    def inspect(self) -> dict:
        now = self._services.clock.current()
        slots = self._slots()
        return {
            "workspaces": self._workspaces.count(),
            "active": self._active,
            "total_refs": len(slots),
            "activations": {s.handle: s.effective_activation(now, self._config.decay_rate) for s in slots},
        }

    # --- workspaces / context switching / nesting / simulation ----------- #

    def open_workspace(self, kind: WorkspaceKind, context: ExecutionContext, *, parent: str | None = None, isolated: bool = False) -> str:
        with self._lock:
            wsid = self._workspaces.create(kind, parent, isolated, self._services.clock.current())
            self._emit("working_memory.workspace_opened", {"workspace": wsid, "kind": kind.value, "parent": parent}, context)
            return wsid

    def close_workspace(self, workspace: str, context: ExecutionContext) -> int:
        with self._lock:
            self._workspaces.get(workspace)
            candidates = self.consolidation_candidates(workspace)  # episode-close consolidation hook
            slots = self._slots(workspace)
            if slots:
                tx = self._state.begin_transaction(context)
                for s in slots:
                    tx.update(s.handle, status=ObjectStatus.ARCHIVED)
                tx.commit()
                self._evictions += len(slots)
            self._workspaces.remove(workspace)
            if getattr(self, "_active", None) == workspace:
                self._active = self._root
            self._emit("working_memory.workspace_closed", {"workspace": workspace, "consolidation_candidates": len(candidates)}, context)
            return len(candidates)

    def switch_workspace(self, workspace: str) -> str:
        with self._lock:
            self._workspaces.get(workspace)
            previous = self._active
            self._active = workspace
            self._context_switches += 1
            self._emit("working_memory.workspace_switched", {"from": previous, "to": workspace}, _NO_CTX)
            return workspace

    def branch_simulation(self, base_workspace: str, context: ExecutionContext) -> str:
        with self._lock:
            self._workspaces.get(base_workspace)
            sim = self._workspaces.create(WorkspaceKind.SIMULATION, base_workspace, True, self._services.clock.current())
            now = self._services.clock.current()
            base_slots = self._slots(base_workspace)
            if base_slots:
                tx = self._state.begin_transaction(context)
                for s in base_slots:
                    rels = () if s.is_chunk else (activation_edge(s.target),)
                    tx.create(
                        WM_REF_TYPE,
                        payload=build_payload(
                            target=s.target, workspace=sim, zone=s.zone,
                            base_activation=s.base_activation, loaded_seq=now, pinned=s.pinned,
                            is_chunk=s.is_chunk, provenance=f"sim-branch:{s.handle}",
                        ),
                        salience=s.salience, confidence=s.confidence, relationships=rels,
                    )
                tx.commit()
            self._simulations += 1
            self._emit("working_memory.simulation_branched", {"base": base_workspace, "simulation": sim}, context)
            return sim

    def discard_simulation(self, workspace: str, context: ExecutionContext) -> int:
        # Isolated simulation content is discarded; nothing leaks to reality (PrL8).
        return self.close_workspace(workspace, context)

    # --- development hook (gated capacity evolution) --------------------- #

    def set_capacity(self, config: WMConfig, context: ExecutionContext) -> None:
        if "state:admin" not in context.security.scopes:
            raise WorkingMemorySecurityError("Capacity evolution requires admin authority (Development/Executive).")
        with self._lock:
            self._config = config
            self._emit("working_memory.capacity_changed", {"focus": config.focus_capacity, "periphery": config.periphery_capacity}, context)

    def capacity(self) -> WMConfig:
        return self._config

    # --- recovery / snapshot -------------------------------------------- #

    def reconstruct(self) -> int:
        """Rebuild the workspace registry from persistent R4 state (§5.6)."""
        with self._lock:
            objs = self._state.query(region=Region.R4_WORKING_MEMORY, type=WM_REF_TYPE, status=ObjectStatus.ACTIVE)
            for o in objs:
                ws = o.payload["workspace"]
                if not self._workspaces.exists(ws):
                    self._workspaces.create_with_id(ws, WorkspaceKind.NESTED, None, False, 0)
            self._emit("working_memory.reconstructed", {"refs": len(objs)}, _NO_CTX)
            return len(objs)

    def snapshot(self, workspace: str | None = None) -> WMSnapshot:
        ws = workspace or self._active
        return WMSnapshot(workspace=ws, seq=self._services.clock.current(), slots=tuple(self._slots(ws)))

    # --- health / metrics ------------------------------------------------ #

    def metrics(self) -> WMMetricsSnapshot:
        with self._lock:
            return WMMetricsSnapshot(
                loads=self._loads, evictions=self._evictions, overflow_evictions=self._overflow_evictions,
                refreshes=self._refreshes, chunks=self._chunks, consolidations=self._consolidations,
                context_switches=self._context_switches, simulations=self._simulations,
                workspaces=self._workspaces.count(),
                focus_used=len(self._focus_slots(self._active)),
                periphery_used=len(self._periphery_slots(self._active)),
            )

    def wm_health(self) -> WMHealthReport:
        focus_used = len(self._focus_slots(self._active)) if self._started else 0
        healthy = self._started and focus_used <= self._config.focus_capacity
        return WMHealthReport(
            healthy=healthy,
            detail="active" if self._started else "stopped",
            focus_used=focus_used, focus_capacity=self._config.focus_capacity,
            workspaces=self._workspaces.count(),
        )

    def _health_probe(self) -> HealthReport:
        h = self.wm_health()
        return HealthReport(
            component="working_memory",
            status=HealthStatus.HEALTHY if h.healthy else (HealthStatus.DEGRADED if not self._started else HealthStatus.UNHEALTHY),
            detail=h.detail,
            metrics={"focus_used": float(h.focus_used), "workspaces": float(h.workspaces)},
        )

    # --- internals ------------------------------------------------------- #

    def _slots(self, workspace: str | None = None, zone: Zone | None = None) -> list[Slot]:
        objs = self._state.query(region=Region.R4_WORKING_MEMORY, type=WM_REF_TYPE, status=ObjectStatus.ACTIVE)
        slots = [to_slot(o) for o in objs]
        if workspace is not None:
            slots = [s for s in slots if s.workspace == workspace]
        if zone is not None:
            slots = [s for s in slots if s.zone is zone]
        return slots

    def _focus_slots(self, ws: str) -> list[Slot]:
        return [s for s in self._slots(ws, Zone.FOCUS) if s.chunk_of is None]

    def _periphery_slots(self, ws: str) -> list[Slot]:
        return [s for s in self._slots(ws, Zone.PERIPHERY) if s.chunk_of is None]

    def _make_room_in_periphery(self, tx, ws: str, now: int) -> None:
        periphery = self._periphery_slots(ws)
        if len(periphery) >= self._config.periphery_capacity:
            victim = select_eviction_victim(periphery, now, self._config.decay_rate)
            if victim is not None:
                tx.update(victim.handle, status=ObjectStatus.ARCHIVED)  # cool to dormant
                self._overflow_evictions += 1

    def _demote_to_periphery(self, tx, ws: str, victim: Slot, now: int) -> None:
        self._make_room_in_periphery(tx, ws, now)
        tx.update(victim.handle, payload_merge={"zone": Zone.PERIPHERY.value})

    def _emit(self, event_type: str, payload: Mapping[str, Any], context, *, priority: EventPriority = EventPriority.NORMAL) -> None:
        cid = context.correlation_id if context is not None else "working_memory"
        event = CognitiveEvent(
            event_id=uuid.uuid4().hex, type=event_type, sequence=self._services.clock.tick(),
            source="working_memory", correlation_id=cid, payload=payload, priority=priority,
        )
        self._services.events.publish(event)


# A sentinel "no context" for internal events not tied to a caller's execution.
_NO_CTX = None
