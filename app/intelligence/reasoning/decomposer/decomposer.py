"""
Task Decomposer.

Breaks complex requests into ordered, executable tasks before tool planning.
Each task is independently executable and has explicit dependencies.

"Review my repository and improve authentication."
→ Task 1: search_code(auth)
→ Task 2: read_file(auth_module)   [depends on Task 1]
→ Task 3: analyze_architecture     [depends on Task 2]
→ Task 4: detect_problems          [depends on Task 3]
→ Task 5: suggest_improvements     [depends on Task 4]
→ Task 6: generate_patches         [depends on Task 5]

No LLM call. Decomposition is driven by goal type + complexity.
"""

from __future__ import annotations

import uuid

from app.intelligence.reasoning.interfaces import AbstractTaskDecomposer
from app.intelligence.reasoning.models import (
    GoalType,
    InferredGoal,
    ReasoningTask,
    TaskDecomposition,
)

# ── Task templates per GoalType ───────────────────────────────────────────────
# Each template is a list of (description, tool_hint, can_cache) tuples.
# Dependencies are assigned sequentially unless marked parallel.

_TASK_TEMPLATES: dict[GoalType, list[tuple[str, str | None, bool]]] = {
    GoalType.FIND_AND_FIX: [
        ("Search for the relevant implementation",  "search_code",  True),
        ("Read the implementation file",            "read_file",    False),
        ("Identify the root cause",                 None,           False),
        ("Design and apply the fix",                "write_file",   False),
        ("Explain the fix and prevention",          None,           False),
    ],
    GoalType.BUILD: [
        ("Understand requirements from context",    None,           False),
        ("Search for related existing code",        "search_code",  True),
        ("Design the implementation",               None,           False),
        ("Write the complete implementation",       "write_file",   False),
        ("Explain design decisions",                None,           False),
    ],
    GoalType.IMPROVE: [
        ("Search for the code to improve",          "search_code",  True),
        ("Read the current implementation",         "read_file",    False),
        ("Identify improvement opportunities",      None,           False),
        ("Apply improvements",                      "write_file",   False),
        ("Explain what changed and why",            None,           False),
    ],
    GoalType.VALIDATE: [
        ("Search for the code to test",             "search_code",  True),
        ("Read the implementation",                 "read_file",    False),
        ("Design test cases",                       None,           False),
        ("Write the tests",                         "write_file",   False),
        ("Report coverage and results",             None,           False),
    ],
    GoalType.UNDERSTAND: [
        ("Retrieve relevant context",               "search_code",  True),
        ("Build explanation",                       None,           False),
        ("Provide examples",                        None,           False),
    ],
    GoalType.EXPLAIN: [
        ("Identify explanation scope",              None,           False),
        ("Structure progressive explanation",       None,           False),
        ("Add examples and analogies",              None,           False),
        ("Summarize key takeaways",                 None,           False),
    ],
    GoalType.RESEARCH: [
        ("Survey available options",                None,           False),
        ("Evaluate each option",                    None,           False),
        ("Synthesize findings",                     None,           False),
    ],
    GoalType.DECIDE: [
        ("Identify decision context",               None,           False),
        ("Evaluate options against context",        None,           False),
        ("Make recommendation with reasoning",      None,           False),
    ],
    GoalType.COMPARE: [
        ("Define comparison dimensions",            None,           False),
        ("Evaluate each option per dimension",      None,           False),
        ("Build comparison summary",                None,           False),
        ("Recommend best fit",                      None,           False),
    ],
    GoalType.PLAN: [
        ("Understand desired outcome",              None,           False),
        ("Break work into phases",                  None,           False),
        ("Identify dependencies and risks",         None,           False),
        ("Produce actionable plan",                 None,           False),
    ],
    GoalType.UNKNOWN: [
        ("Clarify intent",                          None,           False),
        ("Respond to most likely interpretation",   None,           False),
    ],
}


def _make_task_id() -> str:
    return str(uuid.uuid4())[:8]


class TaskDecomposer(AbstractTaskDecomposer):
    """
    Decomposes a goal into ordered tasks.
    Simple goals → 1 task. Complex goals → full task graph.
    """

    # Complexity levels that trigger full decomposition
    _DECOMPOSE_COMPLEXITIES = {"complex", "very_complex"}

    def decompose(
        self,
        goal: InferredGoal,
        context,
    ) -> TaskDecomposition:
        complexity = context.complexity.level.value
        requires_tools = goal.requires_tools and bool(context.repo_id)

        # Simple goals: single task, no decomposition overhead
        if complexity not in self._DECOMPOSE_COMPLEXITIES or not requires_tools:
            task_id = _make_task_id()
            single_task = ReasoningTask(
                task_id=task_id,
                description=goal.primary_objective,
                tool_hint=None,
                depends_on=[],
                can_cache=False,
            )
            return TaskDecomposition(
                tasks=[single_task],
                total_tasks=1,
                requires_tools=False,
                estimated_steps=1,
                decomposition_rationale="Simple request — single task",
            )

        # Complex goals: use template
        template = _TASK_TEMPLATES.get(goal.goal_type, _TASK_TEMPLATES[GoalType.UNKNOWN])
        tasks: list[ReasoningTask] = []
        prev_id: str | None = None

        for description, tool_hint, can_cache in template:
            task_id = _make_task_id()
            depends_on = [prev_id] if prev_id else []
            tasks.append(ReasoningTask(
                task_id=task_id,
                description=description,
                tool_hint=tool_hint,
                depends_on=depends_on,
                can_cache=can_cache,
            ))
            prev_id = task_id

        tool_tasks = [t for t in tasks if t.tool_hint is not None]

        return TaskDecomposition(
            tasks=tasks,
            total_tasks=len(tasks),
            requires_tools=bool(tool_tasks),
            estimated_steps=len(tasks),
            decomposition_rationale=(
                f"Goal type '{goal.goal_type.value}' with complexity '{complexity}' "
                f"decomposed into {len(tasks)} tasks"
            ),
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_decomposer: TaskDecomposer | None = None


def get_task_decomposer() -> TaskDecomposer:
    global _decomposer
    if _decomposer is None:
        _decomposer = TaskDecomposer()
    return _decomposer
