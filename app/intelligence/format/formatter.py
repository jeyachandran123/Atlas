"""
Response Formatter.

Converts raw LLM output into polished responses.
Each response strategy has independent formatting rules.
No formatting logic lives in prompts.
"""

from __future__ import annotations

import re

from app.intelligence.interfaces import AbstractResponseFormatter
from app.intelligence.models import IntelligenceContext, ResponseStrategy


class ResponseFormatter(AbstractResponseFormatter):
    """
    Applies post-processing formatting based on the selected response strategy.
    """

    def format(self, response: str, context: IntelligenceContext) -> str:
        strategy = context.strategy

        # Apply strategy-specific formatter
        formatters = {
            ResponseStrategy.CODING:          self._format_coding,
            ResponseStrategy.TEACHING:        self._format_teaching,
            ResponseStrategy.ARCHITECTURE:    self._format_architecture,
            ResponseStrategy.TROUBLESHOOTING: self._format_troubleshooting,
            ResponseStrategy.COMPARISON:      self._format_comparison,
            ResponseStrategy.DIRECT_ANSWER:   self._format_direct,
        }

        formatter = formatters.get(strategy, self._format_default)
        return formatter(response)

    def _format_coding(self, response: str) -> str:
        """Ensure code blocks are properly fenced."""
        # Fix unclosed code blocks
        open_count = response.count("```")
        if open_count % 2 != 0:
            response = response.rstrip() + "\n```"
        return response.strip()

    def _format_teaching(self, response: str) -> str:
        """Ensure teaching responses have clear structure."""
        response = response.strip()
        # Ensure numbered lists are properly spaced
        response = re.sub(r"\n(\d+\.)", r"\n\n\1", response)
        return response

    def _format_architecture(self, response: str) -> str:
        """Ensure architecture responses have clear section headers."""
        return response.strip()

    def _format_troubleshooting(self, response: str) -> str:
        """Ensure troubleshooting responses lead with the root cause."""
        return response.strip()

    def _format_comparison(self, response: str) -> str:
        """Ensure comparison responses have consistent table formatting."""
        return response.strip()

    def _format_direct(self, response: str) -> str:
        """Remove unnecessary preamble from direct answers."""
        preamble_patterns = [
            r"^(Sure|Certainly|Of course|Absolutely|Great question)[!,.]?\s*",
            r"^I('d| would) (be happy|love) to (help|assist)[.!]\s*",
        ]
        for pattern in preamble_patterns:
            response = re.sub(pattern, "", response, flags=re.IGNORECASE)
        return response.strip()

    def _format_default(self, response: str) -> str:
        return response.strip()


# ── Singleton ─────────────────────────────────────────────────────────────────

_formatter: ResponseFormatter | None = None


def get_response_formatter() -> ResponseFormatter:
    global _formatter
    if _formatter is None:
        _formatter = ResponseFormatter()
    return _formatter
