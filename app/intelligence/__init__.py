"""
Atlas Conversation Intelligence Engine.

Pipeline:
    User Message
        → IntentDetector
        → ComplexityAnalyzer
        → ConversationAnalyzer
        → PolicyEngine
        → PersonaEngine
        → ResponseStrategyPlanner
        → UserContextBuilder
        → ToolPlanner
        → DynamicPromptComposer
        → LLM
        → ResponseReviewer
        → ResponseFormatter
        → User
"""


def get_engine():
    """Lazy factory — avoids import chain at module load time."""
    from app.intelligence.engine import ConversationIntelligenceEngine
    return ConversationIntelligenceEngine()


__all__ = ["get_engine"]
