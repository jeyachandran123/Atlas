"""
Unit tests for ReviewAgent.

Tests cover:
- Review decision logic (when to run review)
- Response parsing (APPROVED vs NEEDS_REVISION)
- State updates (review_status, review_feedback)
- Edge cases (empty output, errors, max revisions)
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from app.agents.review_agent import (
    ReviewAgent,
    check_revision_decision,
    should_review_decision,
)
from app.agents.state import initial_state
from app.prompts.review import parse_review_response


class TestReviewAgent:
    """Test ReviewAgent core functionality."""

    @pytest.fixture
    def agent(self):
        return ReviewAgent()

    @pytest.fixture
    def base_state(self):
        return initial_state(
            user_message="Fix the bug in auth.py",
            conversation_id="conv-123",
            user_id="user-456",
            org_id="org-789",
            request_id="req-001",
            repo_id="repo-999",
        )

    @pytest.mark.asyncio
    async def test_run_with_approved_response(self, agent, base_state):
        """ReviewAgent approves good code."""
        state = {
            **base_state,
            "intent": "fix",
            "draft_output": "Fixed the authentication bug by adding null check.",
            "files_modified": ["app/auth.py"],
            "tool_results": [],
        }

        with patch.object(agent._ollama, "chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "APPROVED"

            result = await agent.run(state)

            assert result["review_status"] == "approved"
            assert result["review_feedback"] == ""
            assert mock_chat.called

    @pytest.mark.asyncio
    async def test_run_with_needs_revision_response(self, agent, base_state):
        """ReviewAgent identifies issues."""
        state = {
            **base_state,
            "intent": "fix",
            "draft_output": "Fixed by removing the check.",
            "files_modified": ["app/auth.py"],
            "tool_results": [],
        }

        feedback = """Issue 1: Removing the null check will cause crashes
Why: The user object can be None during logout
Fix: Add proper null handling"""

        with patch.object(agent._ollama, "chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = f"NEEDS_REVISION\\n\\n{feedback}"

            result = await agent.run(state)

            assert result["review_status"] == "needs_revision"
            assert "null" in result["review_feedback"].lower()
            assert len(result["review_feedback"]) > 0

    @pytest.mark.asyncio
    async def test_run_skips_if_no_draft_output(self, agent, base_state):
        """ReviewAgent skips if there's nothing to review."""
        state = {
            **base_state,
            "draft_output": "",
            "files_modified": [],
        }

        result = await agent.run(state)

        assert result["review_status"] == "skipped"
        assert result["review_feedback"] == ""

    @pytest.mark.asyncio
    async def test_run_handles_ollama_error(self, agent, base_state):
        """ReviewAgent handles LLM errors gracefully."""
        state = {
            **base_state,
            "intent": "fix",
            "draft_output": "Fixed the bug",
            "files_modified": ["app/auth.py"],
        }

        with patch.object(agent._ollama, "chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = Exception("Ollama connection failed")

            result = await agent.run(state)

            assert result["review_status"] == "skipped"
            assert "Review failed" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_run_includes_tool_results_in_review(self, agent, base_state):
        """ReviewAgent receives tool execution context."""
        from app.shared.schemas import ToolResult

        state = {
            **base_state,
            "intent": "fix",
            "draft_output": "Applied the fix",
            "files_modified": ["app/auth.py"],
            "tool_results": [
                ToolResult(
                    tool_name="file_tool",
                    success=True,
                    output="Written 50 lines to app/auth.py",
                    metadata={"path": "app/auth.py"},
                )
            ],
        }

        with patch.object(agent._ollama, "chat", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "APPROVED"

            result = await agent.run(state)

            # Check that tool results were included in the prompt
            call_args = mock_chat.call_args
            prompt = call_args.kwargs["prompt"]
            assert "file_tool" in prompt
            assert "app/auth.py" in prompt


class TestShouldRunReview:
    """Test review decision logic."""

    @pytest.fixture
    def agent(self):
        return ReviewAgent()

    def test_should_run_for_fix_intent(self, agent):
        """Review runs for fix intent."""
        state = initial_state(
            "Fix the bug", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["intent"] = "fix"
        state["revision_count"] = 0

        assert agent.should_run_review(state) is True

    def test_should_run_for_test_intent(self, agent):
        """Review runs for test intent."""
        state = initial_state(
            "Write tests", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["intent"] = "test"
        state["revision_count"] = 0

        assert agent.should_run_review(state) is True

    def test_should_run_for_review_intent(self, agent):
        """Review runs when explicitly requested."""
        state = initial_state(
            "Review this code", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["intent"] = "review"
        state["revision_count"] = 0

        assert agent.should_run_review(state) is True

    def test_should_not_run_for_explain_intent(self, agent):
        """Review skips for explain intent."""
        state = initial_state(
            "Explain this code", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["intent"] = "explain"
        state["revision_count"] = 0

        assert agent.should_run_review(state) is False

    def test_should_not_run_for_search_intent(self, agent):
        """Review skips for search intent."""
        state = initial_state(
            "Find the function", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["intent"] = "search"
        state["revision_count"] = 0

        assert agent.should_run_review(state) is False

    def test_should_run_if_files_modified(self, agent):
        """Review runs if files were modified, regardless of intent."""
        state = initial_state(
            "Generate code", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["intent"] = "code"
        state["files_modified"] = ["app/models.py"]
        state["revision_count"] = 0

        assert agent.should_run_review(state) is True

    def test_should_not_run_if_max_revisions_reached(self, agent):
        """Review stops after max revisions."""
        state = initial_state(
            "Fix the bug", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["intent"] = "fix"
        state["revision_count"] = 2
        state["max_revisions"] = 2

        assert agent.should_run_review(state) is False


class TestShouldReviewDecision:
    """Test the LangGraph decision function."""

    def test_returns_review_for_fix_intent(self):
        """Decision function returns 'review' for fix intent."""
        state = initial_state(
            "Fix bug", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["intent"] = "fix"

        result = should_review_decision(state)
        assert result == "review"

    def test_returns_skip_for_explain_intent(self):
        """Decision function returns 'skip' for explain intent."""
        state = initial_state(
            "Explain code", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["intent"] = "explain"

        result = should_review_decision(state)
        assert result == "skip"


class TestCheckRevisionDecision:
    """Test the revision decision function."""

    def test_finalise_if_approved(self):
        """Finalise if review approved."""
        state = initial_state(
            "Fix bug", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["review_status"] = "approved"

        result = check_revision_decision(state)
        assert result == "finalise"

    def test_finalise_if_skipped(self):
        """Finalise if review was skipped."""
        state = initial_state(
            "Explain", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["review_status"] = "skipped"

        result = check_revision_decision(state)
        assert result == "finalise"

    def test_revise_if_needs_revision_and_under_limit(self):
        """Revise if review says needs_revision and under max."""
        state = initial_state(
            "Fix bug", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["review_status"] = "needs_revision"
        state["revision_count"] = 0
        state["max_revisions"] = 2

        result = check_revision_decision(state)
        assert result == "revise"

    def test_finalise_if_needs_revision_but_at_limit(self):
        """Finalise if needs revision but hit max revisions."""
        state = initial_state(
            "Fix bug", "conv-1", "user-1", "org-1", "req-1", "repo-1"
        )
        state["review_status"] = "needs_revision"
        state["revision_count"] = 2
        state["max_revisions"] = 2

        result = check_revision_decision(state)
        assert result == "finalise"


class TestParseReviewResponse:
    """Test review response parsing."""

    def test_parse_approved(self):
        """Parse APPROVED response."""
        response = "APPROVED"
        status, feedback = parse_review_response(response)

        assert status == "approved"
        assert feedback == ""

    def test_parse_approved_with_trailing_text(self):
        """Parse APPROVED with explanation."""
        response = "APPROVED\\n\\nThe fix looks good and handles all edge cases."
        status, feedback = parse_review_response(response)

        assert status == "approved"

    def test_parse_needs_revision(self):
        """Parse NEEDS_REVISION with feedback."""
        response = """NEEDS_REVISION

Issue 1: Missing null check
Why: User can be null
Fix: Add if (user == null) check"""

        status, feedback = parse_review_response(response)

        assert status == "needs_revision"
        assert "Issue 1" in feedback
        assert "null check" in feedback

    def test_parse_needs_revision_alternate_format(self):
        """Parse NEEDS REVISION (with space)."""
        response = "NEEDS REVISION\\n\\nThe code has a bug."
        status, feedback = parse_review_response(response)

        assert status == "needs_revision"
        assert "bug" in feedback

    def test_parse_ambiguous_response_with_critical_words(self):
        """Parse response with bug/error keywords as needs_revision."""
        response = "There is a security vulnerability in this code."
        status, feedback = parse_review_response(response)

        assert status == "needs_revision"
        assert "security" in feedback.lower()

    def test_parse_ambiguous_response_without_critical_words(self):
        """Parse unclear response as approved by default."""
        response = "The code looks okay."
        status, feedback = parse_review_response(response)

        assert status == "approved"
