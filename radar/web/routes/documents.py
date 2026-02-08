"""Document collection web routes."""

from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from radar.web import get_common_context, templates

router = APIRouter()


@router.get("/documents", response_class=HTMLResponse)
async def documents_page(request: Request):
    """Documents page."""
    context = get_common_context(request, "documents")

    try:
        from radar.documents import list_collections

        context["collections"] = list_collections()
    except Exception:
        context["collections"] = []

    return templates.TemplateResponse("documents.html", context)


@router.get("/api/documents/search", response_class=HTMLResponse)
async def api_documents_search(
    q: str = "",
    collection: str = "",
    search_type: str = "hybrid",
):
    """Search documents and return HTML results."""
    if not q.strip():
        return HTMLResponse(
            '<div class="text-muted" style="padding: var(--space-md); text-align: center;">'
            "Enter a search query.</div>"
        )

    try:
        from radar.documents import search_fts, search_hybrid, search_semantic
        from radar.semantic import is_embedding_available

        coll = collection if collection else None

        if search_type == "keyword":
            results = search_fts(q, collection=coll, limit=10)
        elif search_type == "semantic":
            if not is_embedding_available():
                return HTMLResponse(
                    '<div class="text-error">Semantic search requires an embedding provider.</div>'
                )
            results = search_semantic(q, collection=coll, limit=10)
        else:
            results = search_hybrid(q, collection=coll, limit=10)

        if not results:
            return HTMLResponse(
                '<div class="text-muted" style="padding: var(--space-md); text-align: center;">'
                f'No results for "{escape(q)}".</div>'
            )

        html_parts = []
        for i, r in enumerate(results, 1):
            content = escape(r["content"][:300])
            if len(r["content"]) > 300:
                content += "..."
            file_path = escape(r.get("file_path", "unknown"))
            coll_name = escape(r.get("collection", ""))

            score_info = ""
            if "similarity" in r:
                score_info = f"similarity: {r['similarity']:.3f}"
            elif "score" in r:
                score_info = f"score: {r['score']:.4f}"

            html_parts.append(
                f'<div class="card mb-md">'
                f'<div class="card__header">'
                f'<span class="card__title" style="font-size: 0.85rem;">#{i} [{coll_name}]</span>'
                f'<span class="text-muted" style="font-size: 0.75rem;">{score_info}</span>'
                f"</div>"
                f'<div class="card__body">'
                f'<div class="text-muted" style="font-size: 0.75rem; margin-bottom: var(--space-xs);">{file_path}</div>'
                f'<div style="white-space: pre-wrap; font-size: 0.85rem;">{content}</div>'
                f"</div>"
                f"</div>"
            )

        return HTMLResponse("\n".join(html_parts))

    except Exception as e:
        return HTMLResponse(
            f'<div class="text-error">Search error: {escape(str(e))}</div>',
            status_code=500,
        )


@router.post("/api/documents/collections", response_class=HTMLResponse)
async def api_create_collection(request: Request):
    """Create a new document collection."""
    form = await request.form()
    name = form.get("name", "").strip()
    base_path = form.get("base_path", "").strip()
    patterns = form.get("patterns", "*.md").strip()
    description = form.get("description", "").strip()

    if not name or not base_path:
        return HTMLResponse(
            '<div class="text-error">Name and base path are required.</div>',
            status_code=400,
        )

    try:
        from radar.documents import create_collection

        coll_id = create_collection(name, base_path, patterns, description)
        return HTMLResponse(
            f'<div class="text-phosphor">Collection "{escape(name)}" created (ID: {coll_id}).</div>'
        )
    except Exception as e:
        return HTMLResponse(
            f'<div class="text-error">Error: {escape(str(e))}</div>',
            status_code=500,
        )


@router.post("/api/documents/collections/{name}/index", response_class=HTMLResponse)
async def api_index_collection(name: str):
    """Trigger re-indexing of a collection."""
    try:
        from radar.documents import index_collection

        result = index_collection(name)
        return HTMLResponse(
            f'<div class="text-phosphor">'
            f"Indexed: {result['files_indexed']} files, "
            f"{result['files_skipped']} unchanged, "
            f"{result['chunks_created']} chunks, "
            f"{result['files_removed']} removed."
            f"</div>"
        )
    except Exception as e:
        return HTMLResponse(
            f'<div class="text-error">Error: {escape(str(e))}</div>',
            status_code=500,
        )


@router.delete("/api/documents/collections/{name}", response_class=HTMLResponse)
async def api_delete_collection(name: str):
    """Delete a document collection."""
    try:
        from radar.documents import delete_collection

        if delete_collection(name):
            return HTMLResponse("")
        return HTMLResponse(
            f'<div class="text-error">Collection "{escape(name)}" not found.</div>',
            status_code=404,
        )
    except Exception as e:
        return HTMLResponse(
            f'<div class="text-error">Error: {escape(str(e))}</div>',
            status_code=500,
        )
