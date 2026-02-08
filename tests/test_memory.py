"""Tests for radar/memory.py — JSONL conversation storage."""

import json
import time
import uuid

import pytest

from radar.memory import (
    add_message,
    count_tool_calls_today,
    create_conversation,
    delete_conversation,
    get_messages,
    get_messages_for_display,
    get_recent_activity,
    get_recent_conversations,
    messages_to_api_format,
)


class TestCreateConversation:
    """create_conversation generates unique IDs and files."""

    def test_returns_valid_uuid(self, isolated_data_dir):
        cid = create_conversation()
        uuid.UUID(cid)  # Raises on invalid

    def test_creates_jsonl_file(self, isolated_data_dir):
        cid = create_conversation()
        path = isolated_data_dir / "conversations" / f"{cid}.jsonl"
        assert path.exists()

    def test_file_initially_empty(self, isolated_data_dir):
        cid = create_conversation()
        path = isolated_data_dir / "conversations" / f"{cid}.jsonl"
        assert path.read_text() == ""

    def test_unique_ids(self, isolated_data_dir):
        ids = {create_conversation() for _ in range(10)}
        assert len(ids) == 10


class TestAddMessage:
    """add_message appends JSONL lines."""

    def test_appends_message(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hello")
        msgs = get_messages(cid)
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "hello"

    def test_returns_line_number_1_indexed(self, isolated_data_dir):
        cid = create_conversation()
        n1 = add_message(cid, "user", "first")
        n2 = add_message(cid, "assistant", "second")
        assert n1 == 1
        assert n2 == 2

    def test_stores_tool_calls(self, isolated_data_dir):
        cid = create_conversation()
        tc = [{"function": {"name": "weather", "arguments": {"city": "NYC"}}}]
        add_message(cid, "assistant", tool_calls=tc)
        msgs = get_messages(cid)
        assert msgs[0]["tool_calls"] == tc

    def test_stores_tool_call_id(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "tool", "result text", tool_call_id="call_1")
        msgs = get_messages(cid)
        assert msgs[0]["tool_call_id"] == "call_1"

    def test_stores_timestamp(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hi")
        msgs = get_messages(cid)
        assert "timestamp" in msgs[0]
        assert "T" in msgs[0]["timestamp"]  # ISO format


class TestGetMessages:
    """get_messages reads JSONL with IDs."""

    def test_returns_empty_for_nonexistent(self, isolated_data_dir):
        msgs = get_messages("nonexistent-id")
        assert msgs == []

    def test_correct_order(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "first")
        add_message(cid, "assistant", "second")
        add_message(cid, "user", "third")
        msgs = get_messages(cid)
        assert [m["content"] for m in msgs] == ["first", "second", "third"]

    def test_adds_id_field(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "msg")
        msgs = get_messages(cid)
        assert msgs[0]["id"] == 1

    def test_limit_returns_last_n(self, isolated_data_dir):
        cid = create_conversation()
        for i in range(5):
            add_message(cid, "user", f"msg{i}")
        msgs = get_messages(cid, limit=2)
        assert len(msgs) == 2
        assert msgs[0]["content"] == "msg3"
        assert msgs[1]["content"] == "msg4"

    def test_skips_blank_lines(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hello")
        # Manually inject a blank line
        path = isolated_data_dir / "conversations" / f"{cid}.jsonl"
        with open(path, "a") as f:
            f.write("\n")
        add_message(cid, "assistant", "world")
        msgs = get_messages(cid)
        assert len(msgs) == 2


class TestGetRecentConversations:
    """get_recent_conversations returns sorted summaries."""

    def test_empty_when_no_conversations(self, isolated_data_dir):
        assert get_recent_conversations() == []

    def test_sorted_by_mtime(self, isolated_data_dir):
        cid1 = create_conversation()
        add_message(cid1, "user", "older")
        time.sleep(0.05)
        cid2 = create_conversation()
        add_message(cid2, "user", "newer")
        convs = get_recent_conversations()
        assert convs[0]["id"] == cid2
        assert convs[1]["id"] == cid1

    def test_limit_works(self, isolated_data_dir):
        for _ in range(5):
            cid = create_conversation()
            add_message(cid, "user", "msg")
        assert len(get_recent_conversations(limit=3)) == 3

    def test_preview_is_first_user_message(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "system", "system prompt")
        add_message(cid, "user", "What is the weather?")
        convs = get_recent_conversations()
        assert convs[0]["preview"] == "What is the weather?"

    def test_preview_truncated_to_100(self, isolated_data_dir):
        cid = create_conversation()
        long_msg = "x" * 200
        add_message(cid, "user", long_msg)
        convs = get_recent_conversations()
        assert len(convs[0]["preview"]) == 100


class TestGetRecentConversationsEnriched:
    """Enriched get_recent_conversations: type, tool_count, search, pagination."""

    def test_returns_type_chat_by_default(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hello")
        convs = get_recent_conversations()
        assert convs[0]["type"] == "chat"

    def test_returns_type_heartbeat_when_id_matches(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "heartbeat check")
        # Write heartbeat_conversation file
        hb_file = isolated_data_dir / "heartbeat_conversation"
        hb_file.write_text(cid)
        convs = get_recent_conversations()
        assert convs[0]["type"] == "heartbeat"

    def test_tool_count_from_tool_calls(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "check weather")
        add_message(cid, "assistant", None, tool_calls=[
            {"function": {"name": "weather", "arguments": {}}, "id": "c1"},
        ])
        add_message(cid, "assistant", None, tool_calls=[
            {"function": {"name": "search", "arguments": {}}, "id": "c2"},
            {"function": {"name": "recall", "arguments": {}}, "id": "c3"},
        ])
        convs = get_recent_conversations()
        assert convs[0]["tool_count"] == 3

    def test_summary_is_first_user_message(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "system", "you are a bot")
        add_message(cid, "user", "What is the weather?")
        add_message(cid, "user", "Second question")
        convs = get_recent_conversations()
        assert convs[0]["summary"] == "What is the weather?"

    def test_timestamp_formatted_for_display(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hi")
        convs = get_recent_conversations()
        ts = convs[0]["timestamp"]
        # Should be space-separated, not T
        assert "T" not in ts
        assert " " in ts

    def test_offset_pagination(self, isolated_data_dir):
        ids = []
        for i in range(5):
            cid = create_conversation()
            add_message(cid, "user", f"msg {i}")
            ids.append(cid)
            time.sleep(0.05)
        # ids are in creation order; get_recent returns newest first
        convs = get_recent_conversations(limit=2, offset=2)
        assert len(convs) == 2
        # offset=2 skips the 2 newest, returns the 3rd and 4th newest
        assert convs[0]["id"] == ids[2]
        assert convs[1]["id"] == ids[1]

    def test_type_filter_chat_excludes_heartbeat(self, isolated_data_dir):
        cid_chat = create_conversation()
        add_message(cid_chat, "user", "regular chat")
        cid_hb = create_conversation()
        add_message(cid_hb, "user", "heartbeat msg")
        hb_file = isolated_data_dir / "heartbeat_conversation"
        hb_file.write_text(cid_hb)
        convs = get_recent_conversations(type_filter="chat")
        ids = [c["id"] for c in convs]
        assert cid_chat in ids
        assert cid_hb not in ids

    def test_type_filter_heartbeat_only(self, isolated_data_dir):
        cid_chat = create_conversation()
        add_message(cid_chat, "user", "regular chat")
        cid_hb = create_conversation()
        add_message(cid_hb, "user", "heartbeat msg")
        hb_file = isolated_data_dir / "heartbeat_conversation"
        hb_file.write_text(cid_hb)
        convs = get_recent_conversations(type_filter="heartbeat")
        assert len(convs) == 1
        assert convs[0]["id"] == cid_hb

    def test_search_matches_content_case_insensitive(self, isolated_data_dir):
        cid1 = create_conversation()
        add_message(cid1, "user", "Tell me about Python")
        cid2 = create_conversation()
        add_message(cid2, "user", "What is the weather?")
        convs = get_recent_conversations(search="python")
        assert len(convs) == 1
        assert convs[0]["id"] == cid1

    def test_search_returns_empty_when_no_match(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hello world")
        convs = get_recent_conversations(search="zzzznotfound")
        assert convs == []

    def test_backward_compat_fields_present(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "test message")
        convs = get_recent_conversations()
        conv = convs[0]
        assert "id" in conv
        assert "created_at" in conv
        assert "preview" in conv
        assert conv["preview"] == conv["summary"]

    def test_tool_count_zero_when_no_tool_calls(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "just chatting")
        add_message(cid, "assistant", "hello there")
        convs = get_recent_conversations()
        assert convs[0]["tool_count"] == 0


class TestMessagesToApiFormat:
    """messages_to_api_format strips extra fields."""

    def test_strips_extra_fields(self):
        msgs = [
            {"role": "user", "content": "hi", "timestamp": "2025-01-01", "id": 1, "tool_calls": None},
        ]
        result = messages_to_api_format(msgs)
        assert result == [{"role": "user", "content": "hi"}]
        assert "timestamp" not in result[0]
        assert "id" not in result[0]

    def test_skips_null_content(self):
        msgs = [{"role": "assistant", "content": None, "tool_calls": None}]
        result = messages_to_api_format(msgs)
        assert "content" not in result[0]

    def test_preserves_tool_calls(self):
        tc = [{"function": {"name": "t", "arguments": {}}}]
        msgs = [{"role": "assistant", "content": "ok", "tool_calls": tc}]
        result = messages_to_api_format(msgs)
        assert result[0]["tool_calls"] == tc


class TestGetMessagesForDisplay:
    """get_messages_for_display transforms for the web UI."""

    def test_skips_tool_role(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hi")
        add_message(cid, "assistant", "calling tool", tool_calls=[
            {"function": {"name": "weather", "arguments": {}}, "id": "call_1"},
        ])
        add_message(cid, "tool", "sunny", tool_call_id="call_1")
        add_message(cid, "assistant", "It's sunny!")
        display = get_messages_for_display(cid)
        roles = [m["role"] for m in display]
        assert "tool" not in roles

    def test_associates_results_by_tool_call_id(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "assistant", None, tool_calls=[
            {"function": {"name": "weather", "arguments": {"city": "NYC"}}, "id": "call_1"},
        ])
        add_message(cid, "tool", "72°F sunny", tool_call_id="call_1")
        display = get_messages_for_display(cid)
        tc = display[0]["tool_calls"][0]
        assert tc["name"] == "weather"
        assert tc["result"] == "72°F sunny"

    def test_positional_fallback(self, isolated_data_dir):
        cid = create_conversation()
        # No tool_call_id on the tool message
        add_message(cid, "assistant", None, tool_calls=[
            {"function": {"name": "search", "arguments": {"q": "test"}}},
        ])
        add_message(cid, "tool", "search results")
        display = get_messages_for_display(cid)
        tc = display[0]["tool_calls"][0]
        assert tc["result"] == "search results"

    def test_display_format_structure(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hello")
        add_message(cid, "assistant", "world")
        display = get_messages_for_display(cid)
        assert len(display) == 2
        assert display[0]["role"] == "user"
        assert display[0]["content"] == "hello"
        assert "id" in display[0]


class TestCountToolCallsToday:
    """count_tool_calls_today scans today's conversations."""

    def test_empty_no_conversations(self, isolated_data_dir):
        assert count_tool_calls_today() == 0

    def test_with_tool_calls(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hello")
        add_message(cid, "assistant", None, tool_calls=[
            {"function": {"name": "weather", "arguments": {"city": "NYC"}}, "id": "call_1"},
        ])
        add_message(cid, "assistant", None, tool_calls=[
            {"function": {"name": "search", "arguments": {"q": "test"}}, "id": "call_2"},
            {"function": {"name": "recall", "arguments": {"q": "mem"}}, "id": "call_3"},
        ])
        assert count_tool_calls_today() == 3

    def test_ignores_yesterday(self, isolated_data_dir):
        cid = create_conversation()
        # Write a message with yesterday's timestamp directly
        conv_path = isolated_data_dir / "conversations" / f"{cid}.jsonl"
        old_msg = json.dumps({
            "timestamp": "2020-01-01T10:00:00",
            "role": "assistant",
            "content": None,
            "tool_calls": [{"function": {"name": "weather", "arguments": {}}}],
            "tool_call_id": None,
        })
        with open(conv_path, "w") as f:
            f.write(old_msg + "\n")
        # File was modified today but the timestamp in the message is old
        assert count_tool_calls_today() == 0


class TestGetRecentActivity:
    """get_recent_activity returns a unified timeline."""

    def test_mixed_types(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "What is the weather?")
        add_message(cid, "assistant", None, tool_calls=[
            {"function": {"name": "weather", "arguments": {"city": "NYC"}}, "id": "call_1"},
        ])
        add_message(cid, "tool", "72F sunny", tool_call_id="call_1")
        add_message(cid, "assistant", "It's sunny!")

        activity = get_recent_activity()
        types = [a["type"] for a in activity]
        assert "chat" in types
        assert "tool" in types
        # User message should have content preview
        chat_items = [a for a in activity if a["type"] == "chat"]
        assert chat_items[0]["message"] == "What is the weather?"
        # Tool call should have name
        tool_items = [a for a in activity if a["type"] == "tool"]
        assert "weather" in tool_items[0]["message"]

    def test_limit(self, isolated_data_dir):
        cid = create_conversation()
        for i in range(15):
            add_message(cid, "user", f"message {i}")
        activity = get_recent_activity(limit=5)
        assert len(activity) == 5

    def test_empty_no_conversations(self, isolated_data_dir):
        assert get_recent_activity() == []

    def test_sorted_descending(self, isolated_data_dir):
        cid = create_conversation()
        # Write messages with explicit timestamps to ensure different minutes
        conv_path = isolated_data_dir / "conversations" / f"{cid}.jsonl"
        with open(conv_path, "w") as f:
            f.write(json.dumps({"timestamp": "2025-06-01T10:00:00", "role": "user", "content": "first", "tool_calls": None, "tool_call_id": None}) + "\n")
            f.write(json.dumps({"timestamp": "2025-06-01T11:00:00", "role": "user", "content": "second", "tool_calls": None, "tool_call_id": None}) + "\n")
        activity = get_recent_activity()
        # Should be sorted by time descending (second message has later timestamp)
        assert activity[0]["message"] == "second"
        assert activity[1]["message"] == "first"


class TestDeleteConversation:
    """delete_conversation removes JSONL files and cleans up feedback."""

    def test_deletes_jsonl_file(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hello")
        conv_path = isolated_data_dir / "conversations" / f"{cid}.jsonl"
        assert conv_path.exists()
        success, msg = delete_conversation(cid)
        assert success is True
        assert not conv_path.exists()

    def test_returns_false_for_nonexistent(self, isolated_data_dir):
        success, msg = delete_conversation("nonexistent-id")
        assert success is False
        assert "not found" in msg

    def test_protects_heartbeat_conversation(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "heartbeat msg")
        hb_file = isolated_data_dir / "heartbeat_conversation"
        hb_file.write_text(cid)
        success, msg = delete_conversation(cid)
        assert success is False
        assert "heartbeat" in msg.lower()
        # File should still exist
        conv_path = isolated_data_dir / "conversations" / f"{cid}.jsonl"
        assert conv_path.exists()

    def test_cleans_up_feedback_records(self, isolated_data_dir):
        from radar.feedback import store_feedback
        from radar.semantic import _get_connection

        cid = create_conversation()
        add_message(cid, "user", "hello")
        add_message(cid, "assistant", "world")
        store_feedback(cid, 1, "positive", "world")

        # Verify feedback exists
        conn = _get_connection()
        rows = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE conversation_id = ?", (cid,)
        ).fetchone()
        assert rows[0] == 1
        conn.close()

        delete_conversation(cid)

        # Verify feedback cleaned up
        conn = _get_connection()
        rows = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE conversation_id = ?", (cid,)
        ).fetchone()
        assert rows[0] == 0
        conn.close()

    def test_get_messages_empty_after_delete(self, isolated_data_dir):
        cid = create_conversation()
        add_message(cid, "user", "hello")
        assert len(get_messages(cid)) == 1
        delete_conversation(cid)
        assert get_messages(cid) == []
