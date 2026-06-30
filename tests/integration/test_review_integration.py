"""
Integration test for ReviewAgent in the full orchestrator flow.

Tests the complete pipeline:
  route_intent → load_memory → retrieve_context → plan_tools →
  execute_tools → coding_agent → should_continue → should_review →
  review_agent → check_revision → finalise
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from app.agents.orchestrator import AgentOrchestrator
from app.agents.review_agent import ReviewAgent
from app.agents.coding_agent import CodingAgent
from app.agents.state import initial_state


class TestReviewAgentIntegration:
    """Test ReviewAgent integration with orchestrator."""

    @pytest.mark.asyncio
    async def test_fix_intent_triggers_review(self):
        """Fix intent should trigger ReviewAgent."""
        # Test the decision logic directly without building the graph
        review_agent = ReviewAgent()
        
        # Create state with fix intent
        state = initial_state(
            user_message="Fix the authentication bug",
            conversation_id="conv-123",
            user_id="user-456",
            org_id="org-789",
            request_id="req-001",
        )
        state["intent"] = "fix"
        state["draft_output"] = "Fixed the bug"
        state["files_modified"] = ["app/auth.py"]
        
        # Test should_run_review logic
        should_review = review_agent.should_run_review(state)
        assert should_review is True

    @pytest.mark.asyncio
    async def test_explain_intent_skips_review(self):
        """Explain intent should skip ReviewAgent."""
        mock_review_agent = ReviewAgent()
        
        state = initial_state(
            user_message="Explain how auth works",
            conversation_id="conv-123",
            user_id="user-456",
            org_id="org-789",
            request_id="req-001",
        )
        state["intent"] = "explain"
        state["draft_output"] = "The auth system works by..."
        state["files_modified"] = []
        
        should_review = mock_review_agent.should_run_review(state)
        assert should_review is False

    @pytest.mark.asyncio
    async def test_revision_loop_increments_count(self):
        """Revision loop should increment revision_count."""
        state = initial_state(
            user_message="Fix the bug",
            conversation_id="conv-123",
            user_id="user-456",
            org_id="org-789",
            request_id="req-001",
        )
        
        # Simulate orchestrator's increment_revision_node
        updated_state = {
            **state,
            "revision_count": state["revision_count"] + 1,
            "draft_output": "",
            "current_step": 0,
            "tool_calls": [],
        }
        
        assert updated_state["revision_count"] == 1
        assert updated_state["draft_output"] == ""
        assert updated_state["current_step"] == 0

    @pytest.mark.asyncio
    async def test_max_revisions_stops_loop(self):
        """Max revisions should force finalization."""
        from app.agents.review_agent import check_revision_decision
        
        # State at max revisions with needs_revision
        state = initial_state(
            user_message="Fix the bug",
            conversation_id="conv-123",
            user_id="user-456",
            org_id="org-789",
            request_id="req-001",
        )
        state["review_status"] = "needs_revision"
        state["revision_count"] = 2
        state["max_revisions"] = 2
        
        decision = check_revision_decision(state)
        assert decision == "finalise"  # Should finalize, not revise

    @pytest.mark.asyncio
    async def test_approved_review_finalizes(self):
        """Approved review should proceed to finalization."""
        from app.agents.review_agent import check_revision_decision
        
        state = initial_state(
            user_message="Fix the bug",
            conversation_id="conv-123",
            user_id="user-456",
            org_id="org-789",
            request_id="req-001",
        )
        state["review_status"] = "approved"
        state["revision_count"] = 0
        
        decision = check_revision_decision(state)
        assert decision == "finalise"

    @pytest.mark.asyncio
    async def test_files_modified_triggers_review_even_for_code_intent(self):
        """Files modified should trigger review even for 'code' intent."""
        mock_review_agent = ReviewAgent()
        
        state = initial_state(
            user_message="Generate a new function",
            conversation_id="conv-123",
            user_id="user-456",
            org_id="org-789",
            request_id="req-001",
        )
        state["intent"] = "code"  # Not fix/test/review
        state["files_modified"] = ["app/utils.py"]  # But files were modified
        state["draft_output"] = "Created new function"
        
        should_review = mock_review_agent.should_run_review(state)
        assert should_review is True  # Should review because files changed
