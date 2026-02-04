"""Radar Web Routes"""

import secrets

from fastapi import Query, Request
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
async def chat(request: Request, continue_: str = Query(None, alias="continue")):
    """Chat page."""
    context = get_common_context(request, "chat")
    context["conversation_id"] = continue_
    context["messages"] = []

    if continue_:
        from radar.memory import get_messages_for_display
        context["messages"] = get_messages_for_display(continue_)

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
    from radar.logging import get_logs, get_log_stats, get_uptime

    context = get_common_context(request, "logs")

    # Load actual logs
    log_entries = get_logs(limit=100)
    stats = get_log_stats()

    context["logs"] = [
        {
            "timestamp": _format_log_timestamp(e.get("timestamp", "")),
            "level": e.get("level", "info"),
            "message": e.get("message", ""),
        }
        for e in log_entries
    ]
    context["error_count"] = stats["error_count"]
    context["warn_count"] = stats["warn_count"]
    context["api_calls"] = stats["api_calls"]
    context["uptime"] = get_uptime()

    return templates.TemplateResponse("logs.html", context)


def _format_log_timestamp(iso_timestamp: str) -> str:
    """Format ISO timestamp to HH:MM:SS for display."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso_timestamp)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return "--:--:--"


@app.get("/personalities", response_class=HTMLResponse)
async def personalities(request: Request):
    """Personalities management page."""
    from radar.agent import get_personalities_dir, DEFAULT_PERSONALITY, load_personality
    from radar.config import load_config

    context = get_common_context(request, "personalities")
    config = load_config()

    # Ensure default exists
    personalities_dir = get_personalities_dir()
    default_file = personalities_dir / "default.md"
    if not default_file.exists():
        default_file.write_text(DEFAULT_PERSONALITY)

    # List all personality files
    personality_files = sorted(personalities_dir.glob("*.md"))
    personalities_list = []
    for pfile in personality_files:
        name = pfile.stem
        content = pfile.read_text()
        # Get description (first non-empty, non-heading line)
        description = ""
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                description = line[:100]
                break
        personalities_list.append({
            "name": name,
            "description": description,
            "is_active": name == config.personality,
        })

    context["personalities"] = personalities_list
    context["active_personality"] = config.personality

    return templates.TemplateResponse("personalities.html", context)


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
    import json
    from html import escape
    from radar.agent import run

    form = await request.form()
    message = form.get("message", "")
    conversation_id = form.get("conversation_id") or None

    if not message:
        return HTMLResponse("")

    response, new_conversation_id = run(message, conversation_id)

    # Get message index for feedback (count messages in conversation)
    from radar.memory import get_messages
    messages = get_messages(new_conversation_id)
    message_index = len(messages) - 1  # Last message (the response)

    # Encode response for data attribute (JSON encode then escape for HTML attribute)
    raw_response_attr = escape(json.dumps(response))

    # Include conversation_id in response for HTMX to track
    # Add feedback buttons to assistant message
    # data-raw contains JSON-encoded markdown for client-side rendering
    return HTMLResponse(
        f"""
        <div class="message message--user">
            <div class="message__role">you</div>
            <div class="message__content">{escape(message)}</div>
        </div>
        <div class="message message--assistant" data-conversation-id="{new_conversation_id}" data-message-index="{message_index}">
            <div class="message__role">radar</div>
            <div class="message__content" data-raw={raw_response_attr}></div>
            <div class="message__feedback">
                <button class="feedback-btn feedback-btn--positive"
                        hx-post="/api/feedback"
                        hx-vals='{{"conversation_id": "{new_conversation_id}", "message_index": {message_index}, "sentiment": "positive"}}'
                        hx-swap="outerHTML"
                        title="This was helpful">
                    <span class="feedback-icon">+</span>
                </button>
                <button class="feedback-btn feedback-btn--negative"
                        hx-post="/api/feedback"
                        hx-vals='{{"conversation_id": "{new_conversation_id}", "message_index": {message_index}, "sentiment": "negative"}}'
                        hx-swap="outerHTML"
                        title="This could be better">
                    <span class="feedback-icon">-</span>
                </button>
            </div>
        </div>
        """
    )


@app.post("/api/feedback")
async def api_feedback(request: Request):
    """Store user feedback on a response."""
    from html import escape
    from radar.feedback import store_feedback

    form = await request.form()
    conversation_id = form.get("conversation_id", "")
    message_index = int(form.get("message_index", 0))
    sentiment = form.get("sentiment", "")
    response_content = form.get("response_content", "")
    user_comment = form.get("user_comment", "")

    if not conversation_id or sentiment not in ("positive", "negative"):
        return HTMLResponse(
            '<span class="text-error">Invalid feedback</span>',
            status_code=400
        )

    try:
        store_feedback(
            conversation_id=conversation_id,
            message_index=message_index,
            sentiment=sentiment,
            response_content=response_content or None,
            user_comment=user_comment or None,
        )

        # Return a confirmation that replaces the feedback buttons
        icon = "+" if sentiment == "positive" else "-"
        color = "phosphor" if sentiment == "positive" else "muted"
        return HTMLResponse(
            f'<span class="feedback-recorded text-{color}" title="Feedback recorded">'
            f'<span class="feedback-icon">{icon}</span> Recorded</span>'
        )

    except Exception as e:
        return HTMLResponse(
            f'<span class="text-error">Error: {escape(str(e))}</span>',
            status_code=500
        )


# ===== Memory API Routes =====


@app.get("/api/memory/search")
async def api_memory_search(q: str = ""):
    """Search memories and return HTML list."""
    from html import escape
    from radar.semantic import _get_connection, is_embedding_available, search_memories

    if not q.strip():
        # Return all memories if no search query
        try:
            conn = _get_connection()
            cursor = conn.execute(
                "SELECT id, content, created_at, source FROM memories ORDER BY created_at DESC"
            )
            rows = cursor.fetchall()
            conn.close()
            facts = [
                {"id": row["id"], "content": row["content"], "created_at": row["created_at"], "source": row["source"]}
                for row in rows
            ]
        except Exception:
            facts = []
    else:
        # Try semantic search if available, fall back to text search
        try:
            if is_embedding_available():
                results = search_memories(q, limit=50)
                facts = [
                    {"id": r["id"], "content": r["content"], "created_at": r["created_at"], "source": r["source"]}
                    for r in results
                ]
            else:
                # Fall back to LIKE search
                conn = _get_connection()
                cursor = conn.execute(
                    "SELECT id, content, created_at, source FROM memories WHERE content LIKE ? ORDER BY created_at DESC",
                    (f"%{q}%",),
                )
                rows = cursor.fetchall()
                conn.close()
                facts = [
                    {"id": row["id"], "content": row["content"], "created_at": row["created_at"], "source": row["source"]}
                    for row in rows
                ]
        except Exception:
            facts = []

    if not facts:
        return HTMLResponse(
            '<div class="card">'
            '<div class="card__body text-muted" style="text-align: center; padding: var(--space-xl);">'
            '<p>No memories found.</p>'
            '</div>'
            '</div>'
        )

    lines = []
    for fact in facts:
        source = escape(fact.get("source") or "manual")
        content = escape(fact.get("content", ""))
        created_at = escape(fact.get("created_at", ""))
        fact_id = fact.get("id")
        lines.append(
            f'<div class="fact" id="fact-{fact_id}">'
            f'<span class="fact__category">{source}</span>'
            f'<div class="fact__content">'
            f'<div class="fact__value">{content}</div>'
            f'<div class="fact__meta">Added {created_at}</div>'
            f'</div>'
            f'<div class="fact__actions">'
            f'<button class="btn btn--ghost" style="padding: 4px 8px; font-size: 0.7rem;"'
            f' hx-delete="/api/memory/{fact_id}"'
            f' hx-target="#fact-{fact_id}"'
            f' hx-swap="outerHTML"'
            f' hx-confirm="Forget this memory?">'
            f'Forget'
            f'</button>'
            f'</div>'
            f'</div>'
        )

    return HTMLResponse("\n".join(lines))


@app.delete("/api/memory/{memory_id}")
async def api_memory_delete(memory_id: int):
    """Delete a memory."""
    from radar.semantic import delete_memory

    success = delete_memory(memory_id)
    if success:
        return HTMLResponse("")  # Empty response removes the element
    return HTMLResponse('<div class="text-error">Memory not found</div>', status_code=404)


@app.get("/memory/add", response_class=HTMLResponse)
async def memory_add_form(request: Request):
    """Return the add memory modal form."""
    return HTMLResponse(
        '''
        <div class="modal-overlay" onclick="this.remove()">
            <div class="modal-content" onclick="event.stopPropagation()">
                <div class="card">
                    <div class="card__header">
                        <span class="card__title">Add Memory</span>
                        <button class="btn btn--ghost" style="padding: 4px 8px;"
                                onclick="this.closest('.modal-overlay').remove()">X</button>
                    </div>
                    <div class="card__body">
                        <form hx-post="/api/memory"
                              hx-target="#memory-list"
                              hx-swap="afterbegin"
                              hx-on::after-request="this.closest('.modal-overlay').remove()">
                            <div class="mb-md">
                                <label class="config-field__label">Content</label>
                                <textarea name="content" class="input" rows="4"
                                          placeholder="Enter something to remember..."
                                          required></textarea>
                            </div>
                            <div class="mb-md">
                                <label class="config-field__label">Source (optional)</label>
                                <input type="text" name="source" class="input"
                                       placeholder="e.g., manual, preference, note">
                            </div>
                            <div class="flex justify-between">
                                <button type="button" class="btn btn--ghost"
                                        onclick="this.closest('.modal-overlay').remove()">Cancel</button>
                                <button type="submit" class="btn btn--primary">Remember</button>
                            </div>
                        </form>
                    </div>
                </div>
            </div>
        </div>
        '''
    )


@app.post("/api/memory")
async def api_memory_create(request: Request):
    """Create a new memory."""
    from html import escape
    from radar.semantic import store_memory, is_embedding_available

    form = await request.form()
    content = form.get("content", "").strip()
    source = form.get("source", "").strip() or "manual"

    if not content:
        return HTMLResponse(
            '<div class="text-error">Content is required</div>',
            status_code=400
        )

    # Check if embeddings are available
    if not is_embedding_available():
        return HTMLResponse(
            '<div class="text-error">Embedding provider not configured</div>',
            status_code=400
        )

    try:
        memory_id = store_memory(content, source)
        from datetime import datetime
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Return the new memory card for prepending
        return HTMLResponse(
            f'<div class="fact" id="fact-{memory_id}">'
            f'<span class="fact__category">{escape(source)}</span>'
            f'<div class="fact__content">'
            f'<div class="fact__value">{escape(content)}</div>'
            f'<div class="fact__meta">Added {created_at}</div>'
            f'</div>'
            f'<div class="fact__actions">'
            f'<button class="btn btn--ghost" style="padding: 4px 8px; font-size: 0.7rem;"'
            f' hx-delete="/api/memory/{memory_id}"'
            f' hx-target="#fact-{memory_id}"'
            f' hx-swap="outerHTML"'
            f' hx-confirm="Forget this memory?">'
            f'Forget'
            f'</button>'
            f'</div>'
            f'</div>'
        )
    except Exception as e:
        return HTMLResponse(
            f'<div class="text-error">Error: {escape(str(e))}</div>',
            status_code=500
        )


# ===== Logs API Routes =====


@app.get("/api/logs")
async def api_logs(level: str = "all"):
    """Get filtered log entries as HTML."""
    from html import escape
    from radar.logging import get_logs

    entries = get_logs(level=level, limit=200)

    if not entries:
        return HTMLResponse(
            '<div class="log-viewer__line">'
            '<span class="log-viewer__timestamp">--:--:--</span>'
            '<span class="log-viewer__level log-viewer__level--info">info</span>'
            '<span class="log-viewer__message text-muted">No log entries found</span>'
            '</div>'
        )

    lines = []
    for entry in entries:
        timestamp = _format_log_timestamp(entry.get("timestamp", ""))
        level_str = entry.get("level", "info")
        message = escape(entry.get("message", ""))
        lines.append(
            f'<div class="log-viewer__line">'
            f'<span class="log-viewer__timestamp">{timestamp}</span>'
            f'<span class="log-viewer__level log-viewer__level--{level_str}">{level_str}</span>'
            f'<span class="log-viewer__message">{message}</span>'
            f'</div>'
        )

    return HTMLResponse("\n".join(lines))


@app.get("/api/logs/stream")
async def api_logs_stream(since: str = ""):
    """Get new log entries since timestamp for HTMX streaming."""
    from html import escape
    from radar.logging import get_recent_entries

    # Get entries since the provided timestamp
    entries = get_recent_entries(since=since if since else None, limit=50)

    if not entries:
        return HTMLResponse("")

    lines = []
    for entry in entries:
        timestamp = _format_log_timestamp(entry.get("timestamp", ""))
        level_str = entry.get("level", "info")
        message = escape(entry.get("message", ""))
        lines.append(
            f'<div class="log-viewer__line" data-timestamp="{entry.get("timestamp", "")}">'
            f'<span class="log-viewer__timestamp">{timestamp}</span>'
            f'<span class="log-viewer__level log-viewer__level--{level_str}">{level_str}</span>'
            f'<span class="log-viewer__message">{message}</span>'
            f'</div>'
        )

    return HTMLResponse("\n".join(lines))


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


# ===== Personality API Routes =====


@app.get("/api/personalities")
async def api_personalities_list():
    """List all personalities."""
    from radar.agent import get_personalities_dir, DEFAULT_PERSONALITY
    from radar.config import load_config

    config = load_config()
    personalities_dir = get_personalities_dir()

    # Ensure default exists
    default_file = personalities_dir / "default.md"
    if not default_file.exists():
        default_file.write_text(DEFAULT_PERSONALITY)

    personality_files = sorted(personalities_dir.glob("*.md"))
    result = []
    for pfile in personality_files:
        name = pfile.stem
        content = pfile.read_text()
        description = ""
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                description = line[:100]
                break
        result.append({
            "name": name,
            "description": description,
            "is_active": name == config.personality,
        })

    return {"personalities": result, "active": config.personality}


@app.get("/api/personalities/{name}")
async def api_personality_get(name: str):
    """Get a personality's content."""
    from radar.agent import get_personalities_dir, load_personality

    content = load_personality(name)
    return {"name": name, "content": content}


@app.put("/api/personalities/{name}")
async def api_personality_update(name: str, request: Request):
    """Update a personality's content."""
    from html import escape
    from radar.agent import get_personalities_dir

    form = await request.form()
    content = form.get("content", "")

    personalities_dir = get_personalities_dir()
    personality_file = personalities_dir / f"{name}.md"

    personality_file.write_text(content)

    return HTMLResponse(
        f'<div class="text-phosphor">✓ Personality "{escape(name)}" saved</div>'
    )


@app.post("/api/personalities")
async def api_personality_create(request: Request):
    """Create a new personality."""
    from html import escape
    from radar.agent import get_personalities_dir, DEFAULT_PERSONALITY

    form = await request.form()
    name = form.get("name", "").strip()

    if not name:
        return HTMLResponse(
            '<div class="text-error">Name is required</div>',
            status_code=400,
        )

    # Sanitize name (alphanumeric, dash, underscore only)
    import re
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return HTMLResponse(
            '<div class="text-error">Invalid name. Use only letters, numbers, dash, underscore.</div>',
            status_code=400,
        )

    personalities_dir = get_personalities_dir()
    personality_file = personalities_dir / f"{name}.md"

    if personality_file.exists():
        return HTMLResponse(
            f'<div class="text-error">Personality "{escape(name)}" already exists</div>',
            status_code=400,
        )

    # Create from template
    content = DEFAULT_PERSONALITY.replace("# Default", f"# {name.title()}")
    content = content.replace("A practical, local-first AI assistant.", f"A custom personality: {name}")
    personality_file.write_text(content)

    # Return redirect response
    return RedirectResponse(url=f"/personalities?created={name}", status_code=303)


@app.delete("/api/personalities/{name}")
async def api_personality_delete(name: str):
    """Delete a personality."""
    from html import escape
    from radar.agent import get_personalities_dir
    from radar.config import load_config

    if name == "default":
        return HTMLResponse(
            '<div class="text-error">Cannot delete default personality</div>',
            status_code=400,
        )

    config = load_config()
    if name == config.personality:
        return HTMLResponse(
            '<div class="text-error">Cannot delete active personality</div>',
            status_code=400,
        )

    personalities_dir = get_personalities_dir()
    personality_file = personalities_dir / f"{name}.md"

    if not personality_file.exists():
        return HTMLResponse(
            f'<div class="text-error">Personality "{escape(name)}" not found</div>',
            status_code=404,
        )

    personality_file.unlink()

    # Return empty response for HTMX to remove the element
    return HTMLResponse("")


@app.post("/api/personalities/{name}/activate")
async def api_personality_activate(name: str):
    """Set a personality as active."""
    import yaml
    from html import escape
    from radar.agent import get_personalities_dir
    from radar.config import get_config_path, reload_config

    personalities_dir = get_personalities_dir()
    personality_file = personalities_dir / f"{name}.md"

    if not personality_file.exists():
        return HTMLResponse(
            f'<div class="text-error">Personality "{escape(name)}" not found</div>',
            status_code=404,
        )

    # Update config file
    config_path = get_config_path()
    if config_path:
        with open(config_path) as f:
            config_data = yaml.safe_load(f) or {}

        config_data["personality"] = name

        with open(config_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False)

        # Reload config
        reload_config()

        return HTMLResponse(
            f'<div class="text-phosphor">✓ Activated: {escape(name)}</div>'
        )
    else:
        return HTMLResponse(
            '<div class="text-error">No config file found. Set RADAR_PERSONALITY env var.</div>',
            status_code=400,
        )


# ===== Personality Suggestions Routes =====


@app.get("/personalities/suggestions", response_class=HTMLResponse)
async def personality_suggestions(request: Request):
    """Personality suggestions review page."""
    from radar.feedback import get_pending_suggestions, get_feedback_summary

    context = get_common_context(request, "personalities")

    suggestions = get_pending_suggestions()
    feedback_summary = get_feedback_summary()

    context["suggestions"] = suggestions
    context["feedback_summary"] = feedback_summary

    return templates.TemplateResponse("personality_suggestions.html", context)


@app.post("/api/personalities/suggestions/{suggestion_id}/approve")
async def api_suggestion_approve(suggestion_id: int):
    """Approve a personality suggestion."""
    from html import escape
    from radar.feedback import approve_suggestion

    success, message = approve_suggestion(suggestion_id)

    if success:
        return HTMLResponse(
            f'<div class="suggestion-approved text-phosphor" style="padding: var(--space-md); text-align: center;">'
            f'<span style="font-size: 1.2rem;">Approved</span><br>'
            f'<span class="text-muted">{escape(message)}</span>'
            f'</div>'
        )
    return HTMLResponse(
        f'<div class="text-error">{escape(message)}</div>',
        status_code=400
    )


@app.post("/api/personalities/suggestions/{suggestion_id}/reject")
async def api_suggestion_reject(suggestion_id: int, request: Request):
    """Reject a personality suggestion."""
    from html import escape
    from radar.feedback import reject_suggestion

    form = await request.form()
    reason = form.get("reason", "")

    success, message = reject_suggestion(suggestion_id, reason or None)

    if success:
        return HTMLResponse("")  # Remove from list
    return HTMLResponse(
        f'<div class="text-error">{escape(message)}</div>',
        status_code=400
    )


@app.get("/api/feedback/summary")
async def api_feedback_summary():
    """Get feedback statistics summary."""
    from radar.feedback import get_feedback_summary

    return get_feedback_summary()


# ===== Plugin Routes =====


@app.get("/plugins", response_class=HTMLResponse)
async def plugins(request: Request):
    """Plugins management page."""
    from radar.config import load_config
    from radar.plugins import get_plugin_loader

    context = get_common_context(request, "plugins")
    config = load_config()
    loader = get_plugin_loader()

    # Get all plugins
    plugins_list = loader.list_plugins(include_pending=False)
    pending_list = loader.list_pending()

    context["plugins"] = plugins_list
    context["enabled_count"] = sum(1 for p in plugins_list if p.get("enabled"))
    context["pending_count"] = len(pending_list)
    context["allow_llm_generated"] = config.plugins.allow_llm_generated
    context["auto_approve"] = config.plugins.auto_approve
    context["auto_approve_if_tests_pass"] = config.plugins.auto_approve_if_tests_pass

    return templates.TemplateResponse("plugins.html", context)


@app.get("/plugins/review", response_class=HTMLResponse)
async def plugins_review(request: Request):
    """Plugin review page for pending plugins."""
    from radar.plugins import get_plugin_loader

    context = get_common_context(request, "plugins")
    loader = get_plugin_loader()

    pending_list = loader.list_pending()
    context["pending_plugins"] = pending_list

    return templates.TemplateResponse("plugin_review.html", context)


@app.get("/plugins/{name}", response_class=HTMLResponse)
async def plugin_detail(request: Request, name: str):
    """Plugin detail page."""
    from radar.plugins import get_plugin_loader

    context = get_common_context(request, "plugins")
    loader = get_plugin_loader()

    # Find the plugin
    plugin_path = loader.available_dir / name
    if not plugin_path.exists():
        plugin_path = loader.pending_dir / name

    if not plugin_path.exists():
        return HTMLResponse("Plugin not found", status_code=404)

    # Load plugin info
    import yaml

    manifest_file = plugin_path / "manifest.yaml"
    code_file = plugin_path / "tool.py"

    if not manifest_file.exists():
        return HTMLResponse("Plugin manifest not found", status_code=404)

    with open(manifest_file) as f:
        manifest = yaml.safe_load(f) or {}

    code = ""
    if code_file.exists():
        code = code_file.read_text()

    # Check if enabled
    enabled_link = loader.enabled_dir / name
    manifest["enabled"] = enabled_link.exists()

    # Get versions
    versions = loader.version_manager.get_versions(name)

    # Get errors
    errors = loader._load_errors(name)

    context["plugin"] = manifest
    context["code"] = code
    context["versions"] = versions
    context["errors"] = [e.to_dict() for e in errors]

    return templates.TemplateResponse("plugin_detail.html", context)


# ===== Plugin API Routes =====


@app.post("/api/plugins/{name}/enable")
async def api_plugin_enable(name: str):
    """Enable a plugin."""
    from html import escape
    from radar.plugins import get_plugin_loader

    loader = get_plugin_loader()
    success, message = loader.enable_plugin(name)

    if success:
        # Return updated plugin card for HTMX
        plugins_list = loader.list_plugins()
        plugin = next((p for p in plugins_list if p["name"] == name), None)
        if plugin:
            return HTMLResponse(f"""
                <div class="card mb-md" id="plugin-{escape(name)}">
                    <div class="card__header" style="display: flex; justify-content: space-between; align-items: center;">
                        <div style="display: flex; align-items: center; gap: var(--space-sm);">
                            <span class="status-indicator__dot" style="width: 8px; height: 8px;"></span>
                            <span class="card__title">{escape(plugin['name'])}</span>
                            <span class="text-muted" style="font-size: 0.75rem;">v{escape(plugin['version'])}</span>
                        </div>
                        <div style="display: flex; gap: var(--space-sm);">
                            <a href="/plugins/{escape(name)}" class="btn btn--ghost" style="padding: 4px 8px; font-size: 0.7rem;">Details</a>
                            <button class="btn btn--ghost" style="padding: 4px 8px; font-size: 0.7rem;"
                                    hx-post="/api/plugins/{escape(name)}/disable"
                                    hx-target="#plugin-{escape(name)}"
                                    hx-swap="outerHTML">
                                Disable
                            </button>
                        </div>
                    </div>
                    <div class="card__body">
                        <p class="text-muted" style="font-size: 0.85rem;">{escape(plugin['description'] or 'No description')}</p>
                    </div>
                </div>
            """)
    return HTMLResponse(f'<div class="text-error">{escape(message)}</div>', status_code=400)


@app.post("/api/plugins/{name}/disable")
async def api_plugin_disable(name: str):
    """Disable a plugin."""
    from html import escape
    from radar.plugins import get_plugin_loader

    loader = get_plugin_loader()
    success, message = loader.disable_plugin(name)

    if success:
        # Return updated plugin card for HTMX
        plugins_list = loader.list_plugins()
        plugin = next((p for p in plugins_list if p["name"] == name), None)
        if plugin:
            return HTMLResponse(f"""
                <div class="card mb-md" id="plugin-{escape(name)}">
                    <div class="card__header" style="display: flex; justify-content: space-between; align-items: center;">
                        <div style="display: flex; align-items: center; gap: var(--space-sm);">
                            <span class="status-indicator__dot status-indicator__dot--idle" style="width: 8px; height: 8px;"></span>
                            <span class="card__title">{escape(plugin['name'])}</span>
                            <span class="text-muted" style="font-size: 0.75rem;">v{escape(plugin['version'])}</span>
                        </div>
                        <div style="display: flex; gap: var(--space-sm);">
                            <a href="/plugins/{escape(name)}" class="btn btn--ghost" style="padding: 4px 8px; font-size: 0.7rem;">Details</a>
                            <button class="btn btn--ghost" style="padding: 4px 8px; font-size: 0.7rem;"
                                    hx-post="/api/plugins/{escape(name)}/enable"
                                    hx-target="#plugin-{escape(name)}"
                                    hx-swap="outerHTML">
                                Enable
                            </button>
                        </div>
                    </div>
                    <div class="card__body">
                        <p class="text-muted" style="font-size: 0.85rem;">{escape(plugin['description'] or 'No description')}</p>
                    </div>
                </div>
            """)
    return HTMLResponse(f'<div class="text-error">{escape(message)}</div>', status_code=400)


@app.post("/api/plugins/{name}/approve")
async def api_plugin_approve(name: str):
    """Approve a pending plugin."""
    from html import escape
    from radar.plugins import get_plugin_loader

    loader = get_plugin_loader()
    success, message = loader.approve_plugin(name)

    if success:
        return HTMLResponse(f"""
            <div class="card mb-lg" style="border-color: var(--phosphor);">
                <div class="card__body" style="text-align: center; padding: var(--space-lg);">
                    <div class="text-phosphor" style="font-size: 1.2rem; margin-bottom: var(--space-sm);">Approved</div>
                    <p class="text-muted">Plugin '{escape(name)}' has been approved and enabled.</p>
                </div>
            </div>
        """)
    return HTMLResponse(f'<div class="text-error">{escape(message)}</div>', status_code=400)


@app.post("/api/plugins/{name}/reject")
async def api_plugin_reject(name: str, request: Request):
    """Reject a pending plugin."""
    from html import escape
    from radar.plugins import get_plugin_loader

    form = await request.form()
    reason = form.get("reason", "")

    loader = get_plugin_loader()
    success, message = loader.reject_plugin(name, reason)

    if success:
        return HTMLResponse("")  # Remove from list
    return HTMLResponse(f'<div class="text-error">{escape(message)}</div>', status_code=400)


@app.put("/api/plugins/{name}/code")
async def api_plugin_update_code(name: str, request: Request):
    """Update a plugin's code."""
    from html import escape
    from radar.plugins import get_plugin_loader

    form = await request.form()
    code = form.get("code", "")

    loader = get_plugin_loader()
    success, message, error_details = loader.update_plugin_code(name, code)

    if success:
        return HTMLResponse(message)

    error_msg = message
    if error_details and "test_results" in error_details:
        for test in error_details["test_results"]:
            if not test.get("passed"):
                error_msg += f" - {test.get('name', 'test')}: {test.get('error', 'failed')}"
                break

    return HTMLResponse(escape(error_msg), status_code=400)


@app.post("/api/plugins/{name}/rollback/{version}")
async def api_plugin_rollback(name: str, version: str):
    """Rollback a plugin to a previous version."""
    from html import escape
    from radar.plugins import get_plugin_loader

    loader = get_plugin_loader()
    success, message = loader.rollback_plugin(name, version)

    if success:
        return HTMLResponse(f'<div class="text-phosphor">{escape(message)}</div>')
    return HTMLResponse(f'<div class="text-error">{escape(message)}</div>', status_code=400)


def run_server(host: str = "127.0.0.1", port: int = 8420):
    """Run the web server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
