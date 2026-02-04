"""Tests for the feedback and personality evolution module."""

import pytest
from radar.feedback import (
    store_feedback,
    get_unprocessed_feedback,
    get_all_feedback,
    mark_feedback_processed,
    get_feedback_summary,
    store_suggestion,
    get_pending_suggestions,
    get_suggestion,
    approve_suggestion,
    reject_suggestion,
    delete_feedback,
)
from radar.semantic import _get_connection


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Clean up test data before and after each test."""
    conn = _get_connection()
    conn.execute("DELETE FROM feedback WHERE conversation_id LIKE 'test-%'")
    conn.execute("DELETE FROM personality_suggestions WHERE personality_name LIKE 'test-%'")
    conn.commit()
    conn.close()
    yield
    conn = _get_connection()
    conn.execute("DELETE FROM feedback WHERE conversation_id LIKE 'test-%'")
    conn.execute("DELETE FROM personality_suggestions WHERE personality_name LIKE 'test-%'")
    conn.commit()
    conn.close()


class TestFeedback:
    """Tests for feedback storage and retrieval."""

    def test_store_feedback_positive(self):
        """Test storing positive feedback."""
        fb_id = store_feedback(
            conversation_id="test-conv-1",
            message_index=0,
            sentiment="positive",
            response_content="Great response",
            user_comment="Very helpful!",
        )
        assert fb_id > 0

    def test_store_feedback_negative(self):
        """Test storing negative feedback."""
        fb_id = store_feedback(
            conversation_id="test-conv-2",
            message_index=1,
            sentiment="negative",
        )
        assert fb_id > 0

    def test_store_feedback_invalid_sentiment(self):
        """Test that invalid sentiment raises error."""
        with pytest.raises(ValueError):
            store_feedback(
                conversation_id="test-conv-3",
                message_index=0,
                sentiment="neutral",
            )

    def test_get_unprocessed_feedback(self):
        """Test retrieving unprocessed feedback."""
        store_feedback("test-conv-4", 0, "positive")
        store_feedback("test-conv-5", 0, "negative")

        feedback = get_unprocessed_feedback()
        test_feedback = [f for f in feedback if f["conversation_id"].startswith("test-")]
        assert len(test_feedback) == 2

    def test_mark_feedback_processed(self):
        """Test marking feedback as processed."""
        fb_id = store_feedback("test-conv-6", 0, "positive")
        count = mark_feedback_processed([fb_id])
        assert count == 1

        # Verify it's no longer in unprocessed
        feedback = get_unprocessed_feedback()
        ids = [f["id"] for f in feedback]
        assert fb_id not in ids

    def test_get_feedback_summary(self):
        """Test feedback summary statistics."""
        store_feedback("test-conv-7", 0, "positive")
        store_feedback("test-conv-8", 0, "positive")
        store_feedback("test-conv-9", 0, "negative")

        summary = get_feedback_summary()
        assert summary["total"] >= 3
        assert summary["positive"] >= 2
        assert summary["negative"] >= 1

    def test_delete_feedback(self):
        """Test deleting feedback."""
        fb_id = store_feedback("test-conv-10", 0, "positive")
        result = delete_feedback(fb_id)
        assert result is True

        # Verify it's gone
        result = delete_feedback(fb_id)
        assert result is False


class TestSuggestions:
    """Tests for personality suggestion management."""

    def test_store_suggestion(self):
        """Test storing a suggestion."""
        sug_id = store_suggestion(
            personality_name="test-personality",
            suggestion_type="add",
            content="Be more concise.",
            reason="Users prefer shorter responses",
            source="feedback_analysis",
        )
        assert sug_id > 0

    def test_store_suggestion_invalid_type(self):
        """Test that invalid suggestion type raises error."""
        with pytest.raises(ValueError):
            store_suggestion(
                personality_name="test-personality",
                suggestion_type="delete",
                content="Something",
            )

    def test_get_pending_suggestions(self):
        """Test retrieving pending suggestions."""
        store_suggestion("test-personality", "add", "Content 1")
        store_suggestion("test-personality", "modify", "Content 2")

        pending = get_pending_suggestions()
        test_suggestions = [s for s in pending if s["personality_name"] == "test-personality"]
        assert len(test_suggestions) == 2

    def test_get_suggestion(self):
        """Test retrieving a specific suggestion."""
        sug_id = store_suggestion("test-personality", "add", "Content")

        suggestion = get_suggestion(sug_id)
        assert suggestion is not None
        assert suggestion["personality_name"] == "test-personality"
        assert suggestion["status"] == "pending"

    def test_reject_suggestion(self):
        """Test rejecting a suggestion."""
        sug_id = store_suggestion("test-personality", "add", "Content")

        success, message = reject_suggestion(sug_id, "Not needed")
        assert success is True

        suggestion = get_suggestion(sug_id)
        assert suggestion["status"] == "rejected"

    def test_reject_already_rejected(self):
        """Test rejecting an already-rejected suggestion."""
        sug_id = store_suggestion("test-personality", "add", "Content")
        reject_suggestion(sug_id)

        success, message = reject_suggestion(sug_id)
        assert success is False
        assert "already" in message.lower()


class TestTools:
    """Tests for the feedback-related tools."""

    def test_suggest_personality_update_tool(self):
        """Test the suggest_personality_update tool."""
        from radar.tools.suggest_personality import suggest_personality_update

        result = suggest_personality_update(
            personality_name="test-tool-personality",
            suggestion_type="add",
            content="Be friendly.",
            reason="Test reason",
        )
        assert "created" in result.lower() or "pending" in result.lower()

        # Clean up
        conn = _get_connection()
        conn.execute("DELETE FROM personality_suggestions WHERE personality_name = 'test-tool-personality'")
        conn.commit()
        conn.close()

    def test_suggest_personality_update_invalid_type(self):
        """Test the tool with invalid suggestion type."""
        from radar.tools.suggest_personality import suggest_personality_update

        result = suggest_personality_update(
            personality_name="test-personality",
            suggestion_type="invalid",
            content="Content",
        )
        assert "invalid" in result.lower()

    def test_analyze_feedback_insufficient(self):
        """Test analyze_feedback with insufficient data."""
        from radar.tools.analyze_feedback import analyze_feedback

        result = analyze_feedback()
        assert "insufficient" in result.lower() or "need at least" in result.lower()
