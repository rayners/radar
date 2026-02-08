"""Personalities routes."""

import re
from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from radar.web import templates, get_common_context

router = APIRouter()


def _extract_personality_info(content: str) -> dict:
    """Extract display info from a personality file, parsing front matter if present.

    Returns dict with: description, model (optional), tools_filter (optional summary).
    """
    from radar.agent import parse_personality

    try:
        pc = parse_personality(content)
    except ValueError:
        # Both include and exclude — treat as plain content
        pc = None

    body = pc.content if pc else content

    # Get description (first non-empty, non-heading line from body)
    description = ""
    for line in body.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            description = line[:100]
            break

    info: dict = {"description": description}

    if pc and pc.model:
        info["model"] = pc.model
    if pc and pc.tools_include:
        info["tools_filter"] = f"include: {', '.join(pc.tools_include)}"
    elif pc and pc.tools_exclude:
        info["tools_filter"] = f"exclude: {', '.join(pc.tools_exclude)}"

    return info


@router.get("/personalities", response_class=HTMLResponse)
async def personalities(request: Request):
    """Personalities management page."""
    from radar.agent import get_personalities_dir, DEFAULT_PERSONALITY
    from radar.config import load_config

    context = get_common_context(request, "personalities")
    config = load_config()

    # Ensure default exists
    personalities_dir = get_personalities_dir()
    default_file = personalities_dir / "default.md"
    if not default_file.exists():
        default_file.write_text(DEFAULT_PERSONALITY)

    personalities_list = []
    seen_names: set[str] = set()

    # List all flat .md personality files
    personality_files = sorted(personalities_dir.glob("*.md"))
    for pfile in personality_files:
        name = pfile.stem
        seen_names.add(name)
        content = pfile.read_text()
        info = _extract_personality_info(content)
        personalities_list.append({
            "name": name,
            "description": info["description"],
            "model": info.get("model"),
            "tools_filter": info.get("tools_filter"),
            "is_active": name == config.personality,
        })

    # List directory-based personalities
    for d in sorted(personalities_dir.iterdir()):
        if d.is_dir() and (d / "PERSONALITY.md").exists():
            name = d.name
            if name in seen_names:
                continue
            seen_names.add(name)
            content = (d / "PERSONALITY.md").read_text()
            info = _extract_personality_info(content)
            personalities_list.append({
                "name": name,
                "description": info["description"],
                "model": info.get("model"),
                "tools_filter": info.get("tools_filter"),
                "is_active": name == config.personality,
                "source": "directory",
            })

    # Add plugin bundled personalities
    try:
        from radar.plugins import get_plugin_loader
        loader = get_plugin_loader()
        for bp in loader.get_bundled_personalities():
            info = _extract_personality_info(bp["content"])
            personalities_list.append({
                "name": bp["name"],
                "description": info["description"],
                "model": info.get("model"),
                "tools_filter": info.get("tools_filter"),
                "is_active": bp["name"] == config.personality,
                "source": "plugin",
                "plugin_name": bp["plugin_name"],
            })
    except Exception:
        pass

    context["personalities"] = personalities_list
    context["active_personality"] = config.personality

    return templates.TemplateResponse("personalities.html", context)


# ===== Personality API Routes =====


@router.get("/api/personalities")
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

    result = []
    seen_names: set[str] = set()

    # Flat .md files
    personality_files = sorted(personalities_dir.glob("*.md"))
    for pfile in personality_files:
        name = pfile.stem
        seen_names.add(name)
        content = pfile.read_text()
        info = _extract_personality_info(content)
        entry = {
            "name": name,
            "description": info["description"],
            "is_active": name == config.personality,
        }
        if info.get("model"):
            entry["model"] = info["model"]
        if info.get("tools_filter"):
            entry["tools_filter"] = info["tools_filter"]
        result.append(entry)

    # Directory-based personalities
    for d in sorted(personalities_dir.iterdir()):
        if d.is_dir() and (d / "PERSONALITY.md").exists():
            name = d.name
            if name in seen_names:
                continue
            seen_names.add(name)
            content = (d / "PERSONALITY.md").read_text()
            info = _extract_personality_info(content)
            entry = {
                "name": name,
                "description": info["description"],
                "is_active": name == config.personality,
                "source": "directory",
            }
            if info.get("model"):
                entry["model"] = info["model"]
            if info.get("tools_filter"):
                entry["tools_filter"] = info["tools_filter"]
            result.append(entry)

    # Add plugin bundled personalities
    try:
        from radar.plugins import get_plugin_loader
        loader = get_plugin_loader()
        for bp in loader.get_bundled_personalities():
            info = _extract_personality_info(bp["content"])
            entry = {
                "name": bp["name"],
                "description": info["description"],
                "is_active": bp["name"] == config.personality,
                "source": "plugin",
                "plugin_name": bp["plugin_name"],
            }
            if info.get("model"):
                entry["model"] = info["model"]
            if info.get("tools_filter"):
                entry["tools_filter"] = info["tools_filter"]
            result.append(entry)
    except Exception:
        pass

    return {"personalities": result, "active": config.personality}


@router.get("/api/personalities/{name}")
async def api_personality_get(name: str):
    """Get a personality's content."""
    from radar.agent import load_personality

    content = load_personality(name)
    return {"name": name, "content": content}


@router.put("/api/personalities/{name}")
async def api_personality_update(name: str, request: Request):
    """Update a personality's content."""
    from radar.agent import get_personalities_dir

    form = await request.form()
    content = form.get("content", "")

    personalities_dir = get_personalities_dir()

    # Check for directory-based personality first
    personality_dir = personalities_dir / name
    personality_md = personality_dir / "PERSONALITY.md"
    if personality_dir.is_dir() and personality_md.exists():
        personality_md.write_text(content)
    else:
        personality_file = personalities_dir / f"{name}.md"
        personality_file.write_text(content)

    return HTMLResponse(
        f'<div class="text-phosphor">✓ Personality "{escape(name)}" saved</div>'
    )


@router.post("/api/personalities")
async def api_personality_create(request: Request):
    """Create a new personality."""
    from radar.agent import get_personalities_dir, DEFAULT_PERSONALITY

    form = await request.form()
    name = form.get("name", "").strip()
    directory = form.get("directory", "") == "true"

    if not name:
        return HTMLResponse(
            '<div class="text-error">Name is required</div>',
            status_code=400,
        )

    # Sanitize name (alphanumeric, dash, underscore only)
    if not re.match(r'^[a-zA-Z0-9_-]+$', name):
        return HTMLResponse(
            '<div class="text-error">Invalid name. Use only letters, numbers, dash, underscore.</div>',
            status_code=400,
        )

    personalities_dir = get_personalities_dir()

    # Check both formats for conflicts
    personality_file = personalities_dir / f"{name}.md"
    personality_dir = personalities_dir / name

    if personality_file.exists() or (personality_dir.is_dir() and (personality_dir / "PERSONALITY.md").exists()):
        return HTMLResponse(
            f'<div class="text-error">Personality "{escape(name)}" already exists</div>',
            status_code=400,
        )

    # Create from template
    content = DEFAULT_PERSONALITY.replace("# Default", f"# {name.title()}")
    content = content.replace("A practical, local-first AI assistant.", f"A custom personality: {name}")

    if directory:
        personality_dir.mkdir(parents=True, exist_ok=True)
        (personality_dir / "context").mkdir(exist_ok=True)
        (personality_dir / "PERSONALITY.md").write_text(content)
    else:
        personality_file.write_text(content)

    # Return redirect response
    return RedirectResponse(url=f"/personalities?created={name}", status_code=303)


@router.delete("/api/personalities/{name}")
async def api_personality_delete(name: str):
    """Delete a personality."""
    import shutil

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
    personality_dir = personalities_dir / name

    if personality_file.exists():
        personality_file.unlink()
    elif personality_dir.is_dir() and (personality_dir / "PERSONALITY.md").exists():
        shutil.rmtree(personality_dir)
    else:
        return HTMLResponse(
            f'<div class="text-error">Personality "{escape(name)}" not found</div>',
            status_code=404,
        )

    # Return empty response for HTMX to remove the element
    return HTMLResponse("")


@router.post("/api/personalities/{name}/activate")
async def api_personality_activate(name: str):
    """Set a personality as active."""
    import yaml
    from radar.agent import get_personalities_dir
    from radar.config import get_config_path, reload_config

    personalities_dir = get_personalities_dir()
    personality_file = personalities_dir / f"{name}.md"
    personality_dir = personalities_dir / name

    exists = (
        personality_file.exists()
        or (personality_dir.is_dir() and (personality_dir / "PERSONALITY.md").exists())
    )
    if not exists:
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


@router.get("/personalities/suggestions", response_class=HTMLResponse)
async def personality_suggestions(request: Request):
    """Personality suggestions review page."""
    from radar.feedback import get_pending_suggestions, get_feedback_summary

    context = get_common_context(request, "personalities")

    suggestions = get_pending_suggestions()
    feedback_summary = get_feedback_summary()

    context["suggestions"] = suggestions
    context["feedback_summary"] = feedback_summary

    return templates.TemplateResponse("personality_suggestions.html", context)


@router.post("/api/personalities/suggestions/{suggestion_id}/approve")
async def api_suggestion_approve(suggestion_id: int):
    """Approve a personality suggestion."""
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


@router.post("/api/personalities/suggestions/{suggestion_id}/reject")
async def api_suggestion_reject(suggestion_id: int, request: Request):
    """Reject a personality suggestion."""
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


@router.get("/api/feedback/summary")
async def api_feedback_summary():
    """Get feedback statistics summary."""
    from radar.feedback import get_feedback_summary

    return get_feedback_summary()
