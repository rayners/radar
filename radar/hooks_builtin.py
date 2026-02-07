"""Config-driven hook builders.

Reads hooks.rules from radar.yaml and registers hook callbacks.
"""

import logging
from datetime import datetime
from typing import Any

from radar.hooks import HookPoint, HookRegistration, HookResult, register_hook

logger = logging.getLogger("radar.hooks")


def load_config_hooks() -> int:
    """Load hooks from config and register them.

    Returns count of hooks registered.
    """
    try:
        from radar.config import get_config
        config = get_config()
    except Exception:
        return 0

    if not config.hooks.enabled:
        return 0

    count = 0
    for rule in config.hooks.rules:
        try:
            registration = _build_hook(rule)
            if registration:
                register_hook(registration)
                count += 1
        except Exception:
            logger.warning(
                "Failed to build hook from rule: %s",
                rule.get("name", "(unnamed)"),
                exc_info=True,
            )

    if count:
        logger.info("Loaded %d config hook(s)", count)
    return count


def _build_hook(rule: dict) -> HookRegistration | None:
    """Build a HookRegistration from a config rule dict."""
    name = rule.get("name", "unnamed")
    hook_point_str = rule.get("hook_point", "")
    rule_type = rule.get("type", "")
    priority = rule.get("priority", 50)

    try:
        hook_point = HookPoint(hook_point_str)
    except ValueError:
        logger.warning("Unknown hook_point '%s' in rule '%s'", hook_point_str, name)
        return None

    callback = _build_callback(hook_point, rule_type, rule)
    if callback is None:
        logger.warning("Unknown rule type '%s' in rule '%s'", rule_type, name)
        return None

    return HookRegistration(
        name=name,
        hook_point=hook_point,
        callback=callback,
        priority=priority,
        source="config",
        description=rule.get("description", f"{rule_type} rule"),
    )


def _build_callback(
    hook_point: HookPoint,
    rule_type: str,
    rule: dict,
) -> Any:
    """Build a callback function for a rule type."""
    if hook_point == HookPoint.PRE_TOOL_CALL:
        return _build_pre_callback(rule_type, rule)
    elif hook_point == HookPoint.POST_TOOL_CALL:
        return _build_post_callback(rule_type, rule)
    elif hook_point == HookPoint.FILTER_TOOLS:
        return _build_filter_callback(rule_type, rule)
    return None


# --- Pre-tool callbacks ---


def _build_pre_callback(rule_type: str, rule: dict) -> Any:
    """Build a pre-tool-call callback."""
    if rule_type == "block_command_pattern":
        return _make_block_command_pattern(rule)
    elif rule_type == "block_path_pattern":
        return _make_block_path_pattern(rule)
    elif rule_type == "block_tool":
        return _make_block_tool(rule)
    return None


def _make_block_command_pattern(rule: dict) -> Any:
    """Block exec commands matching substring patterns."""
    patterns = rule.get("patterns", [])
    tools = set(rule.get("tools", ["exec"]))
    message = rule.get("message", "Command blocked by hook")

    def callback(tool_name: str, arguments: dict) -> HookResult:
        if tool_name not in tools:
            return HookResult()
        command = arguments.get("command", "")
        for pattern in patterns:
            if pattern in command:
                return HookResult(blocked=True, message=message)
        return HookResult()

    return callback


def _make_block_path_pattern(rule: dict) -> Any:
    """Block file tools accessing paths under configured directories."""
    from pathlib import Path

    blocked_dirs = [Path(d).expanduser().resolve() for d in rule.get("paths", [])]
    tools = set(rule.get("tools", ["read_file", "write_file"]))
    message = rule.get("message", "Path blocked by hook")

    def callback(tool_name: str, arguments: dict) -> HookResult:
        if tool_name not in tools:
            return HookResult()
        path_str = arguments.get("path", "") or arguments.get("file_path", "")
        if not path_str:
            return HookResult()
        try:
            target = Path(path_str).expanduser().resolve()
            for blocked in blocked_dirs:
                if target == blocked or blocked in target.parents:
                    return HookResult(blocked=True, message=message)
        except Exception:
            pass
        return HookResult()

    return callback


def _make_block_tool(rule: dict) -> Any:
    """Block specific tools entirely."""
    blocked_tools = set(rule.get("tools", []))
    message = rule.get("message", "Tool blocked by hook")

    def callback(tool_name: str, arguments: dict) -> HookResult:
        if tool_name in blocked_tools:
            return HookResult(blocked=True, message=message)
        return HookResult()

    return callback


# --- Post-tool callbacks ---


def _build_post_callback(rule_type: str, rule: dict) -> Any:
    """Build a post-tool-call callback."""
    if rule_type == "log":
        return _make_log_callback(rule)
    return None


def _make_log_callback(rule: dict) -> Any:
    """Log tool execution."""
    log_level = rule.get("log_level", "info")

    def callback(
        tool_name: str,
        arguments: dict,
        result: str,
        success: bool,
    ) -> None:
        from radar.logging import log
        status = "success" if success else "failure"
        log(log_level, f"Hook log: {tool_name} ({status})", tool=tool_name)

    return callback


# --- Filter callbacks ---


def _build_filter_callback(rule_type: str, rule: dict) -> Any:
    """Build a filter-tools callback."""
    if rule_type == "time_restrict":
        return _make_time_restrict(rule)
    elif rule_type == "allowlist":
        return _make_allowlist(rule)
    elif rule_type == "denylist":
        return _make_denylist(rule)
    return None


def _make_time_restrict(rule: dict) -> Any:
    """Remove tools during a time window."""
    start_hour = rule.get("start_hour", 22)
    end_hour = rule.get("end_hour", 8)
    restricted_tools = set(rule.get("tools", []))

    def callback(tools: list[dict]) -> list[dict]:
        hour = datetime.now().hour
        # Check if current hour falls in restricted window
        if start_hour > end_hour:
            # Wraps midnight (e.g., 22:00-08:00)
            in_window = hour >= start_hour or hour < end_hour
        else:
            # Same-day window (e.g., 09:00-17:00)
            in_window = start_hour <= hour < end_hour

        if not in_window:
            return tools

        return [
            t for t in tools
            if t.get("function", {}).get("name") not in restricted_tools
        ]

    return callback


def _make_allowlist(rule: dict) -> Any:
    """Only keep tools in the allowlist."""
    allowed = set(rule.get("tools", []))

    def callback(tools: list[dict]) -> list[dict]:
        return [
            t for t in tools
            if t.get("function", {}).get("name") in allowed
        ]

    return callback


def _make_denylist(rule: dict) -> Any:
    """Remove tools in the denylist."""
    denied = set(rule.get("tools", []))

    def callback(tools: list[dict]) -> list[dict]:
        return [
            t for t in tools
            if t.get("function", {}).get("name") not in denied
        ]

    return callback
