"""Tests for the scheduled tasks module."""

from datetime import datetime, timedelta

import pytest

from radar.scheduled_tasks import (
    MINIMUM_INTERVAL_MINUTES,
    compute_next_run,
    create_task,
    delete_task,
    disable_task,
    enable_task,
    format_schedule,
    get_due_tasks,
    get_task,
    list_tasks,
    mark_task_executed,
)
from radar.semantic import _get_connection


@pytest.fixture(autouse=True)
def cleanup_test_data():
    """Clean up test data before and after each test."""
    conn = _get_connection()
    conn.execute("DELETE FROM scheduled_tasks WHERE name LIKE 'test-%'")
    conn.commit()
    conn.close()
    yield
    conn = _get_connection()
    conn.execute("DELETE FROM scheduled_tasks WHERE name LIKE 'test-%'")
    conn.commit()
    conn.close()


class TestComputeNextRun:
    """Tests for compute_next_run scheduling logic."""

    def test_daily_future_time(self):
        """Daily schedule with a time later today returns today."""
        # Use 23:59 which should almost always be in the future during tests
        result = compute_next_run("daily", time_of_day="23:59")
        assert result is not None
        now = datetime.now()
        if now.hour < 23 or (now.hour == 23 and now.minute < 59):
            assert result.date() == now.date()
        assert result.hour == 23
        assert result.minute == 59

    def test_daily_past_time(self):
        """Daily schedule with a time earlier today returns tomorrow."""
        result = compute_next_run("daily", time_of_day="00:00")
        assert result is not None
        tomorrow = datetime.now().date() + timedelta(days=1)
        assert result.date() == tomorrow

    def test_daily_missing_time(self):
        """Daily schedule without time_of_day returns None."""
        result = compute_next_run("daily")
        assert result is None

    def test_weekly_returns_next_matching_day(self):
        """Weekly schedule returns the next matching weekday."""
        result = compute_next_run("weekly", time_of_day="09:00", day_of_week="mon,wed,fri")
        assert result is not None
        assert result.weekday() in (0, 2, 4)  # Mon, Wed, Fri

    def test_weekly_missing_params(self):
        """Weekly schedule without required params returns None."""
        assert compute_next_run("weekly", time_of_day="09:00") is None
        assert compute_next_run("weekly", day_of_week="mon") is None

    def test_weekly_invalid_day_names(self):
        """Weekly schedule with all invalid day names returns None."""
        result = compute_next_run("weekly", time_of_day="09:00", day_of_week="foo,bar")
        assert result is None

    def test_interval(self):
        """Interval schedule returns now + N minutes."""
        before = datetime.now()
        result = compute_next_run("interval", interval_minutes=30)
        after = datetime.now()
        assert result is not None
        assert before + timedelta(minutes=30) <= result <= after + timedelta(minutes=30)

    def test_interval_below_minimum(self):
        """Interval below minimum returns None."""
        result = compute_next_run("interval", interval_minutes=MINIMUM_INTERVAL_MINUTES - 1)
        assert result is None

    def test_interval_missing(self):
        """Interval without minutes returns None."""
        result = compute_next_run("interval")
        assert result is None

    def test_once_future(self):
        """Once schedule with future datetime returns that datetime."""
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        result = compute_next_run("once", run_at=future)
        assert result is not None

    def test_once_past(self):
        """Once schedule with past datetime returns None."""
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        result = compute_next_run("once", run_at=past)
        assert result is None

    def test_once_missing_run_at(self):
        """Once schedule without run_at returns None."""
        result = compute_next_run("once")
        assert result is None

    def test_unknown_schedule_type(self):
        """Unknown schedule type returns None."""
        result = compute_next_run("biweekly")
        assert result is None


class TestCreateAndGetTask:
    """Tests for task creation and retrieval."""

    def test_create_daily_task(self):
        """Create a daily task and verify all fields."""
        task_id = create_task(
            name="test-daily",
            description="Test daily task",
            schedule_type="daily",
            message="Do the thing",
            time_of_day="07:00",
        )
        assert task_id > 0

        task = get_task(task_id)
        assert task is not None
        assert task["name"] == "test-daily"
        assert task["description"] == "Test daily task"
        assert task["schedule_type"] == "daily"
        assert task["message"] == "Do the thing"
        assert task["time_of_day"] == "07:00"
        assert task["enabled"] == 1
        assert task["next_run"] is not None
        assert task["created_by"] == "chat"

    def test_create_weekly_task(self):
        """Create a weekly task."""
        task_id = create_task(
            name="test-weekly",
            description="Weekly task",
            schedule_type="weekly",
            message="Weekly action",
            time_of_day="09:00",
            day_of_week="mon,wed,fri",
        )
        task = get_task(task_id)
        assert task["schedule_type"] == "weekly"
        assert task["day_of_week"] == "mon,wed,fri"

    def test_create_interval_task(self):
        """Create an interval task."""
        task_id = create_task(
            name="test-interval",
            description="Interval task",
            schedule_type="interval",
            message="Repeat action",
            interval_minutes=15,
        )
        task = get_task(task_id)
        assert task["schedule_type"] == "interval"
        assert task["interval_minutes"] == 15

    def test_create_once_task(self):
        """Create a one-time task."""
        future = (datetime.now() + timedelta(hours=2)).isoformat()
        task_id = create_task(
            name="test-once",
            description="One-time task",
            schedule_type="once",
            message="Do once",
            run_at=future,
        )
        task = get_task(task_id)
        assert task["schedule_type"] == "once"
        assert task["next_run"] is not None

    def test_create_with_custom_created_by(self):
        """Create a task with custom created_by value."""
        task_id = create_task(
            name="test-web",
            description="Web task",
            schedule_type="daily",
            message="Web action",
            time_of_day="08:00",
            created_by="web",
        )
        task = get_task(task_id)
        assert task["created_by"] == "web"

    def test_get_nonexistent_task(self):
        """Getting a nonexistent task returns None."""
        assert get_task(999999) is None


class TestListTasks:
    """Tests for listing tasks."""

    def test_list_all_tasks(self):
        """List returns all tasks."""
        create_task("test-list-1", "d", "daily", "m", time_of_day="07:00")
        create_task("test-list-2", "d", "daily", "m", time_of_day="08:00")

        tasks = list_tasks()
        test_tasks = [t for t in tasks if t["name"].startswith("test-")]
        assert len(test_tasks) >= 2

    def test_list_enabled_only(self):
        """List with enabled_only filters disabled tasks."""
        tid1 = create_task("test-enabled", "d", "daily", "m", time_of_day="07:00")
        tid2 = create_task("test-disabled", "d", "daily", "m", time_of_day="08:00")
        disable_task(tid2)

        tasks = list_tasks(enabled_only=True)
        test_names = [t["name"] for t in tasks if t["name"].startswith("test-")]
        assert "test-enabled" in test_names
        assert "test-disabled" not in test_names

    def test_list_includes_disabled_by_default(self):
        """List without enabled_only includes disabled tasks."""
        tid = create_task("test-disabled2", "d", "daily", "m", time_of_day="07:00")
        disable_task(tid)

        tasks = list_tasks()
        test_names = [t["name"] for t in tasks if t["name"].startswith("test-")]
        assert "test-disabled2" in test_names


class TestDeleteTask:
    """Tests for task deletion."""

    def test_delete_existing_task(self):
        """Deleting an existing task returns True."""
        tid = create_task("test-del", "d", "daily", "m", time_of_day="07:00")
        assert delete_task(tid) is True
        assert get_task(tid) is None

    def test_delete_nonexistent_task(self):
        """Deleting a nonexistent task returns False."""
        assert delete_task(999999) is False


class TestDisableEnableTask:
    """Tests for task enable/disable toggling."""

    def test_disable_task(self):
        """Disabling a task sets enabled to False."""
        tid = create_task("test-toggle", "d", "daily", "m", time_of_day="07:00")
        assert disable_task(tid) is True
        task = get_task(tid)
        assert not task["enabled"]

    def test_enable_task(self):
        """Enabling a disabled task sets enabled to True and recomputes next_run."""
        tid = create_task("test-toggle2", "d", "daily", "m", time_of_day="07:00")
        disable_task(tid)

        assert enable_task(tid) is True
        task = get_task(tid)
        assert task["enabled"]
        assert task["next_run"] is not None

    def test_disable_nonexistent(self):
        """Disabling a nonexistent task returns False."""
        assert disable_task(999999) is False

    def test_enable_nonexistent(self):
        """Enabling a nonexistent task returns False."""
        assert enable_task(999999) is False


class TestDueTasksAndExecution:
    """Tests for due task detection and execution marking."""

    def _set_next_run_to_past(self, task_id: int):
        """Helper: set a task's next_run to 10 minutes ago."""
        conn = _get_connection()
        past = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "UPDATE scheduled_tasks SET next_run = ? WHERE id = ?", (past, task_id)
        )
        conn.commit()
        conn.close()

    def test_get_due_tasks(self):
        """Tasks with past next_run appear as due."""
        tid = create_task("test-due", "d", "interval", "m", interval_minutes=5)
        self._set_next_run_to_past(tid)

        due = get_due_tasks()
        due_ids = [t["id"] for t in due]
        assert tid in due_ids

    def test_disabled_task_not_due(self):
        """Disabled tasks do not appear as due."""
        tid = create_task("test-due-disabled", "d", "interval", "m", interval_minutes=5)
        self._set_next_run_to_past(tid)
        disable_task(tid)

        due = get_due_tasks()
        due_ids = [t["id"] for t in due]
        assert tid not in due_ids

    def test_future_task_not_due(self):
        """Tasks with future next_run are not due."""
        tid = create_task("test-due-future", "d", "interval", "m", interval_minutes=60)
        # next_run is ~60 min from now, should not be due

        due = get_due_tasks()
        due_ids = [t["id"] for t in due]
        assert tid not in due_ids

    def test_mark_executed_interval(self):
        """Marking an interval task executed updates last_run and computes new next_run."""
        tid = create_task("test-exec-interval", "d", "interval", "m", interval_minutes=10)
        self._set_next_run_to_past(tid)

        mark_task_executed(tid)
        task = get_task(tid)
        assert task["last_run"] is not None
        assert task["next_run"] is not None
        assert task["enabled"]

        # next_run should be in the future
        next_run = datetime.strptime(task["next_run"], "%Y-%m-%d %H:%M:%S")
        assert next_run > datetime.now()

    def test_mark_executed_daily(self):
        """Marking a daily task executed updates last_run and sets next_run to tomorrow."""
        tid = create_task("test-exec-daily", "d", "daily", "m", time_of_day="07:00")
        self._set_next_run_to_past(tid)

        mark_task_executed(tid)
        task = get_task(tid)
        assert task["last_run"] is not None
        assert task["next_run"] is not None
        assert task["enabled"]

    def test_mark_executed_once_disables(self):
        """Marking a one-time task executed disables it."""
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        tid = create_task("test-exec-once", "d", "once", "m", run_at=future)
        self._set_next_run_to_past(tid)

        mark_task_executed(tid)
        task = get_task(tid)
        assert task["last_run"] is not None
        assert task["next_run"] is None
        assert not task["enabled"]

    def test_mark_executed_removes_from_due(self):
        """After execution, a task no longer appears as due."""
        tid = create_task("test-exec-nodue", "d", "interval", "m", interval_minutes=30)
        self._set_next_run_to_past(tid)

        due_before = [t["id"] for t in get_due_tasks()]
        assert tid in due_before

        mark_task_executed(tid)

        due_after = [t["id"] for t in get_due_tasks()]
        assert tid not in due_after

    def test_mark_executed_nonexistent(self):
        """Marking a nonexistent task does nothing (no error)."""
        mark_task_executed(999999)  # Should not raise


class TestFormatSchedule:
    """Tests for human-readable schedule formatting."""

    def test_daily(self):
        """Format daily schedule."""
        task = {"schedule_type": "daily", "time_of_day": "07:00"}
        assert format_schedule(task) == "Daily at 07:00"

    def test_weekly(self):
        """Format weekly schedule."""
        task = {"schedule_type": "weekly", "time_of_day": "09:00", "day_of_week": "mon,wed,fri"}
        assert format_schedule(task) == "Weekly mon,wed,fri at 09:00"

    def test_interval(self):
        """Format interval schedule."""
        task = {"schedule_type": "interval", "interval_minutes": 30}
        assert format_schedule(task) == "Every 30 min"

    def test_once(self):
        """Format one-time schedule."""
        task = {"schedule_type": "once", "run_at": "2026-03-01T10:00:00"}
        assert format_schedule(task) == "Once at 2026-03-01T10:00:00"


class TestTools:
    """Tests for the scheduled task tools."""

    def test_schedule_task_daily(self):
        """Test schedule_task tool creates a daily task."""
        from radar.tools.scheduled_tasks import schedule_task

        result = schedule_task(
            name="test-tool-daily",
            message="Check the weather",
            schedule_type="daily",
            time_of_day="07:00",
        )
        assert "test-tool-daily" in result
        assert "Next run:" in result

    def test_schedule_task_missing_time(self):
        """Test schedule_task tool rejects daily without time."""
        from radar.tools.scheduled_tasks import schedule_task

        result = schedule_task(
            name="test-tool-notime",
            message="msg",
            schedule_type="daily",
        )
        assert "Error" in result

    def test_schedule_task_interval_too_small(self):
        """Test schedule_task tool rejects interval below minimum."""
        from radar.tools.scheduled_tasks import schedule_task

        result = schedule_task(
            name="test-tool-small",
            message="msg",
            schedule_type="interval",
            interval_minutes=1,
        )
        assert "Error" in result

    def test_schedule_task_invalid_type(self):
        """Test schedule_task tool rejects invalid schedule type."""
        from radar.tools.scheduled_tasks import schedule_task

        result = schedule_task(
            name="test-tool-bad",
            message="msg",
            schedule_type="biweekly",
        )
        assert "Error" in result

    def test_list_scheduled_tasks_empty(self):
        """Test list_scheduled_tasks with no tasks."""
        from radar.tools.scheduled_tasks import list_scheduled_tasks

        result = list_scheduled_tasks()
        assert "No scheduled tasks" in result or "test-" not in result

    def test_list_scheduled_tasks_with_tasks(self):
        """Test list_scheduled_tasks shows created tasks."""
        from radar.tools.scheduled_tasks import schedule_task, list_scheduled_tasks

        schedule_task(
            name="test-tool-list",
            message="List me",
            schedule_type="daily",
            time_of_day="12:00",
        )
        result = list_scheduled_tasks()
        assert "test-tool-list" in result
        assert "Daily at 12:00" in result

    def test_cancel_task_disable(self):
        """Test cancel_task disables a task."""
        from radar.tools.scheduled_tasks import schedule_task, cancel_task

        # Create first, extract ID from result
        create_result = schedule_task(
            name="test-tool-cancel",
            message="Cancel me",
            schedule_type="daily",
            time_of_day="06:00",
        )
        # Extract task ID from "Scheduled task 'test-tool-cancel' (ID N) created."
        task_id = int(create_result.split("(ID ")[1].split(")")[0])

        result = cancel_task(task_id=task_id)
        assert "disabled" in result.lower()

        task = get_task(task_id)
        assert not task["enabled"]

    def test_cancel_task_delete(self):
        """Test cancel_task with delete=True permanently removes."""
        from radar.tools.scheduled_tasks import schedule_task, cancel_task

        create_result = schedule_task(
            name="test-tool-delete",
            message="Delete me",
            schedule_type="daily",
            time_of_day="06:00",
        )
        task_id = int(create_result.split("(ID ")[1].split(")")[0])

        result = cancel_task(task_id=task_id, delete=True)
        assert "deleted" in result.lower()
        assert get_task(task_id) is None

    def test_cancel_nonexistent(self):
        """Test cancel_task with nonexistent ID."""
        from radar.tools.scheduled_tasks import cancel_task

        result = cancel_task(task_id=999999)
        assert "not found" in result.lower()
