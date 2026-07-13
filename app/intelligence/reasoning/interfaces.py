"""
Abstract interfaces for every reasoning module.

Every module implements exactly one interface.
The ReasoningEngine depends on these abstractions — never on concretions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.intelligence.models import IntelligenceContext
    from app.intelligence.reasoning.models import (
        ActiveGoalContext,
        ConfidenceReport,
        ExecutionPlan,
        ExpansionPlan,
        InferredGoal,
        QualitySignal,
        ReflectionResult,
        RewrittenQuery,
        TaskDecomposition,
        ValidationResult,
    )


class AbstractGoalAnalyzer(ABC):
    """Infers the actual goal from a user message."""

    @abstractmethod
    def analyze(
        self,
        message: str,
        context: "IntelligenceContext",
        active_goal: "ActiveGoalContext",
    ) -> "InferredGoal":
        ...


class AbstractQueryRewriter(ABC):
    """Enriches incomplete queries with missing context. Never changes meaning."""

    @abstractmethod
    def rewrite(
        self,
        message: str,
        goal: "InferredGoal",
        context: "IntelligenceContext",
    ) -> "RewrittenQuery":
        ...


class AbstractTaskDecomposer(ABC):
    """Breaks complex requests into ordered, executable tasks."""

    @abstractmethod
    def decompose(
        self,
        goal: "InferredGoal",
        context: "IntelligenceContext",
    ) -> "TaskDecomposition":
        ...


class AbstractExecutionPlanner(ABC):
    """Builds an execution graph from a task decomposition."""

    @abstractmethod
    def plan(
        self,
        decomposition: "TaskDecomposition",
        context: "IntelligenceContext",
    ) -> "ExecutionPlan":
        ...


class AbstractConfidenceEvaluator(ABC):
    """Evaluates confidence across all reasoning dimensions."""

    @abstractmethod
    def evaluate(
        self,
        goal: "InferredGoal",
        context: "IntelligenceContext",
    ) -> "ConfidenceReport":
        ...


class AbstractReflectionEngine(ABC):
    """Reflects on whether the generated response achieved the goal."""

    @abstractmethod
    def reflect(
        self,
        response: str,
        goal: "InferredGoal",
        context: "IntelligenceContext",
    ) -> "ReflectionResult":
        ...


class AbstractExpansionEngine(ABC):
    """Identifies weak sections and plans targeted expansion."""

    @abstractmethod
    def plan_expansion(
        self,
        response: str,
        reflection: "ReflectionResult",
        context: "IntelligenceContext",
    ) -> "ExpansionPlan":
        ...


class AbstractGoalMemory(ABC):
    """Stores and retrieves goals across conversation turns."""

    @abstractmethod
    def get_active_context(
        self,
        user_id: str,
        conversation_id: str,
        current_goal: "InferredGoal",
    ) -> "ActiveGoalContext":
        ...

    @abstractmethod
    def store(
        self,
        user_id: str,
        conversation_id: str,
        goal: "InferredGoal",
        turn_index: int,
    ) -> None:
        ...


class AbstractStrategyValidator(ABC):
    """Validates that the selected response strategy matches the inferred goal."""

    @abstractmethod
    def validate(
        self,
        goal: "InferredGoal",
        context: "IntelligenceContext",
    ) -> "ValidationResult":
        ...


class AbstractAdaptiveLearner(ABC):
    """Collects quality signals and adjusts reasoning behaviour over time."""

    @abstractmethod
    def record(self, signal: "QualitySignal") -> None:
        ...

    @abstractmethod
    def get_adjustments(self, intent: str, strategy: str) -> dict:
        """Return behaviour adjustments based on accumulated signals."""
        ...
