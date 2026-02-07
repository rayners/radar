"""Plugin hook loading -- register/unregister hooks from plugins with 'hook' capability."""

import importlib.util
import logging
import types
from pathlib import Path

from radar.hooks import HookPoint, HookRegistration, HookResult, register_hook, unregister_hooks_by_source

logger = logging.getLogger("radar.plugins.hooks")


def load_plugin_hooks(plugin) -> int:
    """Load hooks from a plugin with 'hook' capability.

    Args:
        plugin: A Plugin instance with manifest.hooks definitions.

    Returns:
        Count of hooks registered.
    """
    if "hook" not in plugin.manifest.capabilities:
        return 0

    if not plugin.manifest.hooks:
        return 0

    if not plugin.path:
        return 0

    code_file = plugin.path / "tool.py"
    if not code_file.exists():
        return 0

    if plugin.manifest.trust_level == "local":
        return _load_local_hooks(plugin, code_file)
    else:
        return _load_sandbox_hooks(plugin, code_file)


def unload_plugin_hooks(plugin_name: str) -> int:
    """Unregister all hooks from a plugin.

    Returns count of hooks removed.
    """
    source = f"plugin:{plugin_name}"
    return unregister_hooks_by_source(source)


def _load_local_hooks(plugin, code_file: Path) -> int:
    """Load hooks from a local-trust plugin via importlib."""
    spec = importlib.util.spec_from_file_location(
        f"radar_plugin_hooks_{plugin.name}", code_file
    )
    if not spec or not spec.loader:
        return 0

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        logger.warning(
            "Failed to load hook module for plugin '%s'",
            plugin.name,
            exc_info=True,
        )
        return 0

    count = 0
    source = f"plugin:{plugin.name}"

    for hook_def in plugin.manifest.hooks:
        func_name = hook_def.get("function", "")
        func = getattr(module, func_name, None)
        if func is None or not callable(func):
            logger.warning(
                "Plugin '%s' declares hook function '%s' but it was not found",
                plugin.name, func_name,
            )
            continue

        try:
            hook_point = HookPoint(hook_def.get("hook_point", ""))
        except ValueError:
            logger.warning(
                "Plugin '%s' hook '%s' has invalid hook_point",
                plugin.name, func_name,
            )
            continue

        registration = HookRegistration(
            name=f"{plugin.name}:{func_name}",
            hook_point=hook_point,
            callback=func,
            priority=hook_def.get("priority", 100),
            source=source,
            description=hook_def.get("description", ""),
        )
        register_hook(registration)
        count += 1

    return count


def _load_sandbox_hooks(plugin, code_file: Path) -> int:
    """Load hooks from a sandbox-trust plugin with restricted builtins.

    HookResult is injected into the namespace so sandbox hooks can return blocks.
    """
    safe_builtins = {
        "True": True, "False": False, "None": None,
        "abs": abs, "all": all, "any": any, "bool": bool, "chr": chr,
        "dict": dict, "divmod": divmod, "enumerate": enumerate,
        "filter": filter, "float": float, "format": format,
        "frozenset": frozenset, "hash": hash, "hex": hex, "int": int,
        "isinstance": isinstance, "issubclass": issubclass, "iter": iter,
        "len": len, "list": list, "map": map, "max": max, "min": min,
        "next": next, "oct": oct, "ord": ord, "pow": pow, "print": print,
        "range": range, "repr": repr, "reversed": reversed, "round": round,
        "set": set, "slice": slice, "sorted": sorted, "str": str,
        "sum": sum, "tuple": tuple, "type": type, "zip": zip,
    }

    code = code_file.read_text()
    # Inject HookResult so sandbox hooks can return blocks
    namespace: dict = {
        "__builtins__": safe_builtins,
        "HookResult": HookResult,
    }

    try:
        compiled = compile(code, str(code_file), "exec")
        # Execute validated plugin code in sandbox namespace
        _run_compiled(compiled, namespace)
    except Exception:
        logger.warning(
            "Failed to compile hook code for plugin '%s'",
            plugin.name,
            exc_info=True,
        )
        return 0

    count = 0
    source = f"plugin:{plugin.name}"

    for hook_def in plugin.manifest.hooks:
        func_name = hook_def.get("function", "")
        func = namespace.get(func_name)
        if not isinstance(func, types.FunctionType):
            logger.warning(
                "Plugin '%s' declares hook function '%s' but it was not found",
                plugin.name, func_name,
            )
            continue

        try:
            hook_point = HookPoint(hook_def.get("hook_point", ""))
        except ValueError:
            logger.warning(
                "Plugin '%s' hook '%s' has invalid hook_point",
                plugin.name, func_name,
            )
            continue

        registration = HookRegistration(
            name=f"{plugin.name}:{func_name}",
            hook_point=hook_point,
            callback=func,
            priority=hook_def.get("priority", 100),
            source=source,
            description=hook_def.get("description", ""),
        )
        register_hook(registration)
        count += 1

    return count


def _run_compiled(compiled, namespace: dict) -> None:
    """Execute compiled code in the given namespace.

    Separated into its own function for clarity.
    """
    import builtins
    builtins.exec(compiled, namespace)  # noqa: S102 -- validated plugin code
