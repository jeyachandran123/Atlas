"""The single integration feature flag: ``COGNITIVE_BRAIN_ENABLED``.

Disabled (default) -> the existing production chat pipeline is completely untouched.
Enabled -> the Conversation Platform routes through the Cognitive Operating System.

Reads the pydantic ``Settings`` field when present, else the environment variable —
so it works whether or not the setting has been added to ``config.py``.
"""

from __future__ import annotations

import os


def cognitive_brain_enabled() -> bool:
    try:
        from app.config import get_settings

        value = getattr(get_settings(), "cognitive_brain_enabled", None)
        if value is not None:
            return bool(value)
    except Exception:
        pass
    return os.getenv("COGNITIVE_BRAIN_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
