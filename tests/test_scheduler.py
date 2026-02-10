"""Tests for radar/scheduler.py — heartbeat scheduling, quiet hours, event queuing."""

from datetime import datetime, time
from unittest.mock import MagicMock, patch

import pytest

import radar.scheduler as mod


class MockDatetime(datetime):
    """datetime subclass that overrides now() but preserves strptime()."""

    _fixed_now: datetime | None = None

    @classmethod
    def now(cls, tz=None):
        if cls._fixed_now is not None:
            return cls._fixed_now
        return super().now(tz)

    @classmethod
    def strptime(cls, date_string, fmt):
        return datetime.strptime(date_string, fmt)


@pytest.fixture(autouse=True)
def reset_scheduler_globals():
    """Reset module-level globals before and after each test."""
    mod._scheduler = None
    mod._event_queue = []
    mod._last_heartbeat = None
    yield
    # Shut down any scheduler that was started during the test
    if mod._scheduler is not None:
        try:
            mod._scheduler.shutdown(wait=False)
        except Exception:
            pass
    mod._scheduler = None
    mod._event_queue = []
    mod._last_heartbeat = None


def _make_config(start="23:00", end="07:00", interval=15):
    """Build a mock config with heartbeat settings."""
    cfg = MagicMock()
    cfg.heartbeat.quiet_hours_start = start
    cfg.heartbeat.quiet_hours_end = end
    cfg.heartbeat.interval_minutes = interval
    return cfg


# ---------------------------------------------------------------------------
# _is_quiet_hours()
# ---------------------------------------------------------------------------


class TestIsQuietHours:
    def _call(self, hour, minute, start="23:00", end="07:00"):
        MockDatetime._fixed_now = datetime(2025, 1, 15, hour, minute, 0)
        with (
            patch.object(mod, "datetime", MockDatetime),
            patch.object(mod, "get_config", return_value=_make_config(start, end)),
        ):
            return mod._is_quiet_hours()

    def test_quiet_hours_late_night(self):
        assert self._call(23, 30) is True

    def test_quiet_hours_early_morning(self):
        assert self._call(3, 0) is True

    def test_quiet_hours_outside_overnight(self):
        assert self._call(12, 0) is False

    def test_quiet_hours_at_start_boundary(self):
        assert self._call(23, 0) is True

    def test_quiet_hours_at_end_boundary(self):
        assert self._call(7, 0) is True

    def test_quiet_hours_same_day_window(self):
        assert self._call(14, 0, start="13:00", end="17:00") is True

    def test_quiet_hours_outside_same_day(self):
        assert self._call(12, 0, start="13:00", end="17:00") is False

    def test_quiet_hours_invalid_format(self):
        MockDatetime._fixed_now = datetime(2025, 1, 15, 12, 0, 0)
        with (
            patch.object(mod, "datetime", MockDatetime),
            patch.object(
                mod, "get_config",
                return_value=_make_config(start="invalid", end="07:00"),
            ),
        ):
            assert mod._is_quiet_hours() is False


# ---------------------------------------------------------------------------
# _build_heartbeat_message()
# ---------------------------------------------------------------------------


class TestBuildHeartbeatMessage:
    @pytest.fixture(autouse=True)
    def _fix_time(self):
        MockDatetime._fixed_now = datetime(2025, 6, 1, 10, 30, 0)
        with patch.object(mod, "datetime", MockDatetime):
            yield

    def test_build_message_empty(self):
        msg = mod._build_heartbeat_message([])
        assert "No new events" in msg
        assert "2025-06-01 10:30:00" in msg

    def test_build_message_without_action(self):
        events = [
            {"type": "file_created", "data": {"description": "New file", "path": "/tmp/foo"}}
        ]
        msg = mod._build_heartbeat_message(events)
        assert "- New file: /tmp/foo" in msg

    def test_build_message_with_action(self):
        events = [
            {
                "type": "file_created",
                "data": {
                    "description": "Downloaded PDF",
                    "path": "/tmp/doc.pdf",
                    "action": "Summarize this document",
                },
            }
        ]
        msg = mod._build_heartbeat_message(events)
        assert "- Downloaded PDF" in msg
        assert "File: /tmp/doc.pdf" in msg
        assert "Action: Summarize this document" in msg

    def test_build_message_multiple(self):
        events = [
            {"type": "a", "data": {"description": "First", "path": "/a"}},
            {"type": "b", "data": {"description": "Second", "path": "/b"}},
        ]
        msg = mod._build_heartbeat_message(events)
        assert "- First: /a" in msg
        assert "- Second: /b" in msg

    def test_build_message_fallback_to_type(self):
        events = [{"type": "custom_type", "data": {"path": "/x"}}]
        msg = mod._build_heartbeat_message(events)
        assert "- custom_type: /x" in msg


# ---------------------------------------------------------------------------
# _log_heartbeat()
# ---------------------------------------------------------------------------


class TestLogHeartbeat:
    def test_log_heartbeat_calls_log(self):
        with patch("radar.logging.log") as mock_log:
            mod._log_heartbeat("test message", foo="bar")
            mock_log.assert_called_once_with("info", "test message", foo="bar")

    def test_log_heartbeat_swallows_exceptions(self):
        with patch("radar.logging.log", side_effect=RuntimeError("boom")):
            mod._log_heartbeat("test")  # Should not raise


# ---------------------------------------------------------------------------
# _heartbeat_tick()
# ---------------------------------------------------------------------------


class TestHeartbeatTick:
    @pytest.fixture
    def _mock_tick_deps(self):
        """Patch all external dependencies of _heartbeat_tick."""
        cfg = _make_config()
        cfg.heartbeat.personality = ""
        cfg.documents.enabled = True
        with (
            patch.object(mod, "_is_quiet_hours", return_value=False) as m_quiet,
            patch.object(mod, "_log_heartbeat") as m_log,
            patch.object(mod, "_check_config_reload") as m_reload,
            patch.object(mod, "get_config", return_value=cfg) as m_cfg,
            patch.object(mod, "_get_heartbeat_conversation_id", return_value="conv-1"),
            patch("radar.scheduled_tasks.get_due_tasks", return_value=[]) as m_due,
            patch("radar.scheduled_tasks.mark_task_executed") as m_mark,
            patch("radar.url_monitors.get_due_monitors", return_value=[]) as m_monitors,
            patch("radar.summaries.check_summary_due", return_value=None) as m_summary,
            patch("radar.documents.ensure_summaries_collection") as m_ensure_summ,
            patch("radar.documents.list_collections", return_value=[]) as m_list_coll,
            patch("radar.conversation_search.index_conversations", return_value={}) as m_conv_idx,
            patch("radar.hooks.run_pre_heartbeat_hooks", return_value=MagicMock(blocked=False)) as m_pre_hook,
            patch("radar.hooks.run_post_heartbeat_hooks") as m_post_hook,
            patch("radar.hooks.run_heartbeat_collect_hooks", return_value=[]) as m_collect_hook,
            patch("radar.tools.calendar._get_reminders", return_value="") as m_rem,
            patch("radar.agent.run") as m_run,
        ):
            yield {
                "quiet": m_quiet,
                "log": m_log,
                "reload": m_reload,
                "config": cfg,
                "due": m_due,
                "mark": m_mark,
                "monitors": m_monitors,
                "summary": m_summary,
                "pre_hook": m_pre_hook,
                "post_hook": m_post_hook,
                "reminders": m_rem,
                "run": m_run,
            }

    def test_tick_skips_quiet_hours(self):
        with (
            patch.object(mod, "_is_quiet_hours", return_value=True),
            patch.object(mod, "_log_heartbeat") as m_log,
            patch("radar.agent.run") as m_run,
        ):
            mod._heartbeat_tick()
            m_run.assert_not_called()
            m_log.assert_called_once()
            assert "quiet hours" in m_log.call_args[0][0].lower()

    def test_tick_processes_due_tasks(self, _mock_tick_deps):
        mocks = _mock_tick_deps
        task = {"id": 42, "name": "weather", "message": "Check weather"}
        mocks["due"].return_value = [task]
        mod._heartbeat_tick()
        mocks["mark"].assert_called_once_with(42)
        mocks["run"].assert_called_once()

    def test_tick_handles_task_exception(self, _mock_tick_deps):
        mocks = _mock_tick_deps
        mocks["due"].side_effect = RuntimeError("db error")
        mod._heartbeat_tick()
        # Should still call agent.run despite task error
        mocks["run"].assert_called_once()

    def test_tick_processes_calendar_reminders(self, _mock_tick_deps):
        mocks = _mock_tick_deps
        mocks["reminders"].return_value = "Meeting at 3pm"
        mod._heartbeat_tick()
        call_msg = mocks["run"].call_args[0][0]
        assert "calendar" in call_msg.lower() or "Meeting at 3pm" in call_msg

    def test_tick_skips_empty_reminders(self, _mock_tick_deps):
        mocks = _mock_tick_deps
        mocks["reminders"].return_value = ""
        mod._heartbeat_tick()
        call_msg = mocks["run"].call_args[0][0]
        assert "No new events" in call_msg

    def test_tick_handles_calendar_exception(self, _mock_tick_deps):
        mocks = _mock_tick_deps
        mocks["reminders"].side_effect = RuntimeError("khal not found")
        mod._heartbeat_tick()
        mocks["run"].assert_called_once()

    def test_tick_clears_event_queue(self, _mock_tick_deps):
        mod.add_event("test", {"description": "ev1", "path": "/a"})
        assert len(mod._event_queue) == 1
        mod._heartbeat_tick()
        assert len(mod._event_queue) == 0

    def test_tick_calls_agent_run_with_personality(self, _mock_tick_deps):
        mocks = _mock_tick_deps
        mocks["config"].heartbeat.personality = "heartbeat"
        mod._heartbeat_tick()
        mocks["run"].assert_called_once()
        _, kwargs = mocks["run"].call_args
        assert kwargs["conversation_id"] == "conv-1"
        assert kwargs["personality"] == "heartbeat"

    def test_tick_passes_none_personality_when_empty(self, _mock_tick_deps):
        mocks = _mock_tick_deps
        mocks["config"].heartbeat.personality = ""
        mod._heartbeat_tick()
        _, kwargs = mocks["run"].call_args
        assert kwargs["personality"] is None

    def test_tick_handles_agent_exception(self, _mock_tick_deps):
        mocks = _mock_tick_deps
        mocks["run"].side_effect = RuntimeError("LLM down")
        mod._heartbeat_tick()  # Should not raise
        assert mod._last_heartbeat is not None

    def test_tick_does_not_mark_tasks_on_agent_failure(self, _mock_tick_deps):
        """When agent.run fails, scheduled tasks should NOT be marked as executed."""
        mocks = _mock_tick_deps
        task = {"id": 42, "name": "weather", "message": "Check weather"}
        mocks["due"].return_value = [task]
        mocks["run"].side_effect = RuntimeError("LLM down")
        mod._heartbeat_tick()
        mocks["mark"].assert_not_called()

    def test_tick_sets_last_heartbeat(self, _mock_tick_deps):
        assert mod._last_heartbeat is None
        mod._heartbeat_tick()
        assert mod._last_heartbeat is not None


# ---------------------------------------------------------------------------
# _get_heartbeat_conversation_id()
# ---------------------------------------------------------------------------


class TestGetHeartbeatConversationId:
    def test_creates_conversation_when_missing(self, isolated_data_dir):
        with patch("radar.memory.create_conversation", return_value="new-conv-id") as m_create:
            result = mod._get_heartbeat_conversation_id()
            assert result == "new-conv-id"
            m_create.assert_called_once()
            hb_file = isolated_data_dir / "heartbeat_conversation"
            assert hb_file.exists()
            assert hb_file.read_text() == "new-conv-id"

    def test_reads_existing_file(self, isolated_data_dir):
        hb_file = isolated_data_dir / "heartbeat_conversation"
        hb_file.write_text("existing-conv-id")
        with patch("radar.memory.create_conversation") as m_create:
            result = mod._get_heartbeat_conversation_id()
            assert result == "existing-conv-id"
            m_create.assert_not_called()

    def test_strips_whitespace(self, isolated_data_dir):
        hb_file = isolated_data_dir / "heartbeat_conversation"
        hb_file.write_text("  conv-id-123\n")
        result = mod._get_heartbeat_conversation_id()
        assert result == "conv-id-123"


# ---------------------------------------------------------------------------
# start_scheduler()
# ---------------------------------------------------------------------------


class TestStartScheduler:
    def test_start_creates_and_starts(self):
        mock_sched = MagicMock()
        with (
            patch.object(mod, "BackgroundScheduler", return_value=mock_sched),
            patch.object(mod, "get_config", return_value=_make_config()),
        ):
            mod.start_scheduler()
            mock_sched.add_job.assert_called_once()
            mock_sched.start.assert_called_once()
            assert mod._scheduler is mock_sched

    def test_start_noop_if_running(self):
        mod._scheduler = MagicMock()
        with (
            patch.object(mod, "BackgroundScheduler") as MockBS,
            patch.object(mod, "get_config", return_value=_make_config()),
        ):
            mod.start_scheduler()
            MockBS.assert_not_called()

    def test_start_uses_config_interval(self):
        mock_sched = MagicMock()
        with (
            patch.object(mod, "BackgroundScheduler", return_value=mock_sched),
            patch.object(mod, "get_config", return_value=_make_config(interval=30)),
        ):
            mod.start_scheduler()
            _, kwargs = mock_sched.add_job.call_args
            assert kwargs["minutes"] == 30


# ---------------------------------------------------------------------------
# stop_scheduler()
# ---------------------------------------------------------------------------


class TestStopScheduler:
    def test_stop_shuts_down(self):
        mock_sched = MagicMock()
        mod._scheduler = mock_sched
        mod.stop_scheduler()
        mock_sched.shutdown.assert_called_once_with(wait=False)
        assert mod._scheduler is None

    def test_stop_noop_if_not_running(self):
        mod.stop_scheduler()  # Should not raise


# ---------------------------------------------------------------------------
# trigger_heartbeat()
# ---------------------------------------------------------------------------


class TestTriggerHeartbeat:
    def test_trigger_skips_quiet_hours(self):
        with (
            patch.object(mod, "_is_quiet_hours", return_value=True),
            patch.object(mod, "_heartbeat_tick") as m_tick,
        ):
            result = mod.trigger_heartbeat()
            assert "quiet hours" in result.lower()
            m_tick.assert_not_called()

    def test_trigger_runs_tick(self):
        with (
            patch.object(mod, "_is_quiet_hours", return_value=False),
            patch.object(mod, "_heartbeat_tick") as m_tick,
        ):
            result = mod.trigger_heartbeat()
            assert "triggered" in result.lower()
            m_tick.assert_called_once()


# ---------------------------------------------------------------------------
# get_status()
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_not_running(self):
        with patch.object(mod, "get_config", return_value=_make_config()):
            status = mod.get_status()
            assert status["running"] is False
            assert status["next_heartbeat"] is None
            assert status["last_heartbeat"] is None

    def test_status_running_with_job(self):
        mock_job = MagicMock()
        mock_job.next_run_time.strftime.return_value = "10:30:00"

        mock_sched = MagicMock()
        mock_sched.running = True
        mock_sched.get_job.return_value = mock_job
        mod._scheduler = mock_sched

        with patch.object(mod, "get_config", return_value=_make_config()):
            status = mod.get_status()
            assert status["running"] is True
            assert status["next_heartbeat"] == "10:30:00"

    def test_status_pending_events(self):
        mod.add_event("a", {"x": 1})
        mod.add_event("b", {"y": 2})
        with patch.object(mod, "get_config", return_value=_make_config()):
            status = mod.get_status()
            assert status["pending_events"] == 2

    def test_status_formats_last_heartbeat(self):
        mod._last_heartbeat = datetime(2025, 3, 15, 14, 30, 0)
        with patch.object(mod, "get_config", return_value=_make_config()):
            status = mod.get_status()
            assert status["last_heartbeat"] == "2025-03-15 14:30:00"


# ---------------------------------------------------------------------------
# add_event()
# ---------------------------------------------------------------------------


class TestAddEvent:
    def test_add_event_appends(self):
        mod.add_event("file_created", {"path": "/tmp/x"})
        assert len(mod._event_queue) == 1

    def test_add_event_structure(self):
        mod.add_event("file_created", {"path": "/tmp/x"})
        event = mod._event_queue[0]
        assert event["type"] == "file_created"
        assert event["data"] == {"path": "/tmp/x"}
        assert "timestamp" in event

    def test_add_event_multiple(self):
        mod.add_event("a", {"x": 1})
        mod.add_event("b", {"y": 2})
        mod.add_event("c", {"z": 3})
        assert len(mod._event_queue) == 3


# ---------------------------------------------------------------------------
# _content_boundary()
# ---------------------------------------------------------------------------


class TestContentBoundary:
    def test_output_format(self):
        result = mod._content_boundary("hello world", "url_monitor")
        assert result.startswith("<external_data_")
        assert 'source="url_monitor"' in result
        assert "hello world" in result
        # Closing tag matches opening
        open_tag = result.split(">")[0].lstrip("<").split()[0]
        assert f"</{open_tag}>" in result

    def test_nonce_is_16_hex_chars(self):
        result = mod._content_boundary("x", "test")
        # Tag format: <external_data_{16 hex chars} source="test">
        tag_name = result.split(">")[0].lstrip("<").split()[0]
        nonce = tag_name.replace("external_data_", "")
        assert len(nonce) == 16
        assert all(c in "0123456789abcdef" for c in nonce)

    def test_unique_nonces(self):
        r1 = mod._content_boundary("a", "src")
        r2 = mod._content_boundary("a", "src")
        tag1 = r1.split(">")[0].lstrip("<").split()[0]
        tag2 = r2.split(">")[0].lstrip("<").split()[0]
        assert tag1 != tag2

    def test_multiline_content(self):
        content = "line1\nline2\nline3"
        result = mod._content_boundary(content, "rss_feed")
        assert "line1\nline2\nline3" in result


# ---------------------------------------------------------------------------
# _content_boundary integration with _build_heartbeat_message
# ---------------------------------------------------------------------------


class TestHeartbeatMessageWithBoundary:
    @pytest.fixture(autouse=True)
    def _fix_time(self):
        MockDatetime._fixed_now = datetime(2025, 6, 1, 10, 30, 0)
        with patch.object(mod, "datetime", MockDatetime):
            yield

    def test_url_changed_event_contains_boundary(self):
        """URL monitor events should have nonce-tagged boundaries in action."""
        action = (
            f"The monitored URL 'test' has changed. "
            f"Changes (5 lines):\n"
            f"{mod._content_boundary('+ new line', 'url_monitor')}\n\n"
            f"Summarize what changed and notify the user."
        )
        events = [{
            "type": "url_changed",
            "data": {
                "description": "URL changed: test",
                "path": "",
                "action": action,
            },
        }]
        msg = mod._build_heartbeat_message(events)
        assert "<external_data_" in msg
        assert 'source="url_monitor"' in msg
