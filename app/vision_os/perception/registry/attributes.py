"""The Attribute Schema Registry and its neutrality gate (02_VOM section 9).

> **Single responsibility:** *Decide whether an attribute may exist. Produce
> none, infer nothing.*

``14_TESTING`` section 6 names this the **registry gate**: *"Attempting to
register a judgment-bearing attribute is rejected."* It is one of four
independent gates enforcing the Semantic Ceiling, and the only one inside M7.

The gate is not documentation. ``neutrality_justification`` is required, and a
proposed attribute must name the **visible evidence** that supports it:

| Proposed | Verdict |
|---|---|
| `headwear_present: bool` — "head region shows a covering" | registered |
| `posture: enum` — "body configuration is directly visible" | registered |
| `queue_position: count` — "ordinal position along a region's axis" | registered (pure geometry) |
| `is_employee: bool` — "uniform implies employment" | **rejected** — role, not appearance |
| `is_compliant: bool` — "missing helmet is a violation" | **rejected** — policy |
| `wait_time_excessive: bool` — "dwell exceeds threshold" | **rejected** — threshold is business |

Note the pattern in every rejection: **the rejected attribute is the accepted one
plus a business premise.** The registry always has a neutral counterpart to
offer, which is why enforcing the gate does not block delivery — it relocates a
line of logic to where it belongs.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field

from ...core.errors import AttributeRejectedError
from ...core.model.ids import AttributeKey, ClassId
from ...core.model.timebase import Duration


class AttributeValueType(enum.Enum):
    """02_VOM section 9 value types. Closed set."""

    ENUM = "enum"
    BOOL = "bool"
    SCALAR = "scalar"
    VECTOR = "vector"
    TEXT = "text"
    RELATION = "relation"
    COUNT = "count"


class Cardinality(enum.Enum):
    SINGLE = "single"
    MULTI = "multi"


class EvidenceRequirement(enum.Enum):
    CROP = "crop"
    FRAME = "frame"
    SEQUENCE = "sequence"


class SchemaStatus(enum.Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"


#: Key tokens that name a judgment rather than an appearance.
#:
#: Two shapes dominate: a **role** ("employee", "customer", "intruder") and a
#: **verdict** ("compliant", "violation", "excessive", "suspicious"). Both encode
#: a premise the platform does not hold.
_FORBIDDEN_TOKENS: frozenset[str] = frozenset(
    {
        # roles — who someone is, not what is visible
        "employee", "staff", "customer", "shopper", "visitor", "patient",
        "nurse", "doctor", "guard", "intruder", "trespasser", "suspect",
        "owner", "driver", "operator", "worker", "manager", "vip",
        # verdicts — conclusions requiring a policy
        "compliant", "compliance", "violation", "violating", "unauthorized",
        "authorised", "authorized", "permitted", "forbidden", "illegal",
        "suspicious", "abnormal", "anomalous", "anomaly", "threat", "danger",
        "dangerous", "unsafe", "risky", "alert", "incident",
        # thresholds — a number only a consumer owns
        "excessive", "insufficient", "overcrowded", "crowded", "congested",
        "busy", "idle", "loitering", "queueing", "waiting", "delayed", "late",
        "overdue", "understaffed", "overstaffed",
        # business nouns
        "order", "invoice", "sku", "shift", "appointment", "booking",
    }
)

#: Prefixes that almost always introduce a judgment.
#:
#: ``is_`` and ``has_`` are not forbidden outright — ``has_headwear`` is a
#: perfectly neutral claim about pixels. They are forbidden *in combination with*
#: a judgment token, which the token set above already catches. What is caught
#: here is the residue: keys asserting a verdict with no noun at all.
_FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {"is_ok", "is_good", "is_bad", "is_normal", "is_valid", "is_correct", "status"}
)

#: A justification must name visible evidence. These words indicate the author
#: reached for a premise instead.
_WEAK_JUSTIFICATION: frozenset[str] = frozenset(
    {"implies", "means", "indicates that they are", "should", "must", "policy",
     "rule", "requirement", "because they are", "obviously"}
)

_MIN_JUSTIFICATION_CHARS = 12


@dataclass(frozen=True, slots=True)
class AttributeSchema:
    """One registered attribute definition (02_VOM section 9)."""

    key: AttributeKey
    value_type: AttributeValueType
    neutrality_justification: str
    """**Required.** What visible evidence supports this attribute."""

    applies_to: tuple[ClassId, ...] = ()
    domain: tuple[str, ...] = ()
    """Allowed values for ``ENUM``; unit or range description otherwise."""

    cardinality: Cardinality = Cardinality.SINGLE
    validity: Duration | None = None
    """Default staleness horizon. ``None`` means the value does not expire."""

    evidence_requirement: EvidenceRequirement = EvidenceRequirement.CROP
    version: str = "1.0.0"
    status: SchemaStatus = SchemaStatus.ACTIVE

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("an attribute schema requires a key")
        if self.value_type is AttributeValueType.ENUM and not self.domain:
            raise ValueError(
                f"attribute '{self.key}' is an enum but declares no domain; an "
                f"unconstrained enum is a text field wearing a type"
            )

    @property
    def is_active(self) -> bool:
        return self.status is SchemaStatus.ACTIVE


def _tokens(key: str) -> set[str]:
    return {part for part in re.split(r"[_.\-]", key.lower()) if part}


def check_neutrality(key: AttributeKey, justification: str) -> None:
    """Raise unless the attribute names visible evidence.

    Raises:
        AttributeRejectedError: the key encodes a role, a verdict, or a
            threshold, or the justification appeals to a premise rather than to
            pixels. The message names the neutral counterpart to register
            instead, because the gate exists to relocate a line of logic, not to
            block delivery.
    """
    lowered = key.lower()
    offending = _tokens(lowered) & _FORBIDDEN_TOKENS

    if offending:
        token = sorted(offending)[0]
        raise AttributeRejectedError(
            f"attribute '{key}' is rejected: '{token}' names a role, a verdict or "
            f"a threshold, none of which are visible in pixels. Register what can "
            f"be seen instead — 'uniform_present' rather than 'is_employee', "
            f"'helmet_present' rather than 'is_compliant', 'dwell_duration' "
            f"rather than 'wait_time_excessive' (02_VOM section 9.1, invariant V1)",
            attribute_key=str(key),
            token=token,
        )

    if lowered in _FORBIDDEN_KEYS:
        raise AttributeRejectedError(
            f"attribute '{key}' is rejected: it asserts a verdict with no visual "
            f"referent. Name the observable property instead (invariant V1)",
            attribute_key=str(key),
        )

    if len(justification.strip()) < _MIN_JUSTIFICATION_CHARS:
        raise AttributeRejectedError(
            f"attribute '{key}' is rejected: neutrality_justification is required "
            f"and must name the visible evidence supporting the attribute. It is "
            f"the registration gate, not documentation (02_VOM section 9.1)",
            attribute_key=str(key),
        )

    weak = [phrase for phrase in _WEAK_JUSTIFICATION if phrase in justification.lower()]
    if weak:
        raise AttributeRejectedError(
            f"attribute '{key}' is rejected: its justification appeals to "
            f"'{weak[0]}' rather than to visible evidence. A justification must "
            f"say what the pixels show, not what it would imply (invariant V1)",
            attribute_key=str(key),
            phrase=weak[0],
        )


@dataclass(slots=True)
class AttributeRegistry:
    """The registered attribute vocabulary for a deployment.

    Injected into the Object Registry, which consults it before holding any
    attribute value. An unregistered attribute is refused: the gate is worthless
    if a producer can bypass it by simply not asking.
    """

    schemas: dict[AttributeKey, AttributeSchema] = field(default_factory=dict)

    def register(self, schema: AttributeSchema) -> AttributeSchema:
        """Admit an attribute after the neutrality gate.

        Raises:
            AttributeRejectedError: the attribute is judgment-bearing.
        """
        check_neutrality(schema.key, schema.neutrality_justification)
        self.schemas[schema.key] = schema
        return schema

    def get(self, key: AttributeKey) -> AttributeSchema | None:
        return self.schemas.get(key)

    def require(self, key: AttributeKey) -> AttributeSchema:
        schema = self.schemas.get(key)
        if schema is None:
            raise AttributeRejectedError(
                f"attribute '{key}' is not registered; the registry holds only "
                f"attributes that have passed the neutrality gate",
                attribute_key=str(key),
            )
        if not schema.is_active:
            raise AttributeRejectedError(
                f"attribute '{key}' is deprecated and no longer accepted",
                attribute_key=str(key),
            )
        return schema

    def applies(self, key: AttributeKey, class_id: ClassId) -> bool:
        """Whether this attribute may be carried by this taxonomy class.

        An empty ``applies_to`` means "any class" — a deliberate degenerate case
        rather than an omission, since some attributes (``truncation``) are
        genuinely class-independent.
        """
        schema = self.schemas.get(key)
        if schema is None:
            return False
        if not schema.applies_to:
            return True
        return any(
            class_id == allowed or class_id.startswith(f"{allowed}.")
            for allowed in schema.applies_to
        )

    def __contains__(self, key: object) -> bool:
        return key in self.schemas

    def __len__(self) -> int:
        return len(self.schemas)
