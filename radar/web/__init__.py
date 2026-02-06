"""Radar Web Dashboard - FastAPI + HTMX"""

import secrets
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path

# Paths
WEB_DIR = Path(__file__).parent
STATIC_DIR = WEB_DIR / "static"
TEMPLATES_DIR = WEB_DIR / "templates"

# FastAPI app
app = FastAPI(title="Radar", docs_url=None, redoc_url=None)

# Static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def _is_localhost(host: str) -> bool:
    """Check if host is localhost."""
    return host in ("127.0.0.1", "localhost", "::1")


def _requires_auth() -> tuple[bool, str]:
    """Check if auth is required and return (required, token)."""
    from radar.config import get_config
    config = get_config()

    # Auth required if binding to non-localhost
    if _is_localhost(config.web.host):
        return False, ""

    return True, config.web.auth_token


def _check_auth(request: Request) -> bool:
    """Check if request is authenticated."""
    requires, token = _requires_auth()

    if not requires:
        return True

    if not token:
        # No token configured but auth required - deny all
        return False

    # Check cookie
    cookie_token = request.cookies.get("radar_auth")
    if cookie_token and secrets.compare_digest(cookie_token, token):
        return True

    # Check Authorization header
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        header_token = auth_header[7:]
        if secrets.compare_digest(header_token, token):
            return True

    # Check query parameter (for initial login)
    query_token = request.query_params.get("token")
    if query_token and secrets.compare_digest(query_token, token):
        return True

    return False


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Check authentication for non-localhost bindings."""
    # Allow static files without auth
    if request.url.path.startswith("/static"):
        return await call_next(request)

    # Allow login page
    if request.url.path == "/login":
        return await call_next(request)

    # Check auth
    if not _check_auth(request):
        requires, token = _requires_auth()
        if requires and not token:
            # No token configured - show error
            return HTMLResponse(
                content="""
                <html><body style="font-family: monospace; padding: 2em; background: #0a0e0d; color: #f87171;">
                <h1>Authentication Required</h1>
                <p>Web UI is exposed on a non-localhost address but no auth_token is configured.</p>
                <p>Add to radar.yaml:</p>
                <pre style="background: #1a2422; padding: 1em; color: #4ade80;">
web:
  auth_token: "your-secret-token-here"</pre>
                <p>Or set environment variable: RADAR_WEB_AUTH_TOKEN</p>
                <p>Generate a token: <code>python -c "import secrets; print(secrets.token_urlsafe(32))"</code></p>
                </body></html>
                """,
                status_code=403,
            )
        # Redirect to login
        return RedirectResponse(url="/login", status_code=302)

    # Handle token in query param - set cookie and redirect
    query_token = request.query_params.get("token")
    if query_token:
        _, expected_token = _requires_auth()
        if expected_token and secrets.compare_digest(query_token, expected_token):
            response = RedirectResponse(url=request.url.path, status_code=302)
            response.set_cookie(
                key="radar_auth",
                value=query_token,
                httponly=True,
                max_age=86400 * 30,  # 30 days
                samesite="strict",
            )
            return response

    return await call_next(request)


def get_common_context(request: Request, active_page: str) -> dict:
    """Get common template context."""
    from radar.config import load_config
    from radar.scheduler import get_status

    config = load_config()
    sched_status = get_status()

    # Determine heartbeat status
    if sched_status.get("quiet_hours"):
        heartbeat_status = "quiet"
        heartbeat_label = "Quiet Hours"
    elif sched_status.get("running"):
        heartbeat_status = "ok"
        heartbeat_label = "System Active"
    else:
        heartbeat_status = "stopped"
        heartbeat_label = "Scheduler Stopped"

    return {
        "request": request,
        "active_page": active_page,
        "model": config.llm.model,
        "llm_provider": config.llm.provider,
        "llm_url": config.llm.base_url.replace("http://", "").replace("https://", ""),
        "ntfy_configured": bool(config.notifications.topic),
        "heartbeat_status": heartbeat_status,
        "heartbeat_label": heartbeat_label,
    }


# Register route modules
from radar.web.routes.auth import router as auth_router
from radar.web.routes.dashboard import router as dashboard_router
from radar.web.routes.chat import router as chat_router
from radar.web.routes.tasks import router as tasks_router
from radar.web.routes.memory import router as memory_router
from radar.web.routes.config import router as config_router
from radar.web.routes.logs import router as logs_router
from radar.web.routes.personalities import router as personalities_router
from radar.web.routes.plugins import router as plugins_router

for _r in [auth_router, dashboard_router, chat_router, tasks_router,
           memory_router, config_router, logs_router, personalities_router,
           plugins_router]:
    app.include_router(_r)


def run_server(host: str = "127.0.0.1", port: int = 8420):
    """Run the web server."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
