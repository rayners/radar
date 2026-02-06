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


def get_tools_schema() -> list[dict]:
    """Return list of tool definitions for the API."""
    ensure_external_tools_loaded()
    return [schema for _, schema in _registry.values()]


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
    """
    if name not in _registry:
        _log_tool_execution(name, False, "Unknown tool")
        return f"Error: Unknown tool '{name}'"

    func, _ = _registry[name]
    try:
        result = func(**arguments)
        _log_tool_execution(name, True)
        return str(result)
    except Exception as e:
        _log_tool_execution(name, False, str(e))
        return f"Error executing {name}: {e}"


def get_tool_names() -> list[str]:
    """Get list of registered tool names."""
    return list(_registry.keys())


def register_dynamic_tool(
    name: str,
    description: str,
    parameters: dict[str, Any],
    code: str,
) -> bool:
    """Register a dynamically loaded tool.

    Args:
        name: Tool name for the API
        description: Human-readable description
        parameters: JSON Schema for parameters (properties dict)
        code: Python code containing the tool function

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

    namespace = {"__builtins__": safe_builtins}

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


def load_external_tools(directories: list[str | Path]) -> list[str]:
    """Load tool modules from external directories.

    Args:
        directories: List of directory paths to scan for .py tool files.

    Returns:
        List of module stems that were loaded.
    """
    import importlib.util

    loaded = []
    for dir_path in directories:
        path = Path(dir_path).expanduser()
        if not path.is_dir():
            continue
        for file in sorted(path.glob("*.py")):
            if file.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(
                f"radar_external_tools.{file.stem}", file
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
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


# Auto-discover built-in tool modules at import time
_static_tools = _discover_tools()

__all__ = [
    "tool",
    "get_tools_schema",
    "execute_tool",
    "get_tool_names",
    "register_dynamic_tool",
    "unregister_tool",
    "is_dynamic_tool",
    "load_external_tools",
    "ensure_external_tools_loaded",
]
