"""Scheduled tasks routes."""

from datetime import datetime
from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from radar.web import templates, get_common_context

router = APIRouter()


@router.get("/tasks", response_class=HTMLResponse)
async def tasks(request: Request):
    """Scheduled tasks page."""
    from radar.scheduler import get_status
    from radar.scheduled_tasks import list_tasks

    context = get_common_context(request, "tasks")
    sched_status = get_status()

    # Load real tasks from DB
    raw_tasks = list_tasks()
    context["tasks"] = [_format_task_for_template(t) for t in raw_tasks]
    context["heartbeat_interval"] = sched_status.get("interval_minutes", 15)
    context["quiet_start"] = sched_status.get("quiet_hours_start", "23:00")
    context["quiet_end"] = sched_status.get("quiet_hours_end", "07:00")
    context["scheduler_running"] = sched_status.get("running", False)
    context["last_heartbeat"] = sched_status.get("last_heartbeat")
    context["next_heartbeat"] = sched_status.get("next_heartbeat")
    context["pending_events"] = sched_status.get("pending_events", 0)
    return templates.TemplateResponse("tasks.html", context)


def _format_task_for_template(task: dict) -> dict:
    """Convert a DB task dict to a template-friendly dict."""
    from radar.scheduled_tasks import format_schedule

    return {
        "id": task["id"],
        "name": task["name"],
        "description": task["description"],
        "schedule": format_schedule(task),
        "enabled": bool(task["enabled"]),
        "last_run": _format_task_timestamp(task.get("last_run")),
        "next_run": _format_task_timestamp(task.get("next_run")),
    }


def _format_task_timestamp(ts: str | None) -> str | None:
    """Format an ISO timestamp to a shorter display string."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts


@router.get("/tasks/add", response_class=HTMLResponse)
async def tasks_add_form(request: Request):
    """Return the add task modal form."""
    return HTMLResponse(
        '''
        <div class="modal-overlay" onclick="this.remove()">
            <div class="modal-content" onclick="event.stopPropagation()">
                <div class="card">
                    <div class="card__header">
                        <span class="card__title">Add Scheduled Task</span>
                        <button class="btn btn--ghost" style="padding: 4px 8px;"
                                onclick="this.closest('.modal-overlay').remove()">X</button>
                    </div>
                    <div class="card__body">
                        <form hx-post="/api/tasks"
                              hx-target="#task-list"
                              hx-swap="innerHTML"
                              hx-on::after-request="this.closest('.modal-overlay').remove()">
                            <div class="mb-md">
                                <label class="config-field__label">Name</label>
                                <input type="text" name="name" class="input"
                                       placeholder="e.g., Morning weather" required>
                            </div>
                            <div class="mb-md">
                                <label class="config-field__label">Message (instruction for the agent)</label>
                                <textarea name="message" class="input" rows="3"
                                          placeholder="e.g., Check the weather forecast and send a summary via ntfy"
                                          required></textarea>
                            </div>
                            <div class="mb-md">
                                <label class="config-field__label">Schedule Type</label>
                                <select name="schedule_type" class="input" id="schedule-type-select"
                                        onchange="document.querySelectorAll('.schedule-field').forEach(e => e.style.display = 'none'); document.querySelectorAll('.schedule-' + this.value).forEach(e => e.style.display = 'block');">
                                    <option value="daily">Daily</option>
                                    <option value="weekly">Weekly</option>
                                    <option value="interval">Interval</option>
                                    <option value="once">Once</option>
                                </select>
                            </div>
                            <div class="mb-md schedule-field schedule-daily schedule-weekly" style="display: block;">
                                <label class="config-field__label">Time of Day</label>
                                <input type="time" name="time_of_day" class="input" value="07:00">
                            </div>
                            <div class="mb-md schedule-field schedule-weekly" style="display: none;">
                                <label class="config-field__label">Days of Week</label>
                                <input type="text" name="day_of_week" class="input"
                                       placeholder="mon,tue,wed,thu,fri" value="mon,tue,wed,thu,fri">
                            </div>
                            <div class="mb-md schedule-field schedule-interval" style="display: none;">
                                <label class="config-field__label">Interval (minutes, min 5)</label>
                                <input type="number" name="interval_minutes" class="input"
                                       min="5" value="30">
                            </div>
                            <div class="mb-md schedule-field schedule-once" style="display: none;">
                                <label class="config-field__label">Run At (date and time)</label>
                                <input type="datetime-local" name="run_at" class="input">
                            </div>
                            <div class="flex justify-between">
                                <button type="button" class="btn btn--ghost"
                                        onclick="this.closest('.modal-overlay').remove()">Cancel</button>
                                <button type="submit" class="btn btn--primary">Create Task</button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </div>
        '''
    )


@router.post("/api/tasks")
async def api_tasks_create(request: Request):
    """Create a scheduled task from the web form."""
    from radar.scheduled_tasks import create_task, list_tasks

    form = await request.form()
    name = form.get("name", "").strip()
    message = form.get("message", "").strip()
    schedule_type = form.get("schedule_type", "daily")
    time_of_day = form.get("time_of_day", "").strip() or None
    day_of_week = form.get("day_of_week", "").strip() or None
    interval_minutes_str = form.get("interval_minutes", "").strip()
    run_at = form.get("run_at", "").strip() or None

    if not name or not message:
        return HTMLResponse(
            '<div class="text-error">Name and message are required</div>',
            status_code=400,
        )

    interval_minutes = int(interval_minutes_str) if interval_minutes_str else None

    try:
        create_task(
            name=name,
            description=message,
            schedule_type=schedule_type,
            message=message,
            time_of_day=time_of_day,
            day_of_week=day_of_week,
            interval_minutes=interval_minutes,
            run_at=run_at,
            created_by="web",
        )
    except Exception as e:
        return HTMLResponse(
            f'<div class="text-error">Error: {escape(str(e))}</div>',
            status_code=400,
        )

    # Return updated full task list
    return _render_task_rows()


@router.delete("/api/tasks/{task_id}")
async def api_tasks_delete(task_id: int):
    """Delete a scheduled task."""
    from radar.scheduled_tasks import delete_task

    success = delete_task(task_id)
    if success:
        return HTMLResponse("")  # HTMX removes the row
    return HTMLResponse(
        '<div class="text-error">Task not found</div>', status_code=404
    )


@router.post("/api/tasks/{task_id}/run")
async def api_tasks_run(task_id: int):
    """Manually trigger a scheduled task."""
    from radar.scheduled_tasks import get_task
    from radar.scheduler import add_event

    task = get_task(task_id)
    if not task:
        return HTMLResponse(
            '<div class="text-error">Task not found</div>', status_code=404
        )

    add_event("scheduled_task", {
        "description": f"Manual run: {task['name']}",
        "action": task["message"],
    })

    return HTMLResponse(
        f'<div class="text-phosphor">Queued "{escape(task["name"])}" for next heartbeat</div>'
    )


@router.post("/api/tasks/{task_id}/toggle")
async def api_tasks_toggle(task_id: int):
    """Toggle a task's enabled/disabled state."""
    from radar.scheduled_tasks import get_task, enable_task, disable_task

    task = get_task(task_id)
    if not task:
        return HTMLResponse(
            '<div class="text-error">Task not found</div>', status_code=404
        )

    if task["enabled"]:
        disable_task(task_id)
    else:
        enable_task(task_id)

    # Return updated full task list
    return _render_task_rows()


@router.post("/api/heartbeat/trigger")
async def api_heartbeat_trigger():
    """Trigger a manual heartbeat."""
    from radar.scheduler import trigger_heartbeat

    result = trigger_heartbeat()
    return HTMLResponse(f'<div class="text-phosphor">{result}</div>')


def _render_task_rows() -> HTMLResponse:
    """Render the task table body rows for HTMX responses."""
    from radar.scheduled_tasks import list_tasks

    raw_tasks = list_tasks()
    tasks = [_format_task_for_template(t) for t in raw_tasks]

    if not tasks:
        return HTMLResponse(
            '<tr><td colspan="6" class="text-muted" style="text-align: center; padding: var(--space-xl);">'
            "<p>No scheduled tasks yet.</p>"
            "</td></tr>"
        )

    lines = []
    for t in tasks:
        dot_class = "" if t["enabled"] else " status-indicator__dot--idle"
        toggle_label = "Pause" if t["enabled"] else "Resume"
        lines.append(
            f'<tr id="task-{t["id"]}">'
            f'<td style="text-align: center;">'
            f'<span class="status-indicator__dot{dot_class}"></span>'
            f"</td>"
            f"<td>"
            f'<div style="font-weight: 500;">{escape(t["name"])}</div>'
            f'<div class="text-muted" style="font-size: 0.8rem;">{escape(t["description"])}</div>'
            f"</td>"
            f'<td><code style="color: var(--amber); font-size: 0.85rem;">{escape(t["schedule"])}</code></td>'
            f'<td class="text-muted">{t["last_run"] or "Never"}</td>'
            f'<td>{t["next_run"] or chr(8212)}</td>'
            f"<td>"
            f'<div class="flex gap-sm">'
            f'<button class="btn btn--ghost" style="padding: 2px 6px; font-size: 0.7rem;"'
            f' hx-post="/api/tasks/{t["id"]}/toggle"'
            f' hx-target="#task-list"'
            f' hx-swap="innerHTML"'
            f' title="{toggle_label}">'
            f'{"||" if t["enabled"] else chr(9654)}'
            f"</button>"
            f'<button class="btn btn--ghost" style="padding: 2px 6px; font-size: 0.7rem;"'
            f' hx-post="/api/tasks/{t["id"]}/run"'
            f' hx-swap="none"'
            f' title="Run now">'
            f"&#9654;"
            f"</button>"
            f'<button class="btn btn--ghost" style="padding: 2px 6px; font-size: 0.7rem;"'
            f' hx-delete="/api/tasks/{t["id"]}"'
            f' hx-target="#task-{t["id"]}"'
            f' hx-swap="outerHTML"'
            f' hx-confirm="Delete this task?"'
            f' title="Delete">'
            f"&#10005;"
            f"</button>"
            f"</div>"
            f"</td>"
            f"</tr>"
        )

    return HTMLResponse("\n".join(lines))
