"""
Unit tests for review prompt building.

Tests cover:
- Prompt structure and content
- Context inclusion
- Response parsing logic
"""

import pytest

from app.prompts.review import (
    REVIEW_SYSTEM_PROMPT,
    build_review_prompt,
    parse_review_response,
)


class TestBuildReviewPrompt:
    """Test review prompt construction."""

    def test_includes_user_request(self):
        """Prompt includes the user's original request."""
        prompt = build_review_prompt(
            draft_output="Fixed the bug",
            user_request="Fix the authentication bug",
            files_modified=[],
            code_context="",
            tool_results=[],
        )

        assert "<user_request>" in prompt
        assert "Fix the authentication bug" in prompt

    def test_includes_agent_response(self):
        """Prompt includes the agent's draft output."""
        draft = "I fixed the bug by adding a null check on line 42."
        prompt = build_review_prompt(
            draft_output=draft,
            user_request="Fix the bug",
            files_modified=[],
            code_context="",
            tool_results=[],
        )

        assert "<agent_response>" in prompt
        assert "null check" in prompt

    def test_includes_files_modified(self):
        """Prompt includes list of modified files."""
        prompt = build_review_prompt(
            draft_output="Fixed",
            user_request="Fix bug",
            files_modified=["app/auth.py", "app/models.py"],
            code_context="",
            tool_results=[],
        )

        assert "<files_modified>" in prompt
        assert "app/auth.py" in prompt
        assert "app/models.py" in prompt

    def test_includes_tool_results(self):
        """Prompt includes tool execution results."""
        tool_results = [
            "[✓] file_tool: Written 50 lines to app/auth.py",
            "[✓] git_tool: Committed changes",
        ]
        prompt = build_review_prompt(
            draft_output="Fixed",
            user_request="Fix bug",
            files_modified=["app/auth.py"],
            code_context="",
            tool_results=tool_results,
        )

        assert "<tool_execution>" in prompt
        assert "file_tool" in prompt
        assert "git_tool" in prompt

    def test_includes_codebase_context(self):
        """Prompt includes relevant code context."""
        context = "```python\\nclass User:\\n    def __init__(self):\\n        pass\\n```"
        prompt = build_review_prompt(
            draft_output="Fixed",
            user_request="Fix bug",
            files_modified=[],
            code_context=context,
            tool_results=[],
        )

        assert "<codebase_context>" in prompt
        assert "class User" in prompt

    def test_skips_empty_context(self):
        """Prompt omits empty context block."""
        prompt = build_review_prompt(
            draft_output="Fixed",
            user_request="Fix bug",
            files_modified=[],
            code_context="No relevant code context found.",
            tool_results=[],
        )

        assert "<codebase_context>" not in prompt

    def test_includes_review_task(self):
        """Prompt includes the review task instructions."""
        prompt = build_review_prompt(
            draft_output="Fixed",
            user_request="Fix bug",
            files_modified=[],
            code_context="",
            tool_results=[],
        )

        assert "<task>" in prompt
        assert "APPROVED" in prompt or "NEEDS_REVISION" in prompt

    def test_complete_prompt_structure(self):
        """Complete prompt has all sections in correct order."""
        prompt = build_review_prompt(
            draft_output="Fixed the authentication bug.",
            user_request="Fix auth bug",
            files_modified=["app/auth.py"],
            code_context="class Auth: pass",
            tool_results=["[✓] file_tool: Success"],
        )

        # Check order: request → response → files → tools → context → task
        req_pos = prompt.index("<user_request>")
        resp_pos = prompt.index("<agent_response>")
        files_pos = prompt.index("<files_modified>")
        tools_pos = prompt.index("<tool_execution>")
        context_pos = prompt.index("<codebase_context>")
        task_pos = prompt.index("<task>")

        assert req_pos < resp_pos < files_pos < tools_pos < context_pos < task_pos


class TestSystemPrompt:
    """Test review system prompt."""

    def test_system_prompt_is_adversarial(self):
        """System prompt emphasizes adversarial review."""
        assert "ADVERSARIAL" in REVIEW_SYSTEM_PROMPT.upper()
        assert "problems" in REVIEW_SYSTEM_PROMPT.lower()

    def test_system_prompt_lists_criteria(self):
        """System prompt lists review criteria."""
        prompt_lower = REVIEW_SYSTEM_PROMPT.lower()
        assert "correctness" in prompt_lower
        assert "security" in prompt_lower
        assert "performance" in prompt_lower
        assert "maintainability" in prompt_lower

    def test_system_prompt_defines_response_format(self):
        """System prompt defines expected response format."""
        assert "APPROVED" in REVIEW_SYSTEM_PROMPT
        assert "NEEDS_REVISION" in REVIEW_SYSTEM_PROMPT


class TestParseReviewResponse:
    """Test parsing of review responses."""

    def test_parse_simple_approved(self):
        """Parse simple APPROVED response."""
        status, feedback = parse_review_response("APPROVED")
        assert status == "approved"
        assert feedback == ""

    def test_parse_lowercase_approved(self):
        """Parse lowercase approved."""
        status, feedback = parse_review_response("approved")
        assert status == "approved"

    def test_parse_approved_with_extra_text(self):
        """Parse APPROVED with explanation."""
        response = "APPROVED\\n\\nThe fix is correct and handles edge cases well."
        status, feedback = parse_review_response(response)
        assert status == "approved"

    def test_parse_needs_revision_with_feedback(self):
        """Parse NEEDS_REVISION with issues listed."""
        response = """NEEDS_REVISION

Issue 1: Missing error handling
Why: Network calls can fail
Fix: Add try-catch block

Issue 2: No input validation
Why: Malicious input could cause issues
Fix: Validate user input"""

        status, feedback = parse_review_response(response)
        assert status == "needs_revision"
        assert "Issue 1" in feedback
        assert "Issue 2" in feedback
        assert "error handling" in feedback

    def test_parse_needs_revision_with_space(self):
        """Parse 'NEEDS REVISION' (with space)."""
        response = "NEEDS REVISION\\n\\nThere's a bug."
        status, feedback = parse_review_response(response)
        assert status == "needs_revision"
        assert "bug" in feedback

    def test_parse_mixed_case(self):
        """Parse mixed case variations."""
        status1, _ = parse_review_response("Needs_Revision\\n\\nIssue found")
        status2, _ = parse_review_response("needs revision\\n\\nProblem")

        assert status1 == "needs_revision"
        assert status2 == "needs_revision"

    def test_parse_ambiguous_with_critical_words(self):
        """Ambiguous response with 'bug' keyword parsed as needs_revision."""
        response = "I found a bug in the implementation."
        status, feedback = parse_review_response(response)
        assert status == "needs_revision"

    def test_parse_ambiguous_with_security_keyword(self):
        """Response mentioning 'security' parsed as needs_revision."""
        response = "There's a potential security issue here."
        status, feedback = parse_review_response(response)
        assert status == "needs_revision"

    def test_parse_ambiguous_positive_as_approved(self):
        """Positive ambiguous response defaults to approved."""
        response = "Looks good to me."
        status, feedback = parse_review_response(response)
        assert status == "approved"

    def test_parse_empty_response(self):
        """Empty response defaults to approved."""
        status, feedback = parse_review_response("")
        assert status == "approved"
        assert feedback == ""

    def test_critical_word_list_coverage(self):
        """All critical words trigger needs_revision."""
        critical_words = ["bug", "error", "issue", "problem", "security", "vulnerability", "incorrect"]

        for word in critical_words:
            response = f"The code has a {word}."
            status, _ = parse_review_response(response)
            assert status == "needs_revision", f"Word '{word}' should trigger needs_revision"
