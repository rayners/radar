"""Health check endpoint."""

from datetime import datetime

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health(check_services: bool = False):
    """Health check endpoint.

    Returns basic health info by default. Pass ?check_services=true
    to also ping LLM, embedding, and database backends.
    """
    from radar.config import load_config
    from radar.logging import get_uptime, get_log_stats
    from radar.scheduler import get_status as get_scheduler_status

    config = load_config()
    sched = get_scheduler_status()
    stats = get_log_stats()
    uptime = get_uptime()

    result = {
        "status": "healthy",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "uptime": uptime,
        "scheduler": {
            "running": sched["running"],
            "last_heartbeat": sched["last_heartbeat"],
            "next_heartbeat": sched["next_heartbeat"],
            "pending_events": sched["pending_events"],
            "quiet_hours": sched["quiet_hours"],
        },
        "stats": {
            "errors_24h": stats["error_count"],
            "warnings_24h": stats["warn_count"],
            "api_calls": stats["api_calls"],
        },
    }

    # Derive status from basic info
    if not sched["running"] or stats["error_count"] > 0:
        result["status"] = "degraded"

    if check_services:
        llm_info = await _check_llm(config)
        emb_info = await _check_embeddings(config)
        db_info = _check_database()

        result["llm"] = llm_info
        result["embeddings"] = emb_info
        result["database"] = db_info

        # Upgrade to unhealthy if LLM or DB unreachable
        if llm_info["status"] == "unreachable":
            result["status"] = "unhealthy"
        if db_info["status"] == "error":
            result["status"] = "unhealthy"

    return JSONResponse(content=result)


async def _check_llm(config) -> dict:
    """Ping the LLM endpoint and measure response time."""
    info = {
        "provider": config.llm.provider,
        "model": config.llm.model,
    }
    try:
        start = datetime.now()
        async with httpx.AsyncClient() as client:
            if config.llm.provider == "ollama":
                url = f"{config.llm.base_url}/api/tags"
                resp = await client.get(url, timeout=3.0)
            else:
                url = f"{config.llm.base_url}/models"
                headers = {}
                if config.llm.api_key:
                    headers["Authorization"] = f"Bearer {config.llm.api_key}"
                resp = await client.get(url, headers=headers, timeout=3.0)

        elapsed_ms = int((datetime.now() - start).total_seconds() * 1000)

        if resp.status_code == 200:
            info["status"] = "ok"
            info["response_time_ms"] = elapsed_ms
        else:
            info["status"] = "error"
            info["http_status"] = resp.status_code
    except (httpx.ConnectError, httpx.TimeoutException):
        info["status"] = "unreachable"
    except Exception as exc:
        info["status"] = "error"
        info["error"] = str(exc)

    return info


async def _check_embeddings(config) -> dict:
    """Check embedding provider availability."""
    info = {
        "provider": config.embedding.provider,
        "model": config.embedding.model,
    }

    if config.embedding.provider == "none":
        info["status"] = "disabled"
        return info

    if config.embedding.provider == "local":
        info["status"] = "ok"
        return info

    # For ollama/openai, ping the endpoint
    try:
        base_url = getattr(config.embedding, "base_url", None) or config.llm.base_url
        async with httpx.AsyncClient() as client:
            if config.embedding.provider == "ollama":
                resp = await client.get(f"{base_url}/api/tags", timeout=3.0)
            else:
                headers = {}
                api_key = getattr(config.embedding, "api_key", None) or config.llm.api_key
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                resp = await client.get(f"{base_url}/models", headers=headers, timeout=3.0)

        info["status"] = "ok" if resp.status_code == 200 else "error"
    except (httpx.ConnectError, httpx.TimeoutException):
        info["status"] = "unreachable"
    except Exception:
        info["status"] = "error"

    return info


def _check_database() -> dict:
    """Check database connectivity and get memory count."""
    try:
        from radar.semantic import _get_connection
        conn = _get_connection()
        cursor = conn.execute("SELECT COUNT(*) FROM memories")
        count = cursor.fetchone()[0]
        conn.close()
        return {"status": "ok", "memory_count": count}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
