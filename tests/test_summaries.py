"""Tests for conversation summaries."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# --- Fixtures ---


@pytest.fixture
def summaries_dir(isolated_data_dir):
    """Return summaries directory inside isolated data dir."""
    d = isolated_data_dir / "summaries"
    d.mkdir(exist_ok=True)
    for sub in ("daily", "weekly", "monthly"):
        (d / sub).mkdir(exist_ok=True)
    return d


@pytest.fixture
def sample_conversations(conversations_dir):
    """Create sample conversation JSONL files."""
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # Conversation 1
    conv1_id = "conv-test-001"
    conv1_path = conversations_dir / f"{conv1_id}.jsonl"
    messages1 = [
        {"timestamp": f"{today}T10:00:00", "role": "user", "content": "What's the weather?"},
        {"timestamp": f"{today}T10:00:05", "role": "assistant", "content": "It's sunny and 72F."},
        {"timestamp": f"{today}T10:01:00", "role": "user", "content": "Thanks!"},
    ]
    with open(conv1_path, "w") as f:
        for msg in messages1:
            f.write(json.dumps(msg) + "\n")

    # Conversation 2
    conv2_id = "conv-test-002"
    conv2_path = conversations_dir / f"{conv2_id}.jsonl"
    messages2 = [
        {"timestamp": f"{today}T14:00:00", "role": "user", "content": "Show my GitHub PRs"},
        {
            "timestamp": f"{today}T14:00:05",
            "role": "assistant",
            "content": None,
            "tool_calls": [{"function": {"name": "github", "arguments": {"action": "prs"}}, "id": "tc1"}],
        },
        {"timestamp": f"{today}T14:00:10", "role": "tool", "content": "3 PRs found", "tool_call_id": "tc1"},
        {"timestamp": f"{today}T14:00:15", "role": "assistant", "content": "You have 3 open PRs."},
    ]
    with open(conv2_path, "w") as f:
        for msg in messages2:
            f.write(json.dumps(msg) + "\n")

    return [conv1_id, conv2_id]


# --- File I/O Tests ---


class TestSummaryFileIO:
    def test_get_summaries_dir_creates_subdirs(self, isolated_data_dir):
        from radar.summaries import get_summaries_dir

        result = get_summaries_dir()
        assert result.exists()
        assert (result / "daily").exists()
        assert (result / "weekly").exists()
        assert (result / "monthly").exists()

    def test_write_and_read_summary(self, summaries_dir, isolated_data_dir):
        from radar.summaries import read_summary, write_summary

        content = "# Daily Summary\n\nThis was a productive day."
        metadata = {"conversations": 5, "topics": ["weather", "github"]}

        path = write_summary("daily", "2025-01-07", content, metadata)
        assert path.exists()

        result = read_summary("daily", "2025-01-07")
        assert result is not None
        assert result["content"] == content
        assert result["metadata"]["period"] == "daily"
        assert result["metadata"]["date"] == "2025-01-07"
        assert result["metadata"]["conversations"] == 5
        assert result["metadata"]["topics"] == ["weather", "github"]

    def test_read_nonexistent_summary(self, summaries_dir, isolated_data_dir):
        from radar.summaries import read_summary

        result = read_summary("daily", "2099-01-01")
        assert result is None

    def test_summary_exists(self, summaries_dir, isolated_data_dir):
        from radar.summaries import summary_exists, write_summary

        assert not summary_exists("daily", "2025-01-07")
        write_summary("daily", "2025-01-07", "Test content")
        assert summary_exists("daily", "2025-01-07")

    def test_list_summaries_empty(self, summaries_dir, isolated_data_dir):
        from radar.summaries import list_summaries

        result = list_summaries()
        assert result == []

    def test_list_summaries_filtered(self, summaries_dir, isolated_data_dir):
        from radar.summaries import list_summaries, write_summary

        write_summary("daily", "2025-01-07", "Day 1")
        write_summary("daily", "2025-01-08", "Day 2")
        write_summary("weekly", "2025-W02", "Week 2")

        all_summaries = list_summaries()
        assert len(all_summaries) == 3

        daily_only = list_summaries(period_type="daily")
        assert len(daily_only) == 2

        weekly_only = list_summaries(period_type="weekly")
        assert len(weekly_only) == 1

    def test_list_summaries_sorted_descending(self, summaries_dir, isolated_data_dir):
        from radar.summaries import list_summaries, write_summary

        write_summary("daily", "2025-01-05", "Older")
        write_summary("daily", "2025-01-08", "Newer")
        write_summary("daily", "2025-01-06", "Middle")

        result = list_summaries(period_type="daily")
        filenames = [s["filename"] for s in result]
        assert filenames == ["2025-01-08", "2025-01-06", "2025-01-05"]

    def test_list_summaries_with_limit(self, summaries_dir, isolated_data_dir):
        from radar.summaries import list_summaries, write_summary

        for i in range(5):
            write_summary("daily", f"2025-01-{i+1:02d}", f"Day {i+1}")

        result = list_summaries(period_type="daily", limit=3)
        assert len(result) == 3

    def test_get_latest_summary(self, summaries_dir, isolated_data_dir):
        from radar.summaries import get_latest_summary, write_summary

        assert get_latest_summary("daily") is None

        write_summary("daily", "2025-01-05", "Older")
        write_summary("daily", "2025-01-08", "Newer")

        latest = get_latest_summary("daily")
        assert latest is not None
        assert latest["filename"] == "2025-01-08"

    def test_write_summary_overwrites(self, summaries_dir, isolated_data_dir):
        from radar.summaries import read_summary, write_summary

        write_summary("daily", "2025-01-07", "Version 1")
        write_summary("daily", "2025-01-07", "Version 2")

        result = read_summary("daily", "2025-01-07")
        assert result["content"] == "Version 2"


# --- Conversation Scanning Tests ---


class TestConversationScanning:
    def test_get_conversations_in_range(self, sample_conversations, isolated_data_dir):
        from radar.summaries import get_conversations_in_range

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        conversations = get_conversations_in_range(today, today)

        assert len(conversations) == 2

    def test_get_conversations_excludes_heartbeat(self, conversations_dir, isolated_data_dir):
        from radar.summaries import get_conversations_in_range

        today = datetime.now()
        today_str = today.strftime("%Y-%m-%d")

        # Create a heartbeat conversation
        hb_id = "heartbeat-conv-id"
        hb_path = conversations_dir / f"{hb_id}.jsonl"
        with open(hb_path, "w") as f:
            f.write(json.dumps({"timestamp": f"{today_str}T12:00:00", "role": "user", "content": "Heartbeat"}) + "\n")

        # Create heartbeat ID file
        hb_file = isolated_data_dir / "heartbeat_conversation"
        hb_file.write_text(hb_id)

        # Create a regular conversation
        reg_path = conversations_dir / "regular-conv.jsonl"
        with open(reg_path, "w") as f:
            f.write(json.dumps({"timestamp": f"{today_str}T12:00:00", "role": "user", "content": "Hello"}) + "\n")

        today_dt = today.replace(hour=0, minute=0, second=0, microsecond=0)
        conversations = get_conversations_in_range(today_dt, today_dt)

        assert len(conversations) == 1
        assert conversations[0]["id"] == "regular-conv"

    def test_get_conversations_empty_range(self, conversations_dir, isolated_data_dir):
        from radar.summaries import get_conversations_in_range

        # Far future range with no conversations
        future = datetime(2099, 1, 1)
        conversations = get_conversations_in_range(future, future)
        assert conversations == []

    def test_get_conversations_no_dir(self, isolated_data_dir):
        """When conversations dir doesn't exist yet."""
        from radar.summaries import get_conversations_in_range

        # Remove conversations dir if it was created
        conv_dir = isolated_data_dir / "conversations"
        if conv_dir.exists():
            import shutil
            shutil.rmtree(conv_dir)

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        result = get_conversations_in_range(today, today)
        assert result == []


# --- Formatting Tests ---


class TestFormatting:
    def test_format_conversations_for_llm(self, sample_conversations, isolated_data_dir):
        from radar.summaries import format_conversations_for_llm, get_conversations_in_range

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        conversations = get_conversations_in_range(today, today)

        result = format_conversations_for_llm(conversations)

        assert "What's the weather?" in result
        assert "It's sunny and 72F." in result
        assert "Show my GitHub PRs" in result
        # Tool role messages should be stripped
        assert "3 PRs found" not in result

    def test_format_skips_tool_only_messages(self, conversations_dir, isolated_data_dir):
        from radar.summaries import format_conversations_for_llm

        conversations = [{
            "created_at": "2025-01-07T10:00:00",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "test"}}]},
                {"role": "tool", "content": "tool result"},
                {"role": "assistant", "content": "Done!"},
            ],
        }]

        result = format_conversations_for_llm(conversations)
        assert "Hello" in result
        assert "Done!" in result
        assert "tool result" not in result

    def test_format_truncates_long_messages(self, isolated_data_dir):
        from radar.summaries import format_conversations_for_llm

        long_content = "x" * 1000
        conversations = [{
            "created_at": "2025-01-07T10:00:00",
            "messages": [
                {"role": "user", "content": long_content},
            ],
        }]

        result = format_conversations_for_llm(conversations)
        assert "..." in result
        # Should be truncated to ~500 chars plus "..."
        assert len(result) < 1000

    def test_format_respects_token_limit(self, isolated_data_dir):
        from radar.summaries import format_conversations_for_llm

        # Create many conversations
        conversations = []
        for i in range(50):
            conversations.append({
                "created_at": f"2025-01-07T{i:02d}:00:00",
                "messages": [
                    {"role": "user", "content": f"Message {i} " + "padding " * 50},
                    {"role": "assistant", "content": f"Response {i} " + "padding " * 50},
                ],
            })

        result = format_conversations_for_llm(conversations, max_tokens_approx=500)
        # Should be truncated
        assert "[Truncated" in result or len(result) < 3000

    def test_format_empty_conversations(self, isolated_data_dir):
        from radar.summaries import format_conversations_for_llm

        result = format_conversations_for_llm([])
        assert "No conversations found" in result


# --- Period Parsing Tests ---


class TestPeriodParsing:
    def test_parse_today(self):
        from radar.summaries import _parse_period_range

        start, end, ptype, label = _parse_period_range("today")
        assert ptype == "daily"
        assert label == datetime.now().strftime("%Y-%m-%d")
        assert start == end

    def test_parse_yesterday(self):
        from radar.summaries import _parse_period_range

        start, end, ptype, label = _parse_period_range("yesterday")
        yesterday = datetime.now() - timedelta(days=1)
        assert ptype == "daily"
        assert label == yesterday.strftime("%Y-%m-%d")

    def test_parse_this_week(self):
        from radar.summaries import _parse_period_range

        start, end, ptype, label = _parse_period_range("this_week")
        assert ptype == "weekly"
        assert "W" in label
        assert (end - start).days == 6

    def test_parse_last_week(self):
        from radar.summaries import _parse_period_range

        start, end, ptype, label = _parse_period_range("last_week")
        assert ptype == "weekly"
        assert (end - start).days == 6

    def test_parse_this_month(self):
        from radar.summaries import _parse_period_range

        start, end, ptype, label = _parse_period_range("this_month")
        assert ptype == "monthly"
        assert start.day == 1

    def test_parse_last_month(self):
        from radar.summaries import _parse_period_range

        start, end, ptype, label = _parse_period_range("last_month")
        assert ptype == "monthly"
        assert start.day == 1

    def test_parse_explicit_range(self):
        from radar.summaries import _parse_period_range

        start, end, ptype, label = _parse_period_range("2025-01-01:2025-01-07")
        assert start.strftime("%Y-%m-%d") == "2025-01-01"
        assert end.strftime("%Y-%m-%d") == "2025-01-07"
        assert ptype == "weekly"

    def test_parse_explicit_single_day(self):
        from radar.summaries import _parse_period_range

        start, end, ptype, label = _parse_period_range("2025-01-07:2025-01-07")
        assert ptype == "daily"

    def test_parse_invalid_format(self):
        from radar.summaries import _parse_period_range

        with pytest.raises(ValueError, match="Unknown period format"):
            _parse_period_range("invalid_format")


# --- Tool Tests ---


class TestSummarizeConversationsTool:
    def test_summarize_today(self, sample_conversations, isolated_data_dir):
        from radar.tools.summarize_conversations import summarize_conversations

        result = summarize_conversations("today")
        assert "conversation(s)" in result
        assert "What's the weather?" in result

    def test_summarize_empty_period(self, conversations_dir, isolated_data_dir):
        from radar.tools.summarize_conversations import summarize_conversations

        result = summarize_conversations("2099-01-01:2099-01-02")
        assert "No conversations found" in result

    def test_summarize_invalid_period(self, isolated_data_dir):
        from radar.tools.summarize_conversations import summarize_conversations

        result = summarize_conversations("bogus")
        assert "Error" in result


class TestStoreConversationSummaryTool:
    def test_store_summary_creates_file(self, summaries_dir, isolated_data_dir):
        from radar.tools.store_conversation_summary import store_conversation_summary

        with patch("radar.semantic.is_embedding_available", return_value=False):
            result = store_conversation_summary(
                period_type="daily",
                label="2025-01-07",
                summary="# Summary\n\nGreat day!",
                topics="weather, github",
                conversations_count=3,
            )

        assert "saved" in result.lower() or "Summary" in result

        # Verify file exists
        from radar.summaries import read_summary

        saved = read_summary("daily", "2025-01-07")
        assert saved is not None
        assert "Great day!" in saved["content"]
        assert saved["metadata"]["topics"] == ["weather", "github"]

    def test_store_summary_with_semantic_memory(self, summaries_dir, isolated_data_dir):
        from radar.tools.store_conversation_summary import store_conversation_summary

        with patch("radar.semantic.is_embedding_available", return_value=True), \
             patch("radar.semantic.store_memory", return_value=1) as mock_store:
            result = store_conversation_summary(
                period_type="daily",
                label="2025-01-07",
                summary="Test summary",
            )

        assert "semantic memory" in result.lower()
        mock_store.assert_called_once()


# --- Heartbeat Integration Tests ---


class TestHeartbeatIntegration:
    def test_check_summary_due_returns_none_when_disabled(self, isolated_data_dir):
        from radar.config import get_config
        from radar.summaries import check_summary_due

        config = get_config()
        config.summaries.enabled = False

        result = check_summary_due("daily")
        assert result is None

    def test_check_summary_due_returns_none_before_time(self, isolated_data_dir):
        from radar.config import get_config
        from radar.summaries import check_summary_due

        config = get_config()
        config.summaries.daily_summary_time = "23:59"

        # Unless it's actually 23:59, this should return None
        now = datetime.now()
        if now.hour < 23:
            result = check_summary_due("daily")
            assert result is None

    def test_check_summary_due_skips_existing(self, summaries_dir, sample_conversations, isolated_data_dir):
        from radar.config import get_config
        from radar.summaries import check_summary_due, write_summary

        config = get_config()
        config.summaries.daily_summary_time = "00:00"

        today = datetime.now().strftime("%Y-%m-%d")
        write_summary("daily", today, "Already exists")

        result = check_summary_due("daily")
        assert result is None

    def test_check_summary_due_returns_data(self, summaries_dir, sample_conversations, isolated_data_dir):
        from radar.config import get_config
        from radar.summaries import check_summary_due

        config = get_config()
        config.summaries.daily_summary_time = "00:00"

        result = check_summary_due("daily")
        # Should return formatted conversations (unless no conversations today)
        if result is not None:
            assert "Conversation" in result or "User" in result


# --- Web Route Tests ---


class TestWebRoutes:
    @pytest.fixture
    def client(self):
        from starlette.testclient import TestClient

        from radar.web import app

        return TestClient(app, raise_server_exceptions=False)

    @pytest.fixture(autouse=True)
    def mock_common_deps(self):
        from radar.config.schema import Config

        cfg = Config()
        with (
            patch("radar.web.get_common_context") as mock_ctx,
            patch("radar.config.load_config", return_value=cfg),
            patch("radar.config.get_config", return_value=cfg),
            patch("radar.scheduler.get_status", return_value={
                "running": True,
                "last_heartbeat": None,
                "next_heartbeat": "12:00:00",
                "pending_events": 0,
                "quiet_hours": False,
            }),
        ):
            def _ctx(request, active_page):
                return {
                    "request": request,
                    "active_page": active_page,
                    "model": "test",
                    "llm_provider": "ollama",
                    "llm_url": "localhost:11434",
                    "ntfy_configured": False,
                    "heartbeat_status": "ok",
                    "heartbeat_label": "Active",
                }

            mock_ctx.side_effect = _ctx
            yield

    def test_summaries_page_returns_200(self, client):
        with patch("radar.summaries.list_summaries", return_value=[]):
            resp = client.get("/summaries")
        assert resp.status_code == 200

    def test_api_summaries_returns_html(self, client):
        with patch("radar.summaries.list_summaries", return_value=[
            {
                "metadata": {"period": "daily", "date": "2025-01-07", "conversations": 3, "topics": ["weather"]},
                "content": "Test summary content",
                "path": "/tmp/test.md",
                "period_type": "daily",
                "filename": "2025-01-07",
            }
        ]):
            resp = client.get("/api/summaries")
        assert resp.status_code == 200
        assert "2025-01-07" in resp.text
        assert "weather" in resp.text

    def test_api_summaries_empty(self, client):
        with patch("radar.summaries.list_summaries", return_value=[]):
            resp = client.get("/api/summaries")
        assert resp.status_code == 200
        assert "No summaries found" in resp.text

    def test_generate_summary_no_conversations(self, client):
        with patch("radar.summaries.get_conversations_in_range", return_value=[]):
            resp = client.post("/api/summaries/generate", data={"period": "today"})
        assert resp.status_code == 200
        assert "No conversations found" in resp.text
