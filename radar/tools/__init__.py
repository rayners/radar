"""Tool registry with decorator-based registration."""

import builtins
from functools import wraps
from pathlib import Path
from typing import Any, Callable

# Global registry: name -> (function, schema)
_registry: dict[str, tuple[Callable, dict]] = {}

# Sets populated during discovery — used by is_dynamic_tool()
_static_tools: set[str] = set()
_external_tools: set[str] = set()

# External tool source tracking for hot-reload
# file_path (str) -> set of tool names registered by that file
_external_tool_sources: dict[str, set[str]] = {}
# file_path (str) -> mtime at last load
_external_tool_mtimes: dict[str, float] = {}

# Plugin name -> set of tool names registered by that plugin
_plugin_tools: dict[str, set[str]] = {}


def tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
) -> Callable:
    """Decorator to register a function as a tool.

    Args:
        name: Tool name for the API
        description: Human-readable description
        parameters: JSON Schema for parameters (properties dict)
    """

    def decorator(func: Callable) -> Callable:
        schema = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": parameters,
                    "required": [k for k, v in parameters.items() if not v.get("optional", False)],
                },
            },
        }
        _registry[name] = (func, schema)

        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator


def get_tools_schema(
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[dict]:
    """Return list of tool definitions for the API.

    Args:
        include: If set, only return tools with these names (allowlist).
        exclude: If set, return all tools except these names (denylist).
        Both None returns everything. Both set is caller error (returns all).

    After building the base list, filter hooks are applied.
    """
    ensure_external_tools_loaded()
    if include is not None:
        include_set = set(include)
        tools = [
            schema for name, (_, schema) in _registry.items()
            if name in include_set
        ]
    elif exclude is not None:
        exclude_set = set(exclude)
        tools = [
            schema for name, (_, schema) in _registry.items()
            if name not in exclude_set
        ]
    else:
        tools = [schema for _, schema in _registry.values()]

    # Apply filter hooks (lazy import to avoid circular imports)
    from radar.hooks import run_filter_tools_hooks
    return run_filter_tools_hooks(tools)


def _log_tool_execution(name: str, success: bool, error: str | None = None) -> None:
    """Log a tool execution."""
    try:
        from radar.logging import log
        if success:
            log("info", f"Tool executed: {name}", tool=name)
        else:
            log("warn", f"Tool failed: {name}", tool=name, error=error)
    except Exception:
        pass


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool by name with given arguments.

    Returns the tool's string result or error message.
    Pre-tool hooks can block execution; post-tool hooks observe the result.
    """
    if name not in _registry:
        _log_tool_execution(name, False, "Unknown tool")
        return f"Error: Unknown tool '{name}'"

    # Run pre-tool hooks (lazy import to avoid circular imports)
    from radar.hooks import run_pre_tool_hooks, run_post_tool_hooks

    hook_result = run_pre_tool_hooks(name, arguments)
    if hook_result.blocked:
        msg = hook_result.message or f"Tool '{name}' blocked by hook"
        _log_tool_execution(name, False, msg)
        run_post_tool_hooks(name, arguments, msg, False)
        return f"Error: {msg}"

    func, _ = _registry[name]
    try:
        result = func(**arguments)
        result_str = str(result)
        _log_tool_execution(name, True)
        run_post_tool_hooks(name, arguments, result_str, True)
        return result_str
    except Exception as e:
        error_msg = f"Error executing {name}: {e}"
        _log_tool_execution(name, False, str(e))
        run_post_tool_hooks(name, arguments, error_msg, False)
        return error_msg


def get_tool_names() -> list[str]:
    """Get list of registered tool names."""
    return list(_registry.keys())


def register_dynamic_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    code: str,
    extra_namespace: dict[str, Any] | None = None,
) -> bool:
    """Register a dynamically loaded tool.

    Args:
        name: Tool name for the API
        description: Human-readable description
        parameters: JSON Schema for parameters (properties dict)
        code: Python code containing the tool function
        extra_namespace: Optional extra names to inject (e.g. helper functions)

    Returns:
        True if registration succeeded, False otherwise.
    """
    # Create the tool schema
    schema = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": parameters,
                "required": [k for k, v in parameters.items() if not v.get("optional", False)],
            },
        },
    }

    # Create a safe namespace for execution
    safe_builtins = {
        "True": True,
        "False": False,
        "None": None,
        "abs": abs,
        "all": all,
        "any": any,
        "bool": bool,
        "chr": chr,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "filter": filter,
        "float": float,
        "format": format,
        "frozenset": frozenset,
        "hash": hash,
        "hex": hex,
        "int": int,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "iter": iter,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "next": next,
        "oct": oct,
        "ord": ord,
        "pow": pow,
        "print": print,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "round": round,
        "set": set,
        "slice": slice,
        "sorted": sorted,
        "str": str,
        "sum": sum,
        "tuple": tuple,
        "type": type,
        "zip": zip,
    }

    namespace: dict[str, Any] = {"__builtins__": safe_builtins}
    if extra_namespace:
        # Filter out dunder keys to prevent overriding __builtins__
        namespace.update(
            {k: v for k, v in extra_namespace.items() if not k.startswith("__")}
        )

    try:
        # Execute the code to define the function
        # Note: This code has been validated by CodeValidator before reaching here
        # Using builtins.exec() because 'exec' is shadowed by radar.tools.exec module
        builtins.exec(code, namespace)  # noqa: S102

        # Get the function
        if name not in namespace:
            return False

        func = namespace[name]

        # Register it
        _registry[name] = (func, schema)
        return True

    except Exception:
        return False


def unregister_tool(name: str) -> bool:
    """Unregister a tool by name.

    Args:
        name: Name of the tool to unregister

    Returns:
        True if tool was unregistered, False if not found.
    """
    if name in _registry:
        del _registry[name]
        return True
    return False


def register_local_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    func: Callable,
    plugin_name: str | None = None,
) -> bool:
    """Register a callable directly as a tool (no sandbox, no exec).

    Used for local-trust plugins where importlib already loaded the module.

    Args:
        name: Tool name for the API
        description: Human-readable description
        parameters: JSON Schema for parameters (properties dict)
        func: The callable to register
        plugin_name: Optional plugin name for tracking

    Returns:
        True if registration succeeded.
    """
    schema = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": parameters,
                "required": [k for k, v in parameters.items() if not v.get("optional", False)],
            },
        },
    }
    _registry[name] = (func, schema)
    if plugin_name:
        _plugin_tools.setdefault(plugin_name, set()).add(name)
    return True


def unregister_plugin_tools(plugin_name: str) -> list[str]:
    """Unregister all tools belonging to a plugin.

    Args:
        plugin_name: Name of the plugin whose tools should be removed

    Returns:
        List of tool names that were unregistered.
    """
    tool_names = _plugin_tools.pop(plugin_name, set())
    removed = []
    for name in tool_names:
        if unregister_tool(name):
            removed.append(name)
    return removed


def track_plugin_tool(plugin_name: str, tool_name: str) -> None:
    """Track a tool name as belonging to a plugin.

    Args:
        plugin_name: The plugin that owns the tool
        tool_name: The tool name to track
    """
    _plugin_tools.setdefault(plugin_name, set()).add(tool_name)


def get_plugin_tool_names(plugin_name: str) -> set[str]:
    """Get the set of tool names registered by a plugin."""
    return _plugin_tools.get(plugin_name, set()).copy()


def is_dynamic_tool(name: str) -> bool:
    """Check if a tool was dynamically registered (plugin, not built-in or external)."""
    return name in _registry and name not in _static_tools and name not in _external_tools


def _discover_tools() -> set[str]:
    """Auto-discover and import tool modules from this package."""
    import importlib
    import pkgutil

    snapshot = set(_registry.keys())
    for _finder, module_name, _is_pkg in pkgutil.iter_modules(__path__):
        if module_name.startswith("_"):
            continue
        importlib.import_module(f"radar.tools.{module_name}")
    return set(_registry.keys()) - snapshot


def _load_external_file(file: Path) -> set[str]:
    """Load a single external tool file and return the set of tool names it registered."""
    import importlib.util

    snapshot = set(_registry.keys())
    spec = importlib.util.spec_from_file_location(
        f"radar_external_tools.{file.stem}", file
    )
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    new_tools = set(_registry.keys()) - snapshot
    return new_tools


def load_external_tools(directories: list[str | Path]) -> list[str]:
    """Load tool modules from external directories.

    Args:
        directories: List of directory paths to scan for .py tool files.

    Returns:
        List of module stems that were loaded.
    """
    loaded = []
    for dir_path in directories:
        path = Path(dir_path).expanduser()
        if not path.is_dir():
            continue
        for file in sorted(path.glob("*.py")):
            if file.name.startswith("_"):
                continue
            new_tools = _load_external_file(file)
            file_key = str(file)
            _external_tool_sources[file_key] = new_tools
            try:
                _external_tool_mtimes[file_key] = file.stat().st_mtime
            except OSError:
                pass
            loaded.append(file.stem)
    return loaded


_external_tools_loaded = False


def ensure_external_tools_loaded() -> None:
    """Load external/user-local tools once. Called lazily from get_tools_schema()."""
    global _external_tools_loaded
    if _external_tools_loaded:
        return
    _external_tools_loaded = True

    try:
        from radar.config import get_config, get_data_paths

        config = get_config()
        paths = get_data_paths()

        dirs: list[str | Path] = [paths.tools]
        dirs.extend(config.tools.extra_dirs)

        snapshot = set(_registry.keys())
        load_external_tools(dirs)
        _external_tools.update(set(_registry.keys()) - snapshot - _static_tools)
    except Exception:
        # Config not available (e.g., during testing) — skip silently
        pass


def reload_external_tools() -> dict[str, list[str]]:
    """Reload external tools, adding new ones and removing stale ones.

    Returns dict with keys: added, removed, reloaded (lists of tool names).
    """
    from radar.config import get_config, get_data_paths

    config = get_config()
    paths = get_data_paths()
    dirs = [paths.tools] + [Path(d).expanduser() for d in config.tools.extra_dirs]

    # Discover what's currently on disk
    current_files: dict[str, Path] = {}  # file_key -> Path
    for dir_path in dirs:
        if not dir_path.is_dir():
            continue
        for f in sorted(dir_path.glob("*.py")):
            if f.name.startswith("_"):
                continue
            current_files[str(f)] = f

    added: list[str] = []
    removed: list[str] = []
    reloaded: list[str] = []

    # Remove tools from files that no longer exist on disk
    stale_keys = set(_external_tool_sources.keys()) - set(current_files.keys())
    for file_key in stale_keys:
        tool_names = _external_tool_sources.pop(file_key, set())
        _external_tool_mtimes.pop(file_key, None)
        for name in tool_names:
            unregister_tool(name)
            _external_tools.discard(name)
            removed.append(name)

    # Process current files: add new, reload changed, skip unchanged
    for file_key, file_path in current_files.items():
        try:
            current_mtime = file_path.stat().st_mtime
        except OSError:
            continue

        if file_key not in _external_tool_sources:
            # New file — load it
            new_tools = _load_external_file(file_path)
            _external_tool_sources[file_key] = new_tools
            _external_tool_mtimes[file_key] = current_mtime
            _external_tools.update(new_tools)
            added.extend(new_tools)
        elif current_mtime != _external_tool_mtimes.get(file_key):
            # Changed file — unregister old tools, re-import
            old_tools = _external_tool_sources.get(file_key, set())
            for name in old_tools:
                unregister_tool(name)
                _external_tools.discard(name)
            new_tools = _load_external_file(file_path)
            _external_tool_sources[file_key] = new_tools
            _external_tool_mtimes[file_key] = current_mtime
            _external_tools.update(new_tools)
            reloaded.extend(new_tools)
        # else: unchanged — skip

    return {"added": added, "removed": removed, "reloaded": reloaded}


# Auto-discover built-in tool modules at import time
_static_tools = _discover_tools()

__all__ = [
    "tool",
    "get_tools_schema",
    "execute_tool",
    "get_tool_names",
    "register_dynamic_tool",
    "register_local_tool",
    "unregister_tool",
    "unregister_plugin_tools",
    "track_plugin_tool",
    "get_plugin_tool_names",
    "is_dynamic_tool",
    "load_external_tools",
    "ensure_external_tools_loaded",
    "reload_external_tools",
]
