"""Config routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from radar.web import templates, get_common_context

router = APIRouter()


@router.get("/config", response_class=HTMLResponse)
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
            "fallback_model": config.llm.fallback_model,
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


@router.get("/api/config/test")
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
