"""CognitiveSession — the runtime host of one active brain.

Boots the Kernel, Runtime, State, Working Memory and registers every engine, exactly
as the constitutional wiring requires (each engine's public constructor + ``register``).
The Reasoning Engine is given a pool whose engine is the Ollama-backed Reasoning Port,
so the faculty reasons through the existing LLM infrastructure without any engine
change. This is the *only* place engines are constructed — the composition root. The
pipeline and route depend on this session's public surface, never on engines directly.
"""

from __future__ import annotations

from typing import Any

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import ExecutionContext, SecurityContext
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.working_memory import WMConfig, WorkingMemoryEngine
from app.cognitive_kernel.engines.working_memory.api import WorkingMemoryRuntimeApi
from app.cognitive_kernel.engines.attention import AttentionEngine, AttentionWMPort
from app.cognitive_kernel.engines.reasoning import ReasoningConfig, ReasoningEngine, ReasoningWMPort
from app.cognitive_kernel.engines.prediction import PredictionEngine, RuntimePredictionPort
from app.cognitive_kernel.engines.executive import ExecutiveEngine
from app.cognitive_kernel.engines.metacognition import MetaCognitionEngine
from app.cognitive_kernel.engines.learning import LearningEngine
from app.cognitive_kernel.engines.development import DevelopmentEngine

from .ports import LLMPort, Turn
from .reasoning_port import build_reasoning_pool

# The generative reasoning engine is trusted at the reasoning altitude; the Executive
# is the real safety gate (stakes-scaled). Reasoning concludes readily so chat answers
# flow; the Executive governs authorization.
_REASONING_CALIBRATION = {
    "symbolic": 1.0, "probabilistic": 0.9, "heuristic": 0.7, "generative": 0.6,
    "generative_llm": 0.9,
}


class CognitiveSession:
    def __init__(self, llm: LLMPort, *, identity_name: str = "Atlas", model: str | None = None,
                 focus_capacity: int = 16) -> None:
        self.kernel = Bootstrapper().boot(
            KernelConfig(identity_name=identity_name, identity_core={"safety_first": True}))
        self.services = self.kernel.services()
        self.runtime = CognitiveRuntime(self.services)
        self.runtime.start()
        self.state = CognitiveStateManager(self.services)
        self.state.start()

        self.wm = WorkingMemoryEngine(
            self.services, self.state, WMConfig(focus_capacity=focus_capacity, periphery_capacity=focus_capacity))
        self.wm.register(self.kernel, self.runtime)
        self.wm_api = WorkingMemoryRuntimeApi(self.runtime)

        self.attention = AttentionEngine(self.services, self.state, AttentionWMPort(self.wm, self.wm_api))
        self.attention.register(self.kernel, self.runtime)

        reasoning_config = ReasoningConfig(confidence_sufficient=0.4, engine_calibration=_REASONING_CALIBRATION)
        self.reasoning = ReasoningEngine(
            self.services, self.state, ReasoningWMPort(self.wm), reasoning_config,
            pool=build_reasoning_pool(llm, model=model))
        self.reasoning.register(self.kernel, self.runtime)

        self.prediction = PredictionEngine(self.services, self.state)
        self.prediction.register(self.kernel, self.runtime)

        self.executive = ExecutiveEngine(
            self.services, self.state, prediction_port=RuntimePredictionPort(self.runtime))
        self.executive.register(self.kernel, self.runtime)

        self.metacognition = MetaCognitionEngine(self.services, self.state)
        self.metacognition.register(self.kernel, self.runtime)

        self.learning = LearningEngine(self.services, self.state)
        self.learning.register(self.kernel, self.runtime)

        self.development = DevelopmentEngine(self.services, self.state)
        self.development.register(self.kernel, self.runtime)

    def new_context(self, turn: Turn) -> ExecutionContext:
        return self.services.new_context(
            security=SecurityContext(turn.user_id, turn.org_id),
            correlation_id=turn.conversation_id,
        )

    def health(self) -> dict[str, str]:
        return {name: r.status.value for name, r in self.services.health.report().items()}

    def shutdown(self) -> None:
        for engine in (self.development, self.learning, self.metacognition, self.executive,
                       self.prediction, self.reasoning, self.attention, self.wm):
            try:
                engine.stop()
            except Exception:
                pass
        self.state.stop()
        self.runtime.stop()
        self.kernel.shutdown()
