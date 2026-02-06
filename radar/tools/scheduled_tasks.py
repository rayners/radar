"""Tools for managing scheduled tasks via chat."""

from radar.tools import tool


@tool(
    name="schedule_task",
    description="Create a scheduled task that runs automatically. "
    "Use 'daily' for daily tasks, 'weekly' for specific days, "
    "'interval' for recurring every N minutes, or 'once' for a one-time task.",
    parameters={
        "name": {"type": "string", "description": "Short name for the task"},
        "message": {
            "type": "string",
            "description": "The message/instruction to execute when the task fires",
        },
        "schedule_type": {
            "type": "string",
            "enum": ["once", "daily", "weekly", "interval"],
            "description": "Type of schedule",
        },
        "time_of_day": {
            "type": "string",
            "description": "Time in HH:MM format (for daily/weekly)",
            "optional": True,
        },
        "day_of_week": {
            "type": "string",
            "description": "Comma-separated days: mon,tue,wed,thu,fri,sat,sun (for weekly)",
            "optional": True,
        },
        "interval_minutes": {
            "type": "integer",
            "description": "Minutes between runs (for interval, minimum 5)",
            "optional": True,
        },
        "run_at": {
            "type": "string",
            "description": "ISO datetime for one-time execution (for once)",
            "optional": True,
        },
    },
)
def schedule_task(
    name: str,
    message: str,
    schedule_type: str,
    time_of_day: str | None = None,
    day_of_week: str | None = None,
    interval_minutes: int | None = None,
    run_at: str | None = None,
) -> str:
    from radar.scheduled_tasks import create_task, get_task, MINIMUM_INTERVAL_MINUTES

    # Validate params per schedule type
    if schedule_type == "daily":
        if not time_of_day:
            return "Error: daily schedule requires time_of_day (HH:MM)"
    elif schedule_type == "weekly":
        if not time_of_day or not day_of_week:
            return "Error: weekly schedule requires time_of_day and day_of_week"
    elif schedule_type == "interval":
        if not interval_minutes:
            return "Error: interval schedule requires interval_minutes"
        if interval_minutes < MINIMUM_INTERVAL_MINUTES:
            return f"Error: interval must be at least {MINIMUM_INTERVAL_MINUTES} minutes"
    elif schedule_type == "once":
        if not run_at:
            return "Error: once schedule requires run_at (ISO datetime)"
    else:
        return f"Error: invalid schedule_type '{schedule_type}'"

    task_id = create_task(
        name=name,
        description=message,
        schedule_type=schedule_type,
        message=message,
        time_of_day=time_of_day,
        day_of_week=day_of_week,
        interval_minutes=interval_minutes,
        run_at=run_at,
    )

    task = get_task(task_id)
    next_run = task["next_run"] if task else "unknown"

    return f"Scheduled task '{name}' (ID {task_id}) created. Next run: {next_run}"


@tool(
    name="list_scheduled_tasks",
    description="List all scheduled tasks with their status and next run time.",
    parameters={
        "show_disabled": {
            "type": "boolean",
            "description": "Include disabled tasks (default: false)",
            "optional": True,
        },
    },
)
def list_scheduled_tasks(show_disabled: bool = False) -> str:
    from radar.scheduled_tasks import list_tasks, format_schedule

    tasks = list_tasks(enabled_only=not show_disabled)

    if not tasks:
        return "No scheduled tasks found."

    lines = []
    for t in tasks:
        status = "enabled" if t["enabled"] else "disabled"
        schedule = format_schedule(t)
        last = t["last_run"] or "never"
        next_r = t["next_run"] or "-"
        lines.append(
            f"[{t['id']}] {t['name']} ({status})\n"
            f"    Schedule: {schedule}\n"
            f"    Message: {t['message'][:80]}\n"
            f"    Last run: {last} | Next run: {next_r}"
        )

    return "\n\n".join(lines)


@tool(
    name="cancel_task",
    description="Cancel a scheduled task. By default disables it (can be re-enabled). "
    "Use delete=true to permanently remove.",
    parameters={
        "task_id": {"type": "integer", "description": "ID of the task to cancel"},
        "delete": {
            "type": "boolean",
            "description": "Permanently delete instead of disable (default: false)",
            "optional": True,
        },
    },
)
def cancel_task(task_id: int, delete: bool = False) -> str:
    from radar.scheduled_tasks import get_task, delete_task, disable_task

    task = get_task(task_id)
    if not task:
        return f"Error: task {task_id} not found"

    if delete:
        delete_task(task_id)
        return f"Task '{task['name']}' (ID {task_id}) permanently deleted."
    else:
        disable_task(task_id)
        return f"Task '{task['name']}' (ID {task_id}) disabled. Use list_scheduled_tasks with show_disabled=true to see it."
