"""Dashboard and page routes."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from radar.web import templates, get_common_context

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard page."""
    from datetime import datetime

    from radar.memory import count_tool_calls_today, get_recent_activity, get_recent_conversations
    from radar.scheduler import get_status

    context = get_common_context(request, "dashboard")

    # Get scheduler status
    sched_status = get_status()
    last_hb = sched_status.get("last_heartbeat")
    next_hb = sched_status.get("next_heartbeat")

    # Get recent conversations and filter to today only
    conversations = get_recent_conversations(20)
    today = datetime.now().strftime("%Y-%m-%d")
    conversations_today = sum(
        1 for c in conversations
        if c.get("created_at", "").startswith(today)
    )

    context.update(
        {
            "last_heartbeat": last_hb or "Never",
            "next_heartbeat": next_hb or "N/A",
            "conversations_today": conversations_today,
            "tool_calls_today": count_tool_calls_today(),
            "activity": get_recent_activity(),
        }
    )

    # Load plugin widgets and pre-render templates through sandboxed Jinja2
    try:
        import jinja2.sandbox
        from markupsafe import Markup
        from radar.plugins import get_plugin_loader

        loader = get_plugin_loader()
        widgets = loader.get_widgets()
        env = jinja2.sandbox.SandboxedEnvironment(autoescape=True)
        for w in widgets:
            try:
                template = env.from_string(w["template_content"])
                w["rendered"] = Markup(template.render(plugin_name=w["name"]))
            except Exception:
                w["rendered"] = Markup('<span class="text-error">Widget render error</span>')
        context["widgets"] = widgets
    except Exception:
        context["widgets"] = []

    return templates.TemplateResponse("dashboard.html", context)


@router.get("/api/activity", response_class=HTMLResponse)
async def api_activity():
    """Return HTML fragment of recent activity for HTMX refresh."""
    from html import escape

    from radar.memory import get_recent_activity

    activity = get_recent_activity()
    if not activity:
        return HTMLResponse(
            '<div class="activity-log__item">'
            '<span class="activity-log__time">--:--</span>'
            '<span class="activity-log__message text-muted">No recent activity</span>'
            '<span class="activity-log__type">idle</span>'
            '</div>'
        )

    html_parts = []
    for item in activity:
        time = escape(item.get("time", ""))
        message = escape(item.get("message", ""))
        item_type = escape(item.get("type", ""))
        html_parts.append(
            f'<div class="activity-log__item">'
            f'<span class="activity-log__time">{time}</span>'
            f'<span class="activity-log__message">{message}</span>'
            f'<span class="activity-log__type activity-log__type--{item_type}">{item_type}</span>'
            f'</div>'
        )
    return HTMLResponse("".join(html_parts))


@router.get("/chat", response_class=HTMLResponse)
async def chat(request: Request, continue_: str = Query(None, alias="continue")):
    """Chat page."""
    context = get_common_context(request, "chat")
    context["conversation_id"] = continue_
    context["messages"] = []

    if continue_:
        from radar.memory import get_messages_for_display
        context["messages"] = get_messages_for_display(continue_)

    return templates.TemplateResponse("chat.html", context)


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    """Conversation history page."""
    from radar.memory import get_recent_conversations

    context = get_common_context(request, "history")
    conversations = get_recent_conversations(20)
    context["conversations"] = conversations
    context["has_more"] = len(conversations) >= 20
    context["offset"] = 0
    return templates.TemplateResponse("history.html", context)


@router.get("/memory", response_class=HTMLResponse)
async def memory(request: Request):
    """Memory/facts page."""
    context = get_common_context(request, "memory")

    # Load all memories from semantic storage
    try:
        from radar.semantic import _get_connection
        conn = _get_connection()
        cursor = conn.execute("SELECT id, content, created_at, source FROM memories ORDER BY created_at DESC")
        rows = cursor.fetchall()
        conn.close()
        context["facts"] = [
            {"id": row["id"], "content": row["content"], "created_at": row["created_at"], "source": row["source"]}
            for row in rows
        ]
    except Exception:
        context["facts"] = []

    return templates.TemplateResponse("memory.html", context)
