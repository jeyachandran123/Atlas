"""Understanding adapters — reference understanders, coercion, and the M10 seam.

**Nothing outside this package and the composition root may name an
understander or a coercion strategy.** The platform holds P15 and P16; which
implementation satisfies each is a configuration fact, exactly as Flow 2 keeps
YOLO invisible and Flow 5 keeps crop strategies invisible.

**No VLM ships.** 06_PORTS lists Qwen2.5-VL, GPT-4.1 Vision and the rest as
adapter *examples*; binding one needs weights, a runtime and a device, which are
M18's concern and a deployment's choice. What ships is a scripted understander,
a specialized attribute head, and an always-unavailable terminal — between them
they exercise every path the engine has without making a test depend on what a
model happened to say.
"""

from .coercion import (
    MAX_SCAN_CHARS,
    JsonCoercion,
    KeyValueCoercion,
    PassthroughCoercion,
)
from .prompts import PROVIDER_ID, PromptTemplate, StaticPromptProvider
from .understanders import (
    ScriptedAnswer,
    ScriptedUnderstander,
    StaticAttributeHead,
    UnavailableUnderstander,
)

#: Coercion strategies selectable by configuration.
#:
#: A closed table, like the tracker and crop-strategy factories. A deployment
#: names a strategy; it does not import one.
COERCION_FACTORIES = {
    "coercion.json": JsonCoercion,
    "coercion.keyvalue": KeyValueCoercion,
    "coercion.passthrough": PassthroughCoercion,
}

__all__ = [
    "COERCION_FACTORIES",
    "MAX_SCAN_CHARS",
    "PROVIDER_ID",
    "JsonCoercion",
    "KeyValueCoercion",
    "PassthroughCoercion",
    "PromptTemplate",
    "ScriptedAnswer",
    "ScriptedUnderstander",
    "StaticAttributeHead",
    "StaticPromptProvider",
    "UnavailableUnderstander",
]
