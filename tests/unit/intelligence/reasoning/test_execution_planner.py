import pytest
from app.intelligence.reasoning.planner.planner import ExecutionPlanner
from app.intelligence.reasoning.models import (
    ExecutionMode, GoalType, InferredGoal, ReasoningDepth,
    ReasoningTask, TaskDecomposition, TaskStatus,
)


@pytest.fixture
def planner():
    return ExecutionPlanner()


def _make_context(repo_id="repo1", code_context=""):
    from app.intelligence.models import (
        ComplexityAnalysis, ConversationAnalysis, ConversationTurn,
        DetectedIntent, IntelligenceContext, IntentAnalysis, Intent,
        Persona, PolicyDecision, PolicyResult, ResponseStrategy, Complexity,
    )
    return IntelligenceContext(
        user_message="test",
        conversation_id="conv1",
        user_id="user1",
        org_id="org1",
        repo_id=repo_id,
        agent_mode="auto",
        intent_analysis=IntentAnalysis(primary=DetectedIntent(Intent.DEBUGGING, 0.9, [])),
        complexity=ComplexityAnalysis(
            level=Complexity.COMPLEX,
            expected_response_length="long",
            reasoning_depth="deep",
            estimated_tool_calls=3,
            estimated_context_tokens=4096,
            expected_token_budget=4096,
            response_strategy_hint=ResponseStrategy.TROUBLESHOOTING,
        ),
        conversation=ConversationAnalysis(
            turn_type=ConversationTurn.NEW_TOPIC,
            topic_summary="test",
            user_goal="test",
            is_continuation=False,
            referenced_prior_turn=False,
        ),
        policy=PolicyResult(decision=PolicyDecision.ALLOW),
        persona=Persona.DEBUGGER,
        strategy=ResponseStrategy.TROUBLESHOOTING,
        code_context_block=code_context,
    )


def _make_decomposition(tasks):
    return TaskDecomposition(
        tasks=tasks,
        total_tasks=len(tasks),
        requires_tools=any(t.tool_hint for t in tasks),
        estimated_steps=len(tasks),
    )


def _task(tid, desc, tool=None, depends=None, cache=False):
    return ReasoningTask(
        task_id=tid,
        description=desc,
        tool_hint=tool,
        depends_on=depends or [],
        can_cache=cache,
        status=TaskStatus.PENDING,
    )


class TestExecutionPlanner:
    def test_single_task_produces_single_step(self, planner):
        decomp = _make_decomposition([_task("t1", "do something")])
        ctx = _make_context()
        plan = planner.plan(decomp, ctx)
        assert plan.total_steps == 1

    def test_single_step_is_sequential(self, planner):
        decomp = _make_decomposition([_task("t1", "do something")])
        ctx = _make_context()
        plan = planner.plan(decomp, ctx)
        assert plan.steps[0].mode == ExecutionMode.SEQUENTIAL

    def test_multi_task_produces_multiple_steps(self, planner):
        tasks = [
            _task("t1", "search", tool="search_code", cache=True),
            _task("t2", "read", tool="read_file", depends=["t1"]),
            _task("t3", "fix", tool="write_file", depends=["t2"]),
        ]
        decomp = _make_decomposition(tasks)
        ctx = _make_context()
        plan = planner.plan(decomp, ctx)
        assert plan.total_steps >= 1

    def test_parallel_safe_tools_grouped(self, planner):
        tasks = [
            _task("t1", "search auth", tool="search_code", cache=True),
            _task("t2", "search user", tool="search_code", cache=True),
        ]
        decomp = _make_decomposition(tasks)
        ctx = _make_context()
        plan = planner.plan(decomp, ctx)
        parallel_steps = [s for s in plan.steps if s.mode == ExecutionMode.PARALLEL]
        assert len(parallel_steps) >= 1

    def test_reasoning_depth_multi_step_for_many_tasks(self, planner):
        tasks = [
            _task("t1", "search", tool="search_code"),
            _task("t2", "read", tool="read_file", depends=["t1"]),
            _task("t3", "analyze", depends=["t2"]),
        ]
        decomp = _make_decomposition(tasks)
        ctx = _make_context()
        plan = planner.plan(decomp, ctx)
        assert plan.reasoning_depth == ReasoningDepth.MULTI_STEP

    def test_single_task_is_single_pass(self, planner):
        decomp = _make_decomposition([_task("t1", "explain")])
        ctx = _make_context()
        plan = planner.plan(decomp, ctx)
        assert plan.reasoning_depth == ReasoningDepth.SINGLE_PASS

    def test_estimated_tool_calls_counted(self, planner):
        tasks = [
            _task("t1", "search", tool="search_code"),
            _task("t2", "read", tool="read_file", depends=["t1"]),
            _task("t3", "explain"),
        ]
        decomp = _make_decomposition(tasks)
        ctx = _make_context()
        plan = planner.plan(decomp, ctx)
        assert plan.estimated_tool_calls == 2

    def test_plan_rationale_populated(self, planner):
        tasks = [_task("t1", "search", tool="search_code")]
        decomp = _make_decomposition(tasks)
        ctx = _make_context()
        plan = planner.plan(decomp, ctx)
        assert len(plan.plan_rationale) > 0

    def test_cache_key_set_for_cacheable_tasks(self, planner):
        tasks = [
            _task("t1", "search auth", tool="search_code", cache=True),
            _task("t2", "search user", tool="search_code", cache=True),
        ]
        decomp = _make_decomposition(tasks)
        ctx = _make_context()
        plan = planner.plan(decomp, ctx)
        steps_with_cache = [s for s in plan.steps if s.cache_key]
        assert len(steps_with_cache) >= 1

    def test_needs_retrieval_flagged_for_search_tasks(self, planner):
        tasks = [_task("t1", "search code", tool="search_code")]
        decomp = _make_decomposition(tasks)
        ctx = _make_context()
        plan = planner.plan(decomp, ctx)
        assert any(s.needs_retrieval for s in plan.steps)
