"""
Master test runner for the Reasoning Engine.
Imports all 14 module test files — run this single file to test everything.

    py -m pytest tests/unit/intelligence/reasoning/test_all_reasoning.py -v
"""

from tests.unit.intelligence.reasoning.test_goal_analyzer import *
from tests.unit.intelligence.reasoning.test_query_rewriter import *
from tests.unit.intelligence.reasoning.test_task_decomposer import *
from tests.unit.intelligence.reasoning.test_execution_planner import *
from tests.unit.intelligence.reasoning.test_confidence_evaluator import *
from tests.unit.intelligence.reasoning.test_reflection_engine import *
from tests.unit.intelligence.reasoning.test_expansion_engine import *
from tests.unit.intelligence.reasoning.test_goal_memory import *
from tests.unit.intelligence.reasoning.test_multi_step_controller import *
from tests.unit.intelligence.reasoning.test_strategy_validator import *
from tests.unit.intelligence.reasoning.test_adaptive_learner import *
from tests.unit.intelligence.reasoning.test_trace_builder import *
from tests.unit.intelligence.reasoning.test_reasoning_engine import *
