"""
Prompt Enhancer — delegates to PromptIntelligenceEngine.

Static template injection has been removed.
All prompt intelligence is now handled by app/intelligence/prompting/.

This file is kept for backward compatibility with existing imports.
"""

from app.intelligence.prompting.enhancer_bridge import (
    enhance_user_message,
    _is_non_code_topic,
    _is_adult_content,
    _is_off_topic_for_business,
)

__all__ = [
    "enhance_user_message",
    "_is_non_code_topic",
    "_is_adult_content",
    "_is_off_topic_for_business",
]
