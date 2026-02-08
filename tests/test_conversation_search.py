"""Tests for radar/conversation_search.py — semantic conversation search."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from radar.memory import add_message, create_conversation


# --- Text Conversion Tests ---


class TestConversationToText:
    def test_basic_user_assistant(self, isolated_data_dir):
        from radar.conversation_search import conversation_to_text

        cid = create_conversation()
        add_message(cid, "user", "What's the weather?")
        add_message(cid, "assistant", "It's sunny and 72F.")

        text = conversation_to_text(cid)
        assert "## User" in text
        assert "What's the weather?" in text
        assert "## Assistant" in text
        assert "It's sunny and 72F." in text

    def test_skips_tool_role_messages(self, isolated_data_dir):
        from radar.conversation_search import conversation_to_text

        cid = create_conversation()
        add_message(cid, "user", "Check weather")
        add_message(
            cid,
            "assistant",
            None,
            tool_calls=[{
                "function": {"name": "weather", "arguments": {"location": "Seattle"}},
                "id": "tc1",
            }],
        )
        add_message(cid, "tool", "Temperature: 52F", tool_call_id="tc1")
        add_message(cid, "assistant", "It's 52F in Seattle.")

        text = conversation_to_text(cid)
        # Tool role raw output should not appear
        assert "Temperature: 52F" not in text
        # But assistant summary should
        assert "52F in Seattle" in text

    def test_includes_tool_call_names(self, isolated_data_dir):
        from radar.conversation_search import conversation_to_text

        cid = create_conversation()
        add_message(cid, "user", "Check weather")
        add_message(
            cid,
            "assistant",
            "Here's the weather.",
            tool_calls=[{
                "function": {"name": "weather", "arguments": {"location": "Portland"}},
                "id": "tc1",
            }],
        )

        text = conversation_to_text(cid)
        assert "[Tool: weather(" in text
        assert "Portland" in text

    def test_empty_conversation_returns_empty(self, isolated_data_dir):
        from radar.conversation_search import conversation_to_text

        cid = create_conversation()
        text = conversation_to_text(cid)
        assert text == ""

    def test_header_has_id_and_date(self, isolated_data_dir):
        from radar.conversation_search import conversation_to_text

        cid = create_conversation()
        add_message(cid, "user", "Hello")

        text = conversation_to_text(cid)
        assert f"# Conversation {cid[:8]}" in text
        # Date should be present (YYYY-MM-DD format from timestamp)
        lines = text.split("\n")
        assert any("20" in line and "-" in line for line in lines[:2])


# --- Indexing Tests ---


class TestConversationIndexing:
    def test_creates_chunks(self, isolated_data_dir):
        from radar.conversation_search import (
            ensure_conversations_collection,
            index_conversations,
        )
        from radar.documents import _get_connection

        cid = create_conversation()
        add_message(cid, "user", "Tell me about Python programming")
        add_message(cid, "assistant", "Python is a versatile language.")

        result = index_conversations()
        assert result["indexed"] >= 1

        conn = _get_connection()
        count = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
        conn.close()
        assert count > 0

    def test_skips_unchanged(self, isolated_data_dir):
        from radar.conversation_search import index_conversations

        cid = create_conversation()
        add_message(cid, "user", "Hello")
        add_message(cid, "assistant", "Hi there!")

        result1 = index_conversations()
        assert result1["indexed"] >= 1

        result2 = index_conversations()
        assert result2["indexed"] == 0
        assert result2["skipped"] >= 1

    def test_reindexes_on_change(self, isolated_data_dir):
        from radar.conversation_search import index_conversations

        cid = create_conversation()
        add_message(cid, "user", "Hello")
        add_message(cid, "assistant", "Hi!")

        result1 = index_conversations()
        assert result1["indexed"] >= 1

        # Add a new message (changes file hash)
        add_message(cid, "user", "What is machine learning?")
        add_message(cid, "assistant", "ML is a subset of AI.")

        result2 = index_conversations()
        assert result2["indexed"] >= 1

    def test_indexes_multiple_conversations(self, isolated_data_dir):
        from radar.conversation_search import index_conversations

        for _ in range(3):
            cid = create_conversation()
            add_message(cid, "user", "Test message")
            add_message(cid, "assistant", "Response")

        result = index_conversations()
        assert result["indexed"] == 3

    def test_removes_stale_entries(self, isolated_data_dir):
        from radar.conversation_search import index_conversations

        cid = create_conversation()
        add_message(cid, "user", "Temp message")
        add_message(cid, "assistant", "Response")

        index_conversations()

        # Delete the conversation file
        conv_path = isolated_data_dir / "conversations" / f"{cid}.jsonl"
        conv_path.unlink()

        result = index_conversations()
        assert result["removed"] >= 1


# --- Search Tests ---


class TestConversationSearch:
    def test_finds_by_keyword(self, isolated_data_dir):
        from radar.conversation_search import index_conversations, search_conversations

        cid = create_conversation()
        add_message(cid, "user", "Tell me about quantum computing")
        add_message(cid, "assistant", "Quantum computing uses qubits.")

        index_conversations()

        with patch("radar.semantic.is_embedding_available", return_value=False):
            results = search_conversations("quantum")
        assert len(results) > 0
        assert any("quantum" in r["content"].lower() for r in results)

    def test_returns_conversation_id(self, isolated_data_dir):
        from radar.conversation_search import index_conversations, search_conversations

        cid = create_conversation()
        add_message(cid, "user", "Unique xylophone discussion")
        add_message(cid, "assistant", "Xylophones are percussion instruments.")

        index_conversations()

        with patch("radar.semantic.is_embedding_available", return_value=False):
            results = search_conversations("xylophone")
        assert len(results) > 0
        assert results[0]["conversation_id"] == cid

    def test_no_matches_returns_empty(self, isolated_data_dir):
        from radar.conversation_search import index_conversations, search_conversations

        cid = create_conversation()
        add_message(cid, "user", "Hello")
        add_message(cid, "assistant", "Hi!")

        index_conversations()

        with patch("radar.semantic.is_embedding_available", return_value=False):
            results = search_conversations("xyzzyplugh")
        assert results == []


# --- Remove Index Tests ---


class TestRemoveConversationIndex:
    def test_removes_chunks_and_file_row(self, isolated_data_dir):
        from radar.conversation_search import (
            index_conversations,
            remove_conversation_index,
        )
        from radar.documents import _get_connection

        cid = create_conversation()
        add_message(cid, "user", "Data to be removed")
        add_message(cid, "assistant", "Will be cleaned up.")

        index_conversations()

        # Verify data exists
        conn = _get_connection()
        count = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
        conn.close()
        assert count > 0

        remove_conversation_index(cid)

        conn = _get_connection()
        count = conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0]
        conn.close()
        assert count == 0

    def test_noop_for_nonindexed_conversation(self, isolated_data_dir):
        from radar.conversation_search import remove_conversation_index

        # Should not raise
        remove_conversation_index("nonexistent-id")
