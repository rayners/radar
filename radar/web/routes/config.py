"""Config routes."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from radar.web import templates, get_common_context

router = APIRouter()

# Fields that should be coerced from string to int
_NUMERIC_FIELDS = {
    "tools.max_file_size",
    "tools.exec_timeout",
    "max_tool_iterations",
}

_SENSITIVE_KEYS = {"auth_token", "api_key", "api_key_env", "token", "secret"}


def _redact_sensitive_yaml(yaml_text: str) -> str:
    """Redact sensitive values in YAML text for display."""
    import re

    lines = yaml_text.split("\n")
    redacted = []
    for line in lines:
        # Match YAML key: value lines where the key is sensitive
        match = re.match(r"^(\s*)([\w_]+)\s*:\s*(.+)$", line)
        if match:
            indent, key, value = match.groups()
            if key.lower() in _SENSITIVE_KEYS and value.strip() and value.strip() not in ('""', "''", '~', 'null', ''):
                redacted.append(f"{indent}{key}: ***")
                continue
        redacted.append(line)
    return "\n".join(redacted)


_VALID_LLM_PROVIDERS = {"ollama", "openai"}
_VALID_EMBEDDING_PROVIDERS = {"ollama", "openai", "local", "none"}

# Allowlist of config fields that can be saved via the web UI.
# Prevents overwriting security-sensitive fields like plugins.auto_approve,
# tools.exec_mode, web.auth_token, etc.
_ALLOWED_FIELDS = {
    "llm.provider",
    "llm.base_url",
    "llm.model",
    "llm.fallback_model",
    "embedding.provider",
    "embedding.model",
    "notifications.url",
    "notifications.topic",
    "tools.max_file_size",
    "tools.exec_timeout",
    "max_tool_iterations",
}


def _coerce_value(key: str, value: str) -> int | str:
    """Convert string value to appropriate type based on field name."""
    if key in _NUMERIC_FIELDS:
        return int(value)
    return value


def _deep_merge(base: dict, updates: dict) -> dict:
    """Recursively merge updates into base dict."""
    result = dict(base)
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate_config(data: dict) -> list[str]:
    """Validate config data and return list of errors."""
    errors = []

    llm = data.get("llm", {})
    if llm.get("provider") and llm["provider"] not in _VALID_LLM_PROVIDERS:
        errors.append(f"Invalid LLM provider: {llm['provider']}. Must be one of: {', '.join(_VALID_LLM_PROVIDERS)}")

    embedding = data.get("embedding", {})
    if embedding.get("provider") and embedding["provider"] not in _VALID_EMBEDDING_PROVIDERS:
        errors.append(f"Invalid embedding provider: {embedding['provider']}. Must be one of: {', '.join(_VALID_EMBEDDING_PROVIDERS)}")

    # Validate numeric fields are positive
    for field_path in _NUMERIC_FIELDS:
        parts = field_path.split(".")
        obj = data
        for part in parts[:-1]:
            obj = obj.get(part, {})
            if not isinstance(obj, dict):
                break
        else:
            val = obj.get(parts[-1])
            if val is not None and (not isinstance(val, int) or val <= 0):
                errors.append(f"{field_path} must be a positive integer")

    return errors


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

    # Load raw YAML for display, redacting sensitive values
    if config_path and config_path.exists():
        context["config_yaml"] = _redact_sensitive_yaml(config_path.read_text())
    else:
        context["config_yaml"] = "# No configuration file found"

    return templates.TemplateResponse("config.html", context)


@router.post("/api/config", response_class=HTMLResponse)
async def api_config_save(request: Request):
    """Save configuration from form."""
    from html import escape
    from pathlib import Path

    import yaml
    from radar.config import get_config_path, reload_config

    form = await request.form()

    # Parse dot-notation form fields into nested dict
    updates: dict = {}
    for key, value in form.items():
        value = str(value).strip()
        if not value:
            continue

        # Reject fields not in the allowlist
        if key not in _ALLOWED_FIELDS:
            continue

        try:
            coerced = _coerce_value(key, value)
        except (ValueError, TypeError):
            return HTMLResponse(
                f'<div class="text-error">Invalid value for {escape(key)}</div>',
                status_code=400,
            )

        # Build nested dict from dot-notation key
        parts = key.split(".")
        obj = updates
        for part in parts[:-1]:
            obj = obj.setdefault(part, {})
        obj[parts[-1]] = coerced

    # Validate
    errors = _validate_config(updates)
    if errors:
        error_html = "".join(f"<li>{escape(e)}</li>" for e in errors)
        return HTMLResponse(
            f'<div class="text-error">Validation errors:<ul>{error_html}</ul></div>',
            status_code=400,
        )

    # Load existing config file or create new
    config_path = get_config_path()
    if config_path and config_path.exists():
        existing = yaml.safe_load(config_path.read_text()) or {}
    else:
        existing = {}
        config_path = Path.home() / ".config" / "radar" / "radar.yaml"
        config_path.parent.mkdir(parents=True, exist_ok=True)

    # Merge and save
    merged = _deep_merge(existing, updates)
    config_path.write_text(yaml.dump(merged, default_flow_style=False))

    # Reload config singleton
    reload_config()

    return HTMLResponse('<div class="text-phosphor">Configuration saved successfully.</div>')


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
