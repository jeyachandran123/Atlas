"""Assemble the complete Cognitive Operating System — every faculty, wired.

This is the whole mind booted as one system: Kernel + Runtime + State + the eight
cognitive engines, each registered with the Kernel and Runtime and coordinating
*only* through public contracts and the Runtime (never a direct engine call).
"""

from __future__ import annotations

from app.cognitive_kernel import Bootstrapper, KernelConfig
from app.cognitive_kernel.contracts import SecurityContext
from app.cognitive_kernel.runtime import CognitiveRuntime
from app.cognitive_kernel.state import CognitiveStateManager
from app.cognitive_kernel.engines.working_memory import WMConfig, WorkingMemoryEngine
from app.cognitive_kernel.engines.working_memory.api import WorkingMemoryRuntimeApi
from app.cognitive_kernel.engines.attention import AttentionEngine, AttentionWMPort
from app.cognitive_kernel.engines.reasoning import ReasoningEngine, ReasoningWMPort
from app.cognitive_kernel.engines.prediction import PredictionEngine, RuntimePredictionPort
from app.cognitive_kernel.engines.executive import ExecutiveEngine
from app.cognitive_kernel.engines.metacognition import MetaCognitionEngine
from app.cognitive_kernel.engines.learning import LearningEngine
from app.cognitive_kernel.engines.development import DevelopmentEngine

ENGINE_NAMES = frozenset({
    "working_memory", "attention", "reasoning", "prediction",
    "executive", "metacognition", "learning", "development",
})


def assemble():
    kernel = Bootstrapper().boot(KernelConfig(identity_name="Atlas", identity_core={"safety_first": True}))
    services = kernel.services()
    runtime = CognitiveRuntime(services)
    runtime.start()
    state = CognitiveStateManager(services)
    state.start()

    # Boot the faculties in dependency order; each registers with Kernel + Runtime.
    wm = WorkingMemoryEngine(services, state, WMConfig(focus_capacity=12, periphery_capacity=12))
    wm.register(kernel, runtime)
    wm_api = WorkingMemoryRuntimeApi(runtime)
    attention = AttentionEngine(services, state, AttentionWMPort(wm, wm_api))
    attention.register(kernel, runtime)
    reasoning = ReasoningEngine(services, state, ReasoningWMPort(wm))
    reasoning.register(kernel, runtime)
    prediction = PredictionEngine(services, state)
    prediction.register(kernel, runtime)
    executive = ExecutiveEngine(services, state, prediction_port=RuntimePredictionPort(runtime))
    executive.register(kernel, runtime)
    metacognition = MetaCognitionEngine(services, state)
    metacognition.register(kernel, runtime)
    learning = LearningEngine(services, state)
    learning.register(kernel, runtime)
    development = DevelopmentEngine(services, state)
    development.register(kernel, runtime)

    ctx = services.new_context(security=SecurityContext("user", "org"))
    engines = {
        "wm": wm, "wm_api": wm_api, "attention": attention, "reasoning": reasoning,
        "prediction": prediction, "executive": executive, "metacognition": metacognition,
        "learning": learning, "development": development,
    }
    return kernel, runtime, state, engines, ctx


def teardown(kernel, runtime, state, engines) -> None:
    for name, e in engines.items():
        if name == "wm_api":
            continue
        try:
            e.stop()
        except Exception:
            pass
    state.stop()
    runtime.stop()
    kernel.shutdown()
