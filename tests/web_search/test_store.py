"""Sources belong to their message, and go when it goes."""

from __future__ import annotations

from app.db.models import MessageSource


class TestSourcesDieWithTheirMessage:
    """Deleting a conversation, editing a prompt and deleting a message all
    returned 500 once an answer had sources: three call sites delete messages
    and none of them knew about this table.

    The fix is the database's, not the caller's — so this asserts the rule is
    still declared, because removing it breaks three endpoints at once and
    nothing else would notice until a user tried to delete a chat.
    """

    def test_the_foreign_key_cascades(self):
        fk = next(iter(MessageSource.__table__.c.message_id.foreign_keys))
        assert fk.ondelete == "CASCADE"

    def test_it_points_at_messages(self):
        fk = next(iter(MessageSource.__table__.c.message_id.foreign_keys))
        assert fk.column.table.name == "messages"


class TestStoredShape:
    """What is stored is what a card shows, and nothing more."""

    def test_page_text_is_not_a_column(self):
        """The extract is used to write the reply and then discarded; keeping
        copies of other people's pages is not this app's business."""
        columns = set(MessageSource.__table__.c.keys())
        assert "content" not in columns and "extract" not in columns

    def test_a_card_can_be_rebuilt_from_the_row(self):
        columns = set(MessageSource.__table__.c.keys())
        assert {"url", "title", "domain", "favicon_url", "thumbnail_url",
                "position", "show_image", "query"} <= columns
