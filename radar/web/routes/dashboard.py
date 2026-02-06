"""Dashboard and page routes."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from radar.web import templates, get_common_context

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Dashboard page."""
    from radar.memory import get_recent_conversations
    from radar.scheduler import get_status

    context = get_common_context(request, "dashboard")

    # Get scheduler status
    sched_status = get_status()
    last_hb = sched_status.get("last_heartbeat")
    next_hb = sched_status.get("next_heartbeat")

    # Get recent conversations for stats
    conversations = get_recent_conversations(20)

    context.update(
        {
            "last_heartbeat": last_hb or "Never",
            "next_heartbeat": next_hb or "N/A",
            "conversations_today": len(conversations),
            "tool_calls_today": 0,  # Would need to scan conversations for tool calls
            "activity": [
                {"time": c["created_at"][:16] if c.get("created_at") else "", "message": c.get("preview", "")[:50], "type": "chat"}
                for c in conversations[:5]
            ],
        }
    )
    return templates.TemplateResponse("dashboard.html", context)


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
