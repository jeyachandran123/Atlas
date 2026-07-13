"""
Execution Planner.

Builds an execution graph from a task decomposition.
Answers: what runs first, what can run in parallel, what can be cached,
when to retrieve more context, and how deep reasoning should go.

No LLM call. Pure graph analysis on the TaskDecomposition.
"""

from __future__ import annotations

import hashlib

from app.intelligence.reasoning.interfaces import AbstractExecutionPlanner
from app.intelligence.reasoning.models import (
    ExecutionMode,
    ExecutionPlan,
    ExecutionStep,
    ReasoningDepth,
    TaskDecomposition,
)

# Tools that are safe to run in parallel (read-only, idempotent)
_PARALLEL_SAFE_TOOLS = {"search_code", "git_diff", "read_file"}


def _cache_key(task_description: str, repo_id: str | None) -> str:
    raw = f"{task_description}:{repo_id or ''}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


class ExecutionPlanner(AbstractExecutionPlanner):
    """
    Converts a TaskDecomposition into an ordered ExecutionPlan.

    Algorithm:
    1. Group tasks by dependency level (topological sort)
    2. Within each level, identify parallel-safe tasks
    3. Mark cacheable tasks with cache keys
    4. Determine if additional retrieval is needed
    5. Set reasoning depth based on total steps
    """

    def plan(
        self,
        decomposition: TaskDecomposition,
        context,
    ) -> ExecutionPlan:
        if decomposition.total_tasks <= 1:
            return self._single_step_plan(decomposition, context)

        steps = self._build_steps(decomposition, context)
        has_parallel = any(s.mode == ExecutionMode.PARALLEL for s in steps)
        tool_calls = sum(
            1 for t in decomposition.tasks if t.tool_hint is not None
        )
        depth = ReasoningDepth.MULTI_STEP if decomposition.total_tasks > 1 else ReasoningDepth.SINGLE_PASS

        return ExecutionPlan(
            steps=steps,
            total_steps=len(steps),
            has_parallel_steps=has_parallel,
            reasoning_depth=depth,
            estimated_tool_calls=tool_calls,
            plan_rationale=(
                f"{decomposition.total_tasks} tasks → {len(steps)} execution steps, "
                f"depth={depth.value}, parallel={has_parallel}"
            ),
        )

    def _single_step_plan(self, decomposition: TaskDecomposition, context) -> ExecutionPlan:
        task = decomposition.tasks[0] if decomposition.tasks else None
        step = ExecutionStep(
            step_id="step_1",
            task_ids=[task.task_id] if task else [],
            mode=ExecutionMode.SEQUENTIAL,
            can_reuse_context=bool(context.code_context_block),
            needs_retrieval=bool(task and task.tool_hint == "search_code"),
        )
        return ExecutionPlan(
            steps=[step],
            total_steps=1,
            has_parallel_steps=False,
            reasoning_depth=ReasoningDepth.SINGLE_PASS,
            estimated_tool_calls=1 if (task and task.tool_hint) else 0,
            plan_rationale="Single task — direct execution",
        )

    def _build_steps(self, decomposition: TaskDecomposition, context) -> list[ExecutionStep]:
        """
        Topological grouping: tasks with the same dependency depth
        form one execution step. Within a step, parallel-safe tasks
        are grouped together.
        """
        # Build depth map
        task_map = {t.task_id: t for t in decomposition.tasks}
        depth_map: dict[str, int] = {}

        def get_depth(task_id: str) -> int:
            if task_id in depth_map:
                return depth_map[task_id]
            task = task_map[task_id]
            if not task.depends_on:
                depth_map[task_id] = 0
                return 0
            d = 1 + max(get_depth(dep) for dep in task.depends_on)
            depth_map[task_id] = d
            return d

        for t in decomposition.tasks:
            get_depth(t.task_id)

        # Group by depth
        max_depth = max(depth_map.values(), default=0)
        steps: list[ExecutionStep] = []
        repo_id = context.repo_id

        for level in range(max_depth + 1):
            level_tasks = [
                t for t in decomposition.tasks
                if depth_map.get(t.task_id, 0) == level
            ]
            if not level_tasks:
                continue

            # Separate parallel-safe from sequential
            parallel_tasks = [
                t for t in level_tasks
                if t.tool_hint in _PARALLEL_SAFE_TOOLS
            ]
            sequential_tasks = [
                t for t in level_tasks
                if t.tool_hint not in _PARALLEL_SAFE_TOOLS
            ]

            # Parallel step for read-only tools
            if len(parallel_tasks) > 1:
                steps.append(ExecutionStep(
                    step_id=f"step_{len(steps)+1}_parallel",
                    task_ids=[t.task_id for t in parallel_tasks],
                    mode=ExecutionMode.PARALLEL,
                    can_reuse_context=bool(context.code_context_block),
                    needs_retrieval=any(t.tool_hint == "search_code" for t in parallel_tasks),
                    cache_key=_cache_key(
                        "".join(t.description for t in parallel_tasks), repo_id
                    ) if any(t.can_cache for t in parallel_tasks) else None,
                ))
            elif parallel_tasks:
                t = parallel_tasks[0]
                steps.append(ExecutionStep(
                    step_id=f"step_{len(steps)+1}",
                    task_ids=[t.task_id],
                    mode=ExecutionMode.SEQUENTIAL,
                    can_reuse_context=bool(context.code_context_block),
                    needs_retrieval=t.tool_hint == "search_code",
                    cache_key=_cache_key(t.description, repo_id) if t.can_cache else None,
                ))

            # Sequential steps for write/execute tools
            for t in sequential_tasks:
                steps.append(ExecutionStep(
                    step_id=f"step_{len(steps)+1}",
                    task_ids=[t.task_id],
                    mode=ExecutionMode.SEQUENTIAL,
                    can_reuse_context=bool(context.code_context_block),
                    needs_retrieval=False,
                ))

        return steps


# ── Singleton ─────────────────────────────────────────────────────────────────

_planner: ExecutionPlanner | None = None


def get_execution_planner() -> ExecutionPlanner:
    global _planner
    if _planner is None:
        _planner = ExecutionPlanner()
    return _planner
