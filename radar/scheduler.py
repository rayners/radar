"""Scheduler for heartbeat and event processing."""

from datetime import datetime, time
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from radar.config import get_config, get_data_paths

# Global state
_scheduler: BackgroundScheduler | None = None
_event_queue: list[dict[str, Any]] = []
_last_heartbeat: datetime | None = None


def _is_quiet_hours() -> bool:
    """Check if current time is within quiet hours."""
    config = get_config()
    now = datetime.now().time()

    try:
        start = datetime.strptime(config.heartbeat.quiet_hours_start, "%H:%M").time()
        end = datetime.strptime(config.heartbeat.quiet_hours_end, "%H:%M").time()
    except ValueError:
        return False

    # Handle overnight quiet hours (e.g., 23:00 - 07:00)
    if start > end:
        return now >= start or now <= end
    else:
        return start <= now <= end


def _build_heartbeat_message(events: list[dict[str, Any]]) -> str:
    """Build the heartbeat message from queued events."""
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if not events:
        return f"Heartbeat at {current_time}. No new events."

    lines = [f"Heartbeat at {current_time}. Events since last check:"]

    for e in events:
        data = e["data"]
        desc = data.get("description", e["type"])
        path = data.get("path", "")
        action = data.get("action")

        if action:
            lines.append(f"- {desc}")
            lines.append(f"  File: {path}")
            lines.append(f"  Action: {action}")
        else:
            lines.append(f"- {desc}: {path}")

    return "\n".join(lines)


def _log_heartbeat(message: str, **extra) -> None:
    """Log a heartbeat event."""
    try:
        from radar.logging import log
        log("info", message, **extra)
    except Exception:
        pass


def _check_config_reload() -> None:
    """Reload config, hooks, and external tools if the config file changed."""
    from radar.config import config_file_changed, reload_config

    if not config_file_changed():
        return

    _log_heartbeat("Config file changed, reloading")
    reload_config()

    # Reload hooks (clear config-sourced, re-register from new config)
    from radar.hooks import unregister_hooks_by_source
    from radar.hooks_builtin import load_config_hooks
    removed = unregister_hooks_by_source("config")
    added = load_config_hooks()
    _log_heartbeat(f"Hooks reloaded: {removed} removed, {added} added")

    # Reload external tools
    from radar.tools import reload_external_tools
    result = reload_external_tools()
    if any(result.values()):
        _log_heartbeat(
            f"External tools reloaded: {len(result['added'])} added, "
            f"{len(result['removed'])} removed, {len(result['reloaded'])} reloaded"
        )

    # Invalidate skills cache so they're re-discovered with new config dirs
    try:
        from radar.skills import invalidate_skills_cache
        invalidate_skills_cache()
        _log_heartbeat("Skills cache invalidated")
    except Exception:
        pass


def _heartbeat_tick() -> None:
    """Execute a heartbeat tick."""
    global _last_heartbeat, _event_queue

    if _is_quiet_hours():
        _log_heartbeat("Heartbeat skipped (quiet hours)")
        return

    # --- Config hot-reload ---
    try:
        _check_config_reload()
    except Exception as e:
        _log_heartbeat("Config reload error", error=str(e))

    # --- PRE hook ---
    try:
        from radar.hooks import run_pre_heartbeat_hooks
        hook_result = run_pre_heartbeat_hooks(len(_event_queue))
        if hook_result.blocked:
            _log_heartbeat(f"Heartbeat skipped by hook: {hook_result.message}")
            return
    except Exception:
        pass  # Don't let hook failures prevent heartbeats

    # Process due scheduled tasks
    try:
        from radar.scheduled_tasks import get_due_tasks, mark_task_executed
        for task in get_due_tasks():
            add_event("scheduled_task", {
                "description": f"Scheduled task: {task['name']}",
                "action": task["message"],
            })
            mark_task_executed(task["id"])
    except Exception as e:
        _log_heartbeat("Scheduled task processing error", error=str(e))

    # Check due URL monitors
    try:
        from radar.url_monitors import get_due_monitors, check_monitor
        for monitor in get_due_monitors():
            try:
                change = check_monitor(monitor)
                if change:
                    add_event("url_changed", {
                        "description": f"URL changed: {monitor['name']} ({monitor['url']})",
                        "action": (
                            f"The monitored URL '{monitor['name']}' has changed. "
                            f"Changes ({change['change_size']} lines):\n"
                            f"{change['diff_summary']}\n\n"
                            f"Summarize what changed and notify the user."
                        ),
                    })
            except Exception as e:
                _log_heartbeat(f"URL monitor failed: {monitor.get('name', '?')}", error=str(e))
    except Exception as e:
        _log_heartbeat("URL monitor processing error", error=str(e))

    # Check for due conversation summaries
    try:
        from radar.summaries import check_summary_due
        for period_type in ("daily", "weekly", "monthly"):
            summary_data = check_summary_due(period_type)
            if summary_data:
                add_event("conversation_summary", {
                    "description": f"Time to generate {period_type} conversation summary",
                    "action": (
                        f"Generate a {period_type} conversation summary from the following data. "
                        f"Summarize the key topics, decisions, and outcomes. "
                        f"Then call store_conversation_summary to save it.\n\n"
                        f"{summary_data}"
                    ),
                })
    except Exception as e:
        _log_heartbeat("Summary check error", error=str(e))

    # Re-index document collections
    try:
        from radar.config import get_config as _get_cfg
        _cfg = _get_cfg()
        if _cfg.documents.enabled:
            from radar.documents import ensure_summaries_collection, index_collection, list_collections
            ensure_summaries_collection()
            for coll in list_collections():
                try:
                    index_collection(coll["name"])
                except Exception as e:
                    _log_heartbeat(f"Document index error: {coll['name']}", error=str(e))
    except Exception as e:
        _log_heartbeat("Document indexing error", error=str(e))

    # Index conversations for semantic search
    try:
        from radar.conversation_search import index_conversations
        index_conversations()
    except Exception as e:
        _log_heartbeat("Conversation indexing error", error=str(e))

    # Calendar reminders
    try:
        from radar.tools.calendar import _get_reminders
        reminder_text = _get_reminders(15)
        if reminder_text:
            add_event("calendar_reminder", {
                "description": f"Upcoming calendar events:\n{reminder_text}",
                "action": "Send a notification reminding the user about these upcoming calendar events",
            })
    except Exception:
        pass

    # Run heartbeat-collect hooks (e.g., RSS feed checks)
    try:
        from radar.hooks import run_heartbeat_collect_hooks
        for event in run_heartbeat_collect_hooks():
            event_type = event.get("type", "plugin_event")
            data = event.get("data", event)
            add_event(event_type, data)
    except Exception as e:
        _log_heartbeat("Heartbeat-collect hooks error", error=str(e))

    # Collect pending events
    events = _event_queue.copy()
    _event_queue.clear()

    # Build heartbeat message
    message = _build_heartbeat_message(events)

    # Run agent with heartbeat message
    success = True
    error_msg = None
    try:
        from radar.agent import run
        _log_heartbeat("Heartbeat started", event_count=len(events))
        run(message, conversation_id=_get_heartbeat_conversation_id())
        _log_heartbeat("Heartbeat completed", event_count=len(events))
    except Exception as e:
        success = False
        error_msg = str(e)
        # Log error but don't crash scheduler
        import sys
        print(f"Heartbeat error: {e}", file=sys.stderr)
        _log_heartbeat("Heartbeat failed", error=str(e))

    _last_heartbeat = datetime.now()

    # --- POST hook ---
    try:
        from radar.hooks import run_post_heartbeat_hooks
        run_post_heartbeat_hooks(len(events), success, error_msg)
    except Exception:
        pass


def _get_heartbeat_conversation_id() -> str:
    """Get or create a persistent heartbeat conversation ID."""
    heartbeat_file = get_data_paths().base / "heartbeat_conversation"
    if heartbeat_file.exists():
        return heartbeat_file.read_text().strip()
    else:
        from radar.memory import create_conversation
        conv_id = create_conversation()
        heartbeat_file.write_text(conv_id)
        return conv_id


def start_scheduler() -> None:
    """Start the background scheduler."""
    global _scheduler

    if _scheduler is not None:
        return  # Already running

    config = get_config()
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _heartbeat_tick,
        "interval",
        minutes=config.heartbeat.interval_minutes,
        id="heartbeat",
        name="Heartbeat",
    )
    _scheduler.start()


def stop_scheduler() -> None:
    """Stop the background scheduler."""
    global _scheduler

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def trigger_heartbeat() -> str:
    """Manually trigger a heartbeat and return the result."""
    if _is_quiet_hours():
        return "Skipped: quiet hours active"

    _heartbeat_tick()
    return "Heartbeat triggered"


def get_status() -> dict[str, Any]:
    """Get scheduler status information."""
    global _scheduler, _last_heartbeat, _event_queue

    config = get_config()

    running = _scheduler is not None and _scheduler.running
    next_run = None

    if running:
        job = _scheduler.get_job("heartbeat")
        if job and job.next_run_time:
            next_run = job.next_run_time.strftime("%H:%M:%S")

    return {
        "running": running,
        "last_heartbeat": _last_heartbeat.strftime("%Y-%m-%d %H:%M:%S") if _last_heartbeat else None,
        "next_heartbeat": next_run,
        "pending_events": len(_event_queue),
        "quiet_hours": _is_quiet_hours(),
        "interval_minutes": config.heartbeat.interval_minutes,
        "quiet_hours_start": config.heartbeat.quiet_hours_start,
        "quiet_hours_end": config.heartbeat.quiet_hours_end,
    }


def add_event(event_type: str, data: dict[str, Any]) -> None:
    """Add an event to the queue for the next heartbeat.

    Args:
        event_type: Type of event (e.g., "file_created", "file_modified")
        data: Event data dictionary
    """
    global _event_queue

    _event_queue.append({
        "type": event_type,
        "data": data,
        "timestamp": datetime.now().isoformat(),
    })
