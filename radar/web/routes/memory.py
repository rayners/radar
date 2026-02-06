"""Memory API routes."""

from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/api/memory/search")
async def api_memory_search(q: str = ""):
    """Search memories and return HTML list."""
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


@router.delete("/api/memory/{memory_id}")
async def api_memory_delete(memory_id: int):
    """Delete a memory."""
    from radar.semantic import delete_memory

    success = delete_memory(memory_id)
    if success:
        return HTMLResponse("")  # Empty response removes the element
    return HTMLResponse('<div class="text-error">Memory not found</div>', status_code=404)


@router.get("/memory/add", response_class=HTMLResponse)
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


@router.post("/api/memory")
async def api_memory_create(request: Request):
    """Create a new memory."""
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
