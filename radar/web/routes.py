"""Radar Web Routes"""

import secrets

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

from radar.web import app, templates, get_common_context, _requires_auth


# ===== Page Routes =====


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    """Login page."""
    requires, _ = _requires_auth()
    if not requires:
        return RedirectResponse(url="/", status_code=302)

    error = request.query_params.get("error")

    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Login - Radar</title>
            <link rel="stylesheet" href="/static/css/radar.css">
        </head>
        <body style="display: flex; align-items: center; justify-content: center; min-height: 100vh;">
            <div class="card" style="width: 100%; max-width: 400px;">
                <div class="card__header">
                    <span class="card__title">Radar Authentication</span>
                </div>
                <div class="card__body">
                    {f'<div class="text-error mb-md">{error}</div>' if error else ''}
                    <form method="POST" action="/login">
                        <label class="config-field__label">Auth Token</label>
                        <input type="password" name="token" class="input" placeholder="Enter auth token" autofocus>
                        <button type="submit" class="btn btn--primary mt-md" style="width: 100%;">Login</button>
                    </form>
                </div>
            </div>
        </body>
        </html>
        """,
        status_code=200,
    )


@app.post("/login")
async def login_post(request: Request):
    """Handle login form submission."""
    form = await request.form()
    token = form.get("token", "")

    requires, expected_token = _requires_auth()
    if not requires:
        return RedirectResponse(url="/", status_code=302)

    if expected_token and secrets.compare_digest(str(token), expected_token):
        response = RedirectResponse(url="/", status_code=302)
        response.set_cookie(
            key="radar_auth",
            value=token,
            httponly=True,
            max_age=86400 * 30,  # 30 days
            samesite="strict",
        )
        return response

    return RedirectResponse(url="/login?error=Invalid+token", status_code=302)


@app.get("/logout")
async def logout():
    """Logout and clear auth cookie."""
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("radar_auth")
    return response


@app.get("/", response_class=HTMLResponse)
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


@app.get("/chat", response_class=HTMLResponse)
async def chat(request: Request, continue_: str = None):
    """Chat page."""
    context = get_common_context(request, "chat")
    context["conversation_id"] = continue_
    context["messages"] = []  # TODO: Load from memory if continuing

    if continue_:
        # TODO: Load conversation history
        pass

    return templates.TemplateResponse("chat.html", context)


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    """Conversation history page."""
    from radar.memory import get_recent_conversations

    context = get_common_context(request, "history")
    conversations = get_recent_conversations(20)
    context["conversations"] = conversations
    context["has_more"] = len(conversations) >= 20
    context["offset"] = 0
    return templates.TemplateResponse("history.html", context)


@app.get("/memory", response_class=HTMLResponse)
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


@app.get("/tasks", response_class=HTMLResponse)
async def tasks(request: Request):
    """Scheduled tasks page."""
    from radar.scheduler import get_status

    context = get_common_context(request, "tasks")
    sched_status = get_status()

    context["tasks"] = []  # Future: add custom scheduled tasks
    context["heartbeat_interval"] = sched_status.get("interval_minutes", 15)
    context["quiet_start"] = sched_status.get("quiet_hours_start", "23:00")
    context["quiet_end"] = sched_status.get("quiet_hours_end", "07:00")
    context["scheduler_running"] = sched_status.get("running", False)
    context["last_heartbeat"] = sched_status.get("last_heartbeat")
    context["next_heartbeat"] = sched_status.get("next_heartbeat")
    context["pending_events"] = sched_status.get("pending_events", 0)
    return templates.TemplateResponse("tasks.html", context)


@app.get("/config", response_class=HTMLResponse)
async def config(request: Request):
    """Configuration page."""
    import yaml
    from radar.config import load_config, get_config_path

    context = get_common_context(request, "config")
    config = load_config()
    config_path = get_config_path()

    context["config"] = {
        "llm": {
            "provider": config.llm.provider,
            "base_url": config.llm.base_url,
            "model": config.llm.model,
        },
        "embedding": {
            "provider": config.embedding.provider,
            "model": config.embedding.model,
        },
        "notifications": {
            "url": config.notifications.url,
            "topic": config.notifications.topic,
        },
        "tools": {
            "max_file_size": config.tools.max_file_size,
            "exec_timeout": config.tools.exec_timeout,
        },
        "max_tool_iterations": config.max_tool_iterations,
    }
    context["config_path"] = str(config_path) if config_path else "Not found"

    # Load raw YAML for display
    if config_path and config_path.exists():
        context["config_yaml"] = config_path.read_text()
    else:
        context["config_yaml"] = "# No configuration file found"

    return templates.TemplateResponse("config.html", context)


@app.get("/logs", response_class=HTMLResponse)
async def logs(request: Request):
    """Logs page."""
    context = get_common_context(request, "logs")
    # TODO: Load from log file
    context["logs"] = []
    context["error_count"] = 0
    context["warn_count"] = 0
    context["api_calls"] = 0
    context["uptime"] = "—"
    return templates.TemplateResponse("logs.html", context)


# ===== API Routes =====


@app.post("/api/ask")
async def api_ask(request: Request):
    """Quick ask endpoint."""
    from html import escape
    from radar.agent import ask

    form = await request.form()
    message = form.get("message", "")

    if not message:
        return HTMLResponse('<div class="text-muted">No message provided</div>')

    response = ask(message)

    return HTMLResponse(
        f"""
        <div class="message message--user">
            <div class="message__role">you</div>
            <div class="message__content">{escape(message)}</div>
        </div>
        <div class="message message--assistant mt-md">
            <div class="message__role">radar</div>
            <div class="message__content">{escape(response)}</div>
        </div>
        """
    )


@app.post("/api/chat")
async def api_chat(request: Request):
    """Chat message endpoint."""
    from html import escape
    from radar.agent import run

    form = await request.form()
    message = form.get("message", "")
    conversation_id = form.get("conversation_id") or None

    if not message:
        return HTMLResponse("")

    response, new_conversation_id = run(message, conversation_id)

    # Include conversation_id in response for HTMX to track
    return HTMLResponse(
        f"""
        <div class="message message--user">
            <div class="message__role">you</div>
            <div class="message__content">{escape(message)}</div>
        </div>
        <div class="message message--assistant" data-conversation-id="{new_conversation_id}">
            <div class="message__role">radar</div>
            <div class="message__content">{escape(response)}</div>
        </div>
        """
    )


@app.get("/api/config/test")
async def api_config_test():
    """Test LLM connection."""
    import httpx
    from radar.config import load_config

    config = load_config()

    try:
        async with httpx.AsyncClient() as client:
            if config.llm.provider == "ollama":
                # Test Ollama API
                response = await client.get(
                    f"{config.llm.base_url}/api/tags", timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()
                    models = [m["name"] for m in data.get("models", [])]
                    model_list = ", ".join(models[:5])
                    if len(models) > 5:
                        model_list += f" (+{len(models) - 5} more)"
                    return HTMLResponse(
                        f'<div class="text-phosphor">✓ Ollama connected. Available: {model_list}</div>'
                    )
                else:
                    return HTMLResponse(
                        f'<div class="text-error">✗ Ollama error: HTTP {response.status_code}</div>'
                    )
            else:
                # Test OpenAI-compatible API
                headers = {}
                if config.llm.api_key:
                    headers["Authorization"] = f"Bearer {config.llm.api_key}"
                response = await client.get(
                    f"{config.llm.base_url}/models", headers=headers, timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("id", "?") for m in data.get("data", [])][:5]
                    model_list = ", ".join(models) if models else config.llm.model
                    return HTMLResponse(
                        f'<div class="text-phosphor">✓ OpenAI API connected. Models: {model_list}</div>'
                    )
                else:
                    return HTMLResponse(
                        f'<div class="text-error">✗ API error: HTTP {response.status_code}</div>'
                    )
    except Exception as e:
        return HTMLResponse(f'<div class="text-error">✗ Connection failed: {e}</div>')


def run_server(host: str = "127.0.0.1", port: int = 8420):
    """Run the web server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
