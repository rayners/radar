"""List directory tool."""

import fnmatch
from pathlib import Path

from radar.tools import tool


@tool(
    name="list_directory",
    description="List files and directories in a given path. Optionally filter by pattern.",
    parameters={
        "path": {
            "type": "string",
            "description": "Path to the directory to list",
        },
        "pattern": {
            "type": "string",
            "description": "Optional glob pattern to filter results (e.g., '*.py')",
            "optional": True,
        },
    },
)
def list_directory(path: str, pattern: str | None = None) -> str:
    """List directory contents with optional pattern filtering."""
    dir_path = Path(path).expanduser().resolve()

    if not dir_path.exists():
        return f"Error: Directory not found: {path}"

    if not dir_path.is_dir():
        return f"Error: Not a directory: {path}"

    try:
        entries = list(dir_path.iterdir())
    except PermissionError:
        return f"Error: Permission denied: {path}"

    # Sort: directories first, then files, alphabetically
    all_dirs = sorted([e for e in entries if e.is_dir()], key=lambda x: x.name.lower())
    all_files = sorted([e for e in entries if e.is_file()], key=lambda x: x.name.lower())

    # Filter by pattern if provided
    if pattern:
        dirs = [d for d in all_dirs if fnmatch.fnmatch(d.name, pattern)]
        files = [f for f in all_files if fnmatch.fnmatch(f.name, pattern)]
    else:
        dirs = all_dirs
        files = all_files

    result_lines = []
    for d in dirs:
        result_lines.append(f"[DIR]  {d.name}/")
    for f in files:
        size = f.stat().st_size
        result_lines.append(f"[FILE] {f.name} ({size} bytes)")

    if not result_lines:
        if pattern:
            # Show what IS in the directory so LLM can navigate
            hint_dirs = [d.name for d in all_dirs[:5]]
            hint = f" Subdirectories: {', '.join(hint_dirs)}" if hint_dirs else " No subdirectories."
            return f"No files matching '{pattern}' in {path}.{hint}"
        return "Directory is empty"

    return "\n".join(result_lines)
