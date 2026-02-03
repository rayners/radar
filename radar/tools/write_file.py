"""Write file tool."""

from pathlib import Path

from radar.security import check_path_security
from radar.tools import tool


@tool(
    name="write_file",
    description="Write content to a file. Creates the file if it doesn't exist, overwrites if it does. Some sensitive paths (like ~/.ssh, ~/.bashrc) are blocked for security.",
    parameters={
        "path": {
            "type": "string",
            "description": "Path to the file to write",
        },
        "content": {
            "type": "string",
            "description": "Content to write to the file",
        },
    },
)
def write_file(path: str, content: str) -> str:
    """Write content to a file with security checks."""
    # Security check
    is_safe, reason = check_path_security(path, "write")
    if not is_safe:
        return f"Error: {reason}"

    file_path = Path(path).expanduser().resolve()

    try:
        # Create parent directories if needed
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content)
        return f"Successfully wrote {len(content)} bytes to {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except OSError as e:
        return f"Error writing file: {e}"
