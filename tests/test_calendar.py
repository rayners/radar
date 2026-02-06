"""Tests for calendar tool (khal wrapper)."""

import json
import subprocess
from unittest.mock import patch

import pytest

from radar.tools.calendar import (
    _get_cached,
    _get_reminders,
    _list_calendars,
    _list_events,
    _parse_json_events,
    _run_khal,
    _set_cached,
    calendar,
    reset_cache,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear cache before each test."""
    reset_cache()
    yield
    reset_cache()


def _json_event(title="Standup", date="02/06/2026", start_time="09:00",
                end_time="09:30", location="Room A",
                description="Daily sync", cal="work", all_day=False):
    """Build a khal JSON event dict."""
    return {
        "title": title,
        "start-date": date,
        "start-time": start_time,
        "end-time": end_time,
        "location": location,
        "description": description,
        "calendar": cal,
        "all-day": all_day,
    }


def _json_output(*events):
    """Serialize events to JSON array string (khal --json output)."""
    return json.dumps(list(events))


# ── TestRunKhal ──

class TestRunKhal:
    @patch("radar.tools.calendar.subprocess.run")
    def test_successful_command(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="output here\n", stderr="",
        )
        output, success = _run_khal(["list", "today"])
        assert success is True
        assert output == "output here\n"
        mock_run.assert_called_once_with(
            ["khal", "list", "today"],
            capture_output=True, text=True, timeout=30,
        )

    @patch("radar.tools.calendar.subprocess.run")
    def test_nonzero_exit(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="config error",
        )
        output, success = _run_khal(["list"])
        assert success is False
        assert "config error" in output

    @patch("radar.tools.calendar.subprocess.run")
    def test_nonzero_exit_stderr_empty(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="stdout error", stderr="",
        )
        output, success = _run_khal(["list"])
        assert success is False
        assert "stdout error" in output

    @patch("radar.tools.calendar.subprocess.run",
           side_effect=FileNotFoundError())
    def test_khal_not_installed(self, mock_run):
        output, success = _run_khal(["list"])
        assert success is False
        assert "khal not installed" in output

    @patch("radar.tools.calendar.subprocess.run",
           side_effect=subprocess.TimeoutExpired(cmd="khal", timeout=30))
    def test_timeout(self, mock_run):
        output, success = _run_khal(["list"])
        assert success is False
        assert "timed out" in output

    @patch("radar.tools.calendar.subprocess.run",
           side_effect=OSError("permission denied"))
    def test_generic_exception(self, mock_run):
        output, success = _run_khal(["list"])
        assert success is False
        assert "permission denied" in output


# ── TestCache ──

class TestCache:
    def test_cache_hit_within_ttl(self):
        _set_cached("key1", "result")
        assert _get_cached("key1") == "result"

    def test_cache_miss_after_ttl(self):
        _set_cached("key1", "result")
        from radar.tools.calendar import _cache
        ts, val = _cache["key1"]
        _cache["key1"] = (ts - 400, val)  # 400s ago, TTL is 300s
        assert _get_cached("key1") is None

    def test_cache_miss_unknown_key(self):
        assert _get_cached("nonexistent") is None

    def test_reset_cache_clears(self):
        _set_cached("key1", "result")
        reset_cache()
        assert _get_cached("key1") is None


# ── TestParseJsonEvents ──

class TestParseJsonEvents:
    def test_parse_single_event(self):
        output = _json_output(_json_event())
        events = _parse_json_events(output)
        assert len(events) == 1
        assert events[0]["title"] == "Standup"
        assert events[0]["start-date"] == "02/06/2026"
        assert events[0]["start-time"] == "09:00"
        assert events[0]["end-time"] == "09:30"
        assert events[0]["location"] == "Room A"
        assert events[0]["calendar"] == "work"
        assert events[0]["all-day"] is False

    def test_parse_multiple_events(self):
        output = _json_output(
            _json_event(title="Standup"),
            _json_event(title="Lunch", start_time="12:00", end_time="13:00"),
        )
        events = _parse_json_events(output)
        assert len(events) == 2
        assert events[0]["title"] == "Standup"
        assert events[1]["title"] == "Lunch"

    def test_parse_all_day_event(self):
        output = _json_output(_json_event(title="Holiday", start_time="",
                                          end_time="", all_day=True))
        events = _parse_json_events(output)
        assert len(events) == 1
        assert events[0]["all-day"] is True

    def test_parse_empty_output(self):
        assert _parse_json_events("") == []
        assert _parse_json_events("   \n  ") == []

    def test_parse_invalid_json(self):
        assert _parse_json_events("not json at all") == []

    def test_parse_single_object(self):
        output = json.dumps(_json_event(title="Solo"))
        events = _parse_json_events(output)
        assert len(events) == 1
        assert events[0]["title"] == "Solo"


# ── TestListEvents ──

class TestListEvents:
    @patch("radar.tools.calendar.subprocess.run")
    def test_formats_events_by_day(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(
                _json_event(title="Standup", date="02/06/2026",
                            start_time="09:00", end_time="09:30"),
                _json_event(title="Review", date="02/06/2026",
                            start_time="14:00", end_time="15:00"),
            ),
            stderr="",
        )
        result = _list_events("today", "tomorrow", None, "Today's Events")
        assert "Standup" in result
        assert "Review" in result
        assert "02/06/2026" in result
        assert "09:00 - 09:30" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_empty_result(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr="",
        )
        result = _list_events("today", "tomorrow", None, "Today's Events")
        assert "No events found" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_all_day_shows_all_day(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Holiday", start_time="",
                                            end_time="", all_day=True)),
            stderr="",
        )
        result = _list_events("today", "tomorrow", None, "Today's Events")
        assert "All day" in result
        assert "Holiday" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_calendar_filter_passes_flag(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr="",
        )
        _list_events("today", "tomorrow", "work", "Today's Events")
        args = mock_run.call_args[0][0]
        assert "-a" in args
        assert "work" in args

    @patch("radar.tools.calendar.subprocess.run")
    def test_error_returns_message(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="bad config",
        )
        result = _list_events("today", "tomorrow", None, "Today's Events")
        assert "Error" in result
        assert "bad config" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_uses_cache(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Cached")),
            stderr="",
        )
        result1 = _list_events("today", "tomorrow", None, "Today's Events")
        result2 = _list_events("today", "tomorrow", None, "Today's Events")
        assert result1 == result2
        assert mock_run.call_count == 1  # Only called once

    @patch("radar.tools.calendar.subprocess.run")
    def test_location_shown(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Meeting",
                                            location="Conf Room B")),
            stderr="",
        )
        result = _list_events("today", "tomorrow", None, "Today's Events")
        assert "Conf Room B" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_calendar_name_shown(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Meeting", cal="personal")),
            stderr="",
        )
        result = _list_events("today", "tomorrow", None, "Today's Events")
        assert "[personal]" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_multiple_dates_grouped(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(
                _json_event(title="Mon Meeting", date="02/09/2026"),
                _json_event(title="Tue Meeting", date="02/10/2026"),
            ),
            stderr="",
        )
        result = _list_events("today", "7d", None, "This Week")
        assert "02/09/2026" in result
        assert "02/10/2026" in result
        assert "Mon Meeting" in result
        assert "Tue Meeting" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_no_title_shows_placeholder(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="")),
            stderr="",
        )
        result = _list_events("today", "tomorrow", None, "Today's Events")
        assert "(No title)" in result


# ── TestListCalendars ──

class TestListCalendars:
    @patch("radar.tools.calendar.subprocess.run")
    def test_lists_calendars(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="work\npersonal\nholidays\n",
            stderr="",
        )
        result = _list_calendars()
        assert "work" in result
        assert "personal" in result
        assert "holidays" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_no_calendars(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="",
        )
        result = _list_calendars()
        assert "No calendars configured" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_error(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="no config",
        )
        result = _list_calendars()
        assert "Error" in result


# ── TestCalendarTool ──

class TestCalendarTool:
    @patch("radar.tools.calendar.subprocess.run")
    def test_today_operation(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Standup")),
            stderr="",
        )
        result = calendar(operation="today")
        assert "Standup" in result
        assert "Today's Events" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_tomorrow_operation(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Dentist")),
            stderr="",
        )
        result = calendar(operation="tomorrow")
        assert "Dentist" in result
        assert "Tomorrow's Events" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_week_operation(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Sprint Review")),
            stderr="",
        )
        result = calendar(operation="week")
        assert "Sprint Review" in result
        assert "This Week's Events" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_list_operation(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Conference")),
            stderr="",
        )
        result = calendar(operation="list", start_date="2026-03-01",
                          end_date="2026-03-07")
        assert "Conference" in result

    def test_list_operation_requires_start_date(self):
        result = calendar(operation="list")
        assert "start_date is required" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_calendars_operation(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="work\npersonal\n", stderr="",
        )
        result = calendar(operation="calendars")
        assert "work" in result
        assert "personal" in result

    def test_unknown_operation(self):
        result = calendar(operation="invalid")
        assert "Unknown operation" in result

    @patch("radar.tools.calendar.subprocess.run",
           side_effect=FileNotFoundError())
    def test_khal_not_installed(self, mock_run):
        result = calendar(operation="today")
        assert "Error" in result
        assert "khal not installed" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_calendar_filter(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Work Meeting")),
            stderr="",
        )
        result = calendar(operation="today", calendar_name="work")
        assert "Work Meeting" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_list_without_end_date(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr="",
        )
        result = calendar(operation="list", start_date="2026-03-01")
        args = mock_run.call_args[0][0]
        # Should default end to "1d"
        assert "2026-03-01" in args
        assert "1d" in args


# ── TestGetReminders ──

class TestGetReminders:
    @patch("radar.tools.calendar.subprocess.run")
    def test_returns_events_starting_soon(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Standup",
                                            start_time="09:00",
                                            end_time="09:30")),
            stderr="",
        )
        result = _get_reminders(15)
        assert "Standup" in result
        assert "09:00" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_returns_empty_when_no_events(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="[]", stderr="",
        )
        result = _get_reminders(15)
        assert result == ""

    @patch("radar.tools.calendar.subprocess.run")
    def test_skips_all_day_events(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Holiday", start_time="",
                                            end_time="", all_day=True)),
            stderr="",
        )
        result = _get_reminders(15)
        assert result == ""

    @patch("radar.tools.calendar.subprocess.run")
    def test_error_returns_empty(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error",
        )
        result = _get_reminders(15)
        assert result == ""

    @patch("radar.tools.calendar.subprocess.run")
    def test_includes_location(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(_json_event(title="Meeting",
                                            location="Room 5")),
            stderr="",
        )
        result = _get_reminders(15)
        assert "Room 5" in result

    @patch("radar.tools.calendar.subprocess.run")
    def test_mixed_all_day_and_timed(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_json_output(
                _json_event(title="Holiday", all_day=True),
                _json_event(title="Standup", start_time="09:00",
                            end_time="09:30"),
            ),
            stderr="",
        )
        result = _get_reminders(15)
        assert "Holiday" not in result
        assert "Standup" in result
