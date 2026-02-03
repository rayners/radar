"""Radar Web Dashboard - FastAPI + HTMX"""

from fastapi import FastAPI, Request
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
        "model": config.ollama.model,
        "ollama_url": config.ollama.base_url.replace("http://", ""),
        "ntfy_configured": bool(config.notifications.topic),
        "heartbeat_status": heartbeat_status,
        "heartbeat_label": heartbeat_label,
    }


# Import routes
from radar.web import routes  # noqa: E402, F401
