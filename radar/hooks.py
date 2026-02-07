"""Hook system for intercepting tool execution and filtering tool lists."""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("radar.hooks")


class HookPoint(Enum):
    """Points where hooks can intercept."""

    PRE_TOOL_CALL = "pre_tool_call"
    POST_TOOL_CALL = "post_tool_call"
    FILTER_TOOLS = "filter_tools"


@dataclass
class HookResult:
    """Result from a pre-tool hook."""

    blocked: bool = False
    message: str = ""


@dataclass
class HookRegistration:
    """A registered hook callback."""

    name: str
    hook_point: HookPoint
    callback: Callable
    priority: int = 50
    source: str = ""  # e.g. "config", "plugin:my_plugin"
    description: str = ""


# Global registry: hook point -> sorted list of registrations
_hooks: dict[HookPoint, list[HookRegistration]] = {
    HookPoint.PRE_TOOL_CALL: [],
    HookPoint.POST_TOOL_CALL: [],
    HookPoint.FILTER_TOOLS: [],
}


def register_hook(registration: HookRegistration) -> None:
    """Register a hook callback.

    Hooks are kept sorted by priority (lower numbers run first).
    """
    hooks_list = _hooks[registration.hook_point]
    hooks_list.append(registration)
    hooks_list.sort(key=lambda h: h.priority)
    logger.debug(
        "Registered hook '%s' at %s (priority %d, source=%s)",
        registration.name,
        registration.hook_point.value,
        registration.priority,
        registration.source,
    )


def unregister_hook(name: str) -> bool:
    """Unregister a hook by name.

    Returns True if a hook was removed.
    """
    removed = False
    for hook_point in _hooks:
        before = len(_hooks[hook_point])
        _hooks[hook_point] = [h for h in _hooks[hook_point] if h.name != name]
        if len(_hooks[hook_point]) < before:
            removed = True
    return removed


def unregister_hooks_by_source(source: str) -> int:
    """Unregister all hooks from a given source.

    Returns count of hooks removed.
    """
    count = 0
    for hook_point in _hooks:
        before = len(_hooks[hook_point])
        _hooks[hook_point] = [h for h in _hooks[hook_point] if h.source != source]
        count += before - len(_hooks[hook_point])
    return count


def clear_all_hooks() -> None:
    """Remove all registered hooks."""
    for hook_point in _hooks:
        _hooks[hook_point].clear()


def list_hooks() -> list[dict[str, Any]]:
    """List all registered hooks for introspection."""
    result = []
    for hook_point, hooks_list in _hooks.items():
        for h in hooks_list:
            result.append({
                "name": h.name,
                "hook_point": hook_point.value,
                "priority": h.priority,
                "source": h.source,
                "description": h.description,
            })
    return result


def run_pre_tool_hooks(tool_name: str, arguments: dict[str, Any]) -> HookResult:
    """Run all pre-tool-call hooks.

    Returns a HookResult. If any hook blocks, short-circuits immediately.
    """
    hooks_list = _hooks[HookPoint.PRE_TOOL_CALL]
    if not hooks_list:
        return HookResult()

    for hook in hooks_list:
        try:
            result = hook.callback(tool_name, arguments)
            if isinstance(result, HookResult) and result.blocked:
                logger.info(
                    "Hook '%s' blocked tool '%s': %s",
                    hook.name, tool_name, result.message,
                )
                return result
        except Exception:
            logger.warning(
                "Hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )

    return HookResult()


def run_post_tool_hooks(
    tool_name: str,
    arguments: dict[str, Any],
    result: str,
    success: bool,
) -> None:
    """Run all post-tool-call hooks (observe only, cannot block)."""
    hooks_list = _hooks[HookPoint.POST_TOOL_CALL]
    if not hooks_list:
        return

    for hook in hooks_list:
        try:
            hook.callback(tool_name, arguments, result, success)
        except Exception:
            logger.warning(
                "Post-hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )


def run_filter_tools_hooks(tools: list[dict]) -> list[dict]:
    """Run all filter-tools hooks, chaining the result.

    Each hook receives the tool list and returns a (possibly filtered) list.
    """
    hooks_list = _hooks[HookPoint.FILTER_TOOLS]
    if not hooks_list:
        return tools

    for hook in hooks_list:
        try:
            filtered = hook.callback(tools)
            if isinstance(filtered, list):
                tools = filtered
        except Exception:
            logger.warning(
                "Filter hook '%s' raised an exception (skipping)",
                hook.name,
                exc_info=True,
            )

    return tools
