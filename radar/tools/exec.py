"""Execute shell command tool."""

import subprocess

from radar.config import get_config
from radar.tools import tool


@tool(
    name="exec",
    description="Execute a shell command and return its output. Use with caution.",
    parameters={
        "command": {
            "type": "string",
            "description": "The shell command to execute",
        },
        "cwd": {
            "type": "string",
            "description": "Working directory for the command (optional)",
            "optional": True,
        },
    },
)
def exec_command(command: str, cwd: str | None = None) -> str:
    """Execute a shell command with timeout."""
    config = get_config()

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=config.tools.exec_timeout,
            cwd=cwd,
        )

        output_parts = []
        if result.stdout:
            output_parts.append(f"stdout:\n{result.stdout}")
        if result.stderr:
            output_parts.append(f"stderr:\n{result.stderr}")
        if result.returncode != 0:
            output_parts.append(f"exit code: {result.returncode}")

        return "\n".join(output_parts) if output_parts else "(no output)"

    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after {config.tools.exec_timeout} seconds"
    except FileNotFoundError:
        return f"Error: Working directory not found: {cwd}"
    except Exception as e:
        return f"Error executing command: {e}"
