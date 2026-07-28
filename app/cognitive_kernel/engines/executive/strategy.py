"""The Strategy Governor (Phase 5 Ch2 §8) — governs which strategies are in force.

Sets strategy policy and authorizes costly switches at the executive altitude
(cognitive flexibility), issuing directives through the runtime-routed control
ports — the Meta-Reasoning Hook for reasoning depth/strategy (item 23) and the
Attention override for strategic bias (item 22). Planning is reasoning specialized
to future action, so planning coordination (item 17) is commissioned by directing
reasoning with a decomposition strategy. Switches are stabilised against thrash.
"""

from __future__ import annotations

from typing import Any

from .contracts import Directive, ExecutiveConfig


class StrategyGovernor:
    def __init__(self, config: ExecutiveConfig, reasoning_port: Any, attention_port: Any) -> None:
        self._config = config
        self._reasoning = reasoning_port
        self._attention = attention_port
        self._current: dict[str, str] = {}   # matter_id -> strategy in force (anti-thrash)

    def select_reasoning_strategy(self, *, stakes: float, uncertainty: float, correctness_critical: bool) -> str:
        if correctness_critical:
            return "verify_then_trust"
        if stakes < 0.2:
            return "fast_heuristic"
        if stakes >= 0.7:
            return "ensemble"
        if uncertainty >= 0.6:
            return "search"
        return "linear"

    def should_switch(self, matter_id: str, proposed: str) -> bool:
        return self._current.get(matter_id) != proposed

    def govern_reasoning(
        self, context: Any, matter_id: str, *, stakes: float = 0.0, uncertainty: float = 0.5,
        correctness_critical: bool = False, depth: int | None = None, max_steps: int | None = None,
    ) -> Directive:
        strategy = self.select_reasoning_strategy(
            stakes=stakes, uncertainty=uncertainty, correctness_critical=correctness_critical
        )
        if self.should_switch(matter_id, strategy):
            self._reasoning.set_strategy(strategy, context)          # via Meta-Reasoning Hook (runtime)
            self._current[matter_id] = strategy
        if depth is not None or max_steps is not None:
            self._reasoning.set_deliberation(context, max_steps=max_steps, depth=depth)
        return Directive(target="reasoning", operation="set_strategy_directive",
                         payload={"strategy": strategy, "matter": matter_id, "depth": depth})

    def guide_attention(self, context: Any, target: str, delta: float) -> Directive:
        self._attention.bias(target, delta, context)                # via Attention override (runtime)
        return Directive(target="attention", operation="set_executive_bias",
                         payload={"target": target, "delta": delta})

    def coordinate_planning(self, context: Any, goal_id: str) -> Directive:
        """Commission a plan — reasoning specialized to future action (decomposition)."""
        self._reasoning.set_strategy("decomposition", context)
        self._current[goal_id] = "decomposition"
        return Directive(target="reasoning", operation="set_strategy_directive",
                         payload={"strategy": "decomposition", "matter": goal_id})
