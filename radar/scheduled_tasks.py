"""Scheduled tasks CRUD operations."""

from datetime import datetime, timedelta
from typing import Any

from radar.semantic import _get_connection

# Day name to weekday number (Monday=0)
_DAY_MAP = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3,
    "fri": 4, "sat": 5, "sun": 6,
}

MINIMUM_INTERVAL_MINUTES = 5


def _to_sqlite_datetime(dt: datetime | None) -> str | None:
    """Format a datetime as SQLite-compatible string (space separator, no microseconds)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def compute_next_run(
    schedule_type: str,
    time_of_day: str | None = None,
    day_of_week: str | None = None,
    interval_minutes: int | None = None,
    run_at: str | None = None,
) -> datetime | None:
    """Compute the next run time for a schedule.

    Args:
        schedule_type: 'once', 'daily', 'weekly', or 'interval'
        time_of_day: HH:MM for daily/weekly schedules
        day_of_week: Comma-separated day names (mon,tue,...) for weekly
        interval_minutes: Minutes between runs for interval schedules
        run_at: ISO datetime for once schedules

    Returns:
        Next run datetime, or None if schedule is expired
    """
    now = datetime.now()

    if schedule_type == "once":
        if not run_at:
            return None
        target = datetime.fromisoformat(run_at)
        return target if target > now else None

    elif schedule_type == "daily":
        if not time_of_day:
            return None
        hour, minute = map(int, time_of_day.split(":"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target

    elif schedule_type == "weekly":
        if not time_of_day or not day_of_week:
            return None
        hour, minute = map(int, time_of_day.split(":"))
        days = [_DAY_MAP[d.strip().lower()] for d in day_of_week.split(",") if d.strip().lower() in _DAY_MAP]
        if not days:
            return None

        # Find next matching day
        best = None
        for offset in range(8):  # Check up to 8 days ahead (covers wrap-around)
            candidate = now + timedelta(days=offset)
            if candidate.weekday() in days:
                target = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target > now:
                    best = target
                    break
        return best

    elif schedule_type == "interval":
        if not interval_minutes or interval_minutes < MINIMUM_INTERVAL_MINUTES:
            return None
        return now + timedelta(minutes=interval_minutes)

    return None


def create_task(
    name: str,
    description: str,
    schedule_type: str,
    message: str,
    time_of_day: str | None = None,
    day_of_week: str | None = None,
    interval_minutes: int | None = None,
    run_at: str | None = None,
    created_by: str = "chat",
) -> int:
    """Create a new scheduled task.

    Returns:
        The ID of the created task
    """
    next_run = compute_next_run(schedule_type, time_of_day, day_of_week, interval_minutes, run_at)

    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO scheduled_tasks
            (name, description, schedule_type, time_of_day, day_of_week,
             interval_minutes, run_at, message, next_run, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name, description, schedule_type, time_of_day, day_of_week,
                interval_minutes, run_at, message,
                _to_sqlite_datetime(next_run),
                created_by,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_task(task_id: int) -> dict[str, Any] | None:
    """Get a task by ID."""
    conn = _get_connection()
    try:
        cursor = conn.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_tasks(enabled_only: bool = False) -> list[dict[str, Any]]:
    """List all scheduled tasks.

    Args:
        enabled_only: If True, only return enabled tasks
    """
    conn = _get_connection()
    try:
        where = "WHERE enabled = 1 " if enabled_only else ""
        cursor = conn.execute(f"SELECT * FROM scheduled_tasks {where}ORDER BY created_at DESC")
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def delete_task(task_id: int) -> bool:
    """Delete a task permanently.

    Returns:
        True if deleted, False if not found
    """
    conn = _get_connection()
    try:
        cursor = conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def disable_task(task_id: int) -> bool:
    """Disable a task (non-destructive cancel).

    Returns:
        True if updated, False if not found
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "UPDATE scheduled_tasks SET enabled = 0 WHERE id = ?", (task_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def enable_task(task_id: int) -> bool:
    """Enable a disabled task and recompute next_run.

    Returns:
        True if updated, False if not found
    """
    task = get_task(task_id)
    if not task:
        return False

    next_run = compute_next_run(
        task["schedule_type"],
        task["time_of_day"],
        task["day_of_week"],
        task["interval_minutes"],
        task["run_at"],
    )

    conn = _get_connection()
    try:
        cursor = conn.execute(
            "UPDATE scheduled_tasks SET enabled = 1, next_run = ? WHERE id = ?",
            (_to_sqlite_datetime(next_run), task_id),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def get_due_tasks() -> list[dict[str, Any]]:
    """Get all enabled tasks whose next_run is in the past."""
    conn = _get_connection()
    try:
        cursor = conn.execute(
            """
            SELECT * FROM scheduled_tasks
            WHERE next_run <= datetime('now', 'localtime')
            AND enabled = 1
            ORDER BY next_run ASC
            """
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def mark_task_executed(task_id: int) -> None:
    """Mark a task as executed: update last_run, compute next next_run, disable once tasks."""
    task = get_task(task_id)
    if not task:
        return

    now = datetime.now()

    if task["schedule_type"] == "once":
        sql = "UPDATE scheduled_tasks SET last_run = ?, enabled = 0, next_run = NULL WHERE id = ?"
        params = (_to_sqlite_datetime(now), task_id)
    else:
        next_run = compute_next_run(
            task["schedule_type"],
            task["time_of_day"],
            task["day_of_week"],
            task["interval_minutes"],
            task["run_at"],
        )
        sql = "UPDATE scheduled_tasks SET last_run = ?, next_run = ? WHERE id = ?"
        params = (_to_sqlite_datetime(now), _to_sqlite_datetime(next_run), task_id)

    conn = _get_connection()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def format_schedule(task: dict[str, Any]) -> str:
    """Format a task's schedule as a human-readable string."""
    stype = task["schedule_type"]
    if stype == "once":
        return f"Once at {task.get('run_at', '?')}"
    elif stype == "daily":
        return f"Daily at {task.get('time_of_day', '?')}"
    elif stype == "weekly":
        days = task.get("day_of_week", "?")
        return f"Weekly {days} at {task.get('time_of_day', '?')}"
    elif stype == "interval":
        return f"Every {task.get('interval_minutes', '?')} min"
    return stype
