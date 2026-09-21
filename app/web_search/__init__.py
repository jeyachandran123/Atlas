"""Web search for the chat assistant.

The assistant searches when a question needs information it cannot hold — what
happened this week, what something costs now, what an API actually returns — and
answers from the pages it read, showing them as sources the user can open.

Every failure in here is a missing improvement, never a lost reply: no API key,
no budget left, a timeout or a malformed decision all fall back to answering
without the web.
"""

from app.web_search.schemas import SearchOutcome, SearchPlan, WebSource

__all__ = ["SearchOutcome", "SearchPlan", "WebSource"]
