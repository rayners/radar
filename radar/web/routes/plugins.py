"""Plugin routes."""

from html import escape

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from radar.web import templates, get_common_context

router = APIRouter()


@router.get("/plugins", response_class=HTMLResponse)
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


@router.get("/plugins/review", response_class=HTMLResponse)
async def plugins_review(request: Request):
    """Plugin review page for pending plugins."""
    from radar.plugins import get_plugin_loader

    context = get_common_context(request, "plugins")
    loader = get_plugin_loader()

    pending_list = loader.list_pending()
    context["pending_plugins"] = pending_list

    return templates.TemplateResponse("plugin_review.html", context)


@router.get("/plugins/{name}", response_class=HTMLResponse)
async def plugin_detail(request: Request, name: str):
    """Plugin detail page."""
    import yaml
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

    # Get tools from manifest
    tools_list = manifest.get("tools", [])

    context["plugin"] = manifest
    context["code"] = code
    context["versions"] = versions
    context["errors"] = [e.to_dict() for e in errors]
    context["plugin_tools"] = tools_list

    return templates.TemplateResponse("plugin_detail.html", context)


# ===== Plugin API Routes =====


@router.post("/api/plugins/{name}/enable")
async def api_plugin_enable(name: str):
    """Enable a plugin."""
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


@router.post("/api/plugins/{name}/disable")
async def api_plugin_disable(name: str):
    """Disable a plugin."""
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


@router.post("/api/plugins/{name}/approve")
async def api_plugin_approve(name: str):
    """Approve a pending plugin."""
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


@router.post("/api/plugins/{name}/reject")
async def api_plugin_reject(name: str, request: Request):
    """Reject a pending plugin."""
    from radar.plugins import get_plugin_loader

    form = await request.form()
    reason = form.get("reason", "")

    loader = get_plugin_loader()
    success, message = loader.reject_plugin(name, reason)

    if success:
        return HTMLResponse("")  # Remove from list
    return HTMLResponse(f'<div class="text-error">{escape(message)}</div>', status_code=400)


@router.put("/api/plugins/{name}/code")
async def api_plugin_update_code(name: str, request: Request):
    """Update a plugin's code."""
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


@router.post("/api/plugins/{name}/rollback/{version}")
async def api_plugin_rollback(name: str, version: str):
    """Rollback a plugin to a previous version."""
    from radar.plugins import get_plugin_loader

    loader = get_plugin_loader()
    success, message = loader.rollback_plugin(name, version)

    if success:
        return HTMLResponse(f'<div class="text-phosphor">{escape(message)}</div>')
    return HTMLResponse(f'<div class="text-error">{escape(message)}</div>', status_code=400)


@router.get("/api/plugins/{name}/widget")
async def api_plugin_widget(name: str):
    """Refresh a plugin's dashboard widget."""
    import jinja2
    from radar.plugins import get_plugin_loader

    loader = get_plugin_loader()
    widgets = loader.get_widgets()
    widget = next((w for w in widgets if w["name"] == name), None)

    if not widget:
        return HTMLResponse(
            f'<div class="text-error">Widget not found for plugin {escape(name)}</div>',
            status_code=404,
        )

    env = jinja2.sandbox.SandboxedEnvironment(autoescape=True)
    template = env.from_string(widget["template_content"])
    rendered = template.render(plugin_name=name)
    return HTMLResponse(rendered)
