"""Identity infrastructure — the invariant Core.

Identity is created once and never replaced (Phase 1 Ch4; DeL1/ExL12/MeL12). It
survives restart, recovery, checkpoint restore, engine failure, learning,
development, and meta-cognition. This provider *enforces* create-once semantics:
there is deliberately no ``set`` or ``replace``. Persistence is delegated to an
injected store so identity outlives the process without the provider knowing how
it is stored (SOLID DIP).
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from .contracts import Identity, IdentityProvider
from .errors import KernelError


class IdentityAlreadyEstablished(KernelError):
    """Attempted to establish or replace an already-existing identity."""


class IdentityNotEstablished(KernelError):
    """Requested the identity before it was established."""


IdentityLoader = Callable[[], Identity | None]
IdentitySaver = Callable[[Identity], None]


def _to_bytes(identity: Identity) -> bytes:
    return json.dumps(
        {
            "identity_id": identity.identity_id,
            "name": identity.name,
            "core": dict(identity.core),
            "created_at": identity.created_at.isoformat(),
            "version": identity.version,
        },
        sort_keys=True,
    ).encode("utf-8")


def _from_bytes(blob: bytes) -> Identity:
    data = json.loads(blob.decode("utf-8"))
    return Identity(
        identity_id=data["identity_id"],
        name=data["name"],
        core=MappingProxyType(dict(data["core"])),
        created_at=datetime.fromisoformat(data["created_at"]),
        version=int(data["version"]),
    )


class KernelIdentityProvider(IdentityProvider):
    def __init__(self, loader: IdentityLoader | None = None, saver: IdentitySaver | None = None) -> None:
        self._identity: Identity | None = None
        self._saver = saver
        self._lock = threading.Lock()
        if loader is not None:
            restored = loader()
            if restored is not None:
                self._identity = restored

    def establish(self, name: str, core: Mapping[str, Any]) -> Identity:
        with self._lock:
            if self._identity is not None:
                # Idempotent for an identical re-establish; refuse any change.
                if self._identity.name == name and dict(self._identity.core) == dict(core):
                    return self._identity
                raise IdentityAlreadyEstablished(
                    "Identity is created once and can never be replaced (DeL1/ExL12)."
                )
            identity = Identity(
                identity_id=uuid.uuid4().hex,
                name=name,
                core=MappingProxyType(dict(core)),
                created_at=datetime.now(timezone.utc),
                version=1,
            )
            self._identity = identity
            if self._saver is not None:
                self._saver(identity)
            return identity

    def identity(self) -> Identity:
        with self._lock:
            if self._identity is None:
                raise IdentityNotEstablished("Identity has not been established.")
            return self._identity

    def is_established(self) -> bool:
        with self._lock:
            return self._identity is not None


# Serialisation helpers exposed for the checkpoint-backed persistence seam.
identity_to_bytes = _to_bytes
identity_from_bytes = _from_bytes
