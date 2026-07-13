import pytest
from app.intelligence.reasoning.adaptive.learner import AdaptiveLearner
from app.intelligence.reasoning.models import QualitySignal


@pytest.fixture
def learner():
    return AdaptiveLearner()


def _signal(signal_type, intent="coding", strategy="coding"):
    return QualitySignal(signal_type=signal_type, intent=intent, strategy=strategy, complexity="medium")


class TestAdaptiveLearner:
    def test_no_adjustments_for_empty_store(self, learner):
        result = learner.get_adjustments("coding", "coding")
        assert result == {}

    def test_single_signal_no_adjustment(self, learner):
        learner.record(_signal("expansion_needed"))
        result = learner.get_adjustments("coding", "coding")
        assert "increase_response_depth" not in result

    def test_three_expansion_signals_triggers_adjustment(self, learner):
        for _ in range(3):
            learner.record(_signal("expansion_needed"))
        result = learner.get_adjustments("coding", "coding")
        assert result.get("increase_response_depth") is True

    def test_three_clarification_signals_triggers_adjustment(self, learner):
        for _ in range(3):
            learner.record(_signal("clarification_needed"))
        result = learner.get_adjustments("coding", "coding")
        assert result.get("lower_clarification_threshold") is True

    def test_three_tool_failed_signals_triggers_adjustment(self, learner):
        for _ in range(3):
            learner.record(_signal("tool_failed"))
        result = learner.get_adjustments("coding", "coding")
        assert result.get("reduce_tool_calls") is True

    def test_three_repo_miss_signals_triggers_adjustment(self, learner):
        for _ in range(3):
            learner.record(_signal("repo_miss"))
        result = learner.get_adjustments("coding", "coding")
        assert result.get("force_retrieval") is True

    def test_three_strategy_mismatch_signals_triggers_adjustment(self, learner):
        for _ in range(3):
            learner.record(_signal("strategy_mismatch"))
        result = learner.get_adjustments("coding", "coding")
        assert result.get("strategy_unreliable") is True

    def test_signals_isolated_by_intent_strategy(self, learner):
        for _ in range(3):
            learner.record(_signal("expansion_needed", intent="debugging", strategy="troubleshooting"))
        result = learner.get_adjustments("coding", "coding")
        assert "increase_response_depth" not in result

    def test_count_included_in_adjustments(self, learner):
        for _ in range(3):
            learner.record(_signal("expansion_needed"))
        result = learner.get_adjustments("coding", "coding")
        assert result.get("expansion_needed_count") == 3

    def test_summary_returns_all_buckets(self, learner):
        learner.record(_signal("expansion_needed", intent="learning", strategy="teaching"))
        learner.record(_signal("tool_failed", intent="debugging", strategy="troubleshooting"))
        summary = learner.summary()
        assert len(summary) == 2
