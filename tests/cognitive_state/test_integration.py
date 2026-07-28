"""Integration with the kernel: ledger, health, checkpoints, security."""

from __future__ import annotations

import pytest

from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.state import ObjectType, StateSecurityError

from ._st import make_state


def test_state_changes_recorded_in_kernel_ledger() -> None:
    kernel, sm, ctx = make_state()
    try:
        before = kernel.services().ledger.head()
        tx = sm.begin_transaction(ctx)
        tx.create(ObjectType.GOAL, payload={"desc": "x"})
        tx.commit()
        after = kernel.services().ledger.head()
        assert after > before and kernel.services().ledger.verify()
        types = {e.event.type for e in kernel.services().ledger.read(since=before)}
        assert "cognitive_state.object.created" in types
    finally:
        sm.stop()


def test_health_probe_registered_with_kernel() -> None:
    kernel, sm, ctx = make_state()
    try:
        reports = kernel.services().health.report()
        assert "cognitive_state" in reports
        assert sm.health().healthy and sm.health().integrity_ok
    finally:
        sm.stop()


def test_checkpoint_uses_kernel_checkpoint_store() -> None:
    kernel, sm, ctx = make_state()
    try:
        tx = sm.begin_transaction(ctx)
        tx.create(ObjectType.GOAL, payload={"desc": "x"})
        tx.commit()
        cid = sm.checkpoint()
        # The kernel store owns it.
        cp = kernel.services().checkpoints.load(cid)
        assert cp.owner == "cognitive_state" and cp.kind == "cognitive_state"
    finally:
        sm.stop()


def test_security_enforcement() -> None:
    kernel, sm, ctx = make_state(security_enforce=True)
    try:
        no_scope = kernel.services().new_context(security=SecurityContext("u", "o"))
        writeable = kernel.services().new_context(
            security=SecurityContext("u", "o", frozenset({"state:read", "state:write"}))
        )
        # Write without scope is refused.
        tx = sm.begin_transaction(no_scope)
        tx.create(ObjectType.GOAL, payload={})
        with pytest.raises(StateSecurityError):
            tx.commit()
        # Write with scope succeeds; read without scope is refused.
        tx2 = sm.begin_transaction(writeable)
        h = tx2.create(ObjectType.GOAL, payload={})
        tx2.commit()
        with pytest.raises(StateSecurityError):
            sm.get(h, context=no_scope)
        assert sm.get(h, context=writeable).version == 1
    finally:
        sm.stop()
