"""Read file tool."""

from pathlib import Path

from radar.config import get_config
from radar.tools import tool


@tool(
    name="read_file",
    description="Read the contents of a file. Returns the file content as text.",
    parameters={
        "path": {
            "type": "string",
            "description": "Path to the file to read",
        },
    },
)
def read_file(path: str) -> str:
    """Read file contents with size limit."""
    config = get_config()
    file_path = Path(path).expanduser().resolve()

    if not file_path.exists():
        return f"Error: File not found: {path}"

    if not file_path.is_file():
        return f"Error: Not a file: {path}"

    size = file_path.stat().st_size
    if size > config.tools.max_file_size:
        return f"Error: File too large ({size} bytes). Max size is {config.tools.max_file_size} bytes."

    try:
        content = file_path.read_text()
        return content
    except UnicodeDecodeError:
        return f"Error: File is not valid text: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
