"""Execute shell command tool."""

import subprocess

from radar.config import get_config
from radar.security import check_command_security
from radar.tools import tool


@tool(
    name="exec",
    description="Execute a shell command and return its output. Dangerous commands (rm -rf, curl, sudo, etc.) are blocked for security. Use for safe read-only operations like ls, cat, grep, find.",
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
    """Execute a shell command with timeout and security checks."""
    config = get_config()

    # Security check based on config mode
    is_safe, risk_level, reason = check_command_security(command)

    if config.tools.exec_mode == "safe_only":
        # Only allow known safe commands
        if risk_level != "safe":
            return f"Error: Command not in safe list. Only basic read commands (ls, cat, grep, etc.) are allowed in safe_only mode."
    elif config.tools.exec_mode == "block_dangerous":
        # Block known dangerous patterns
        if not is_safe:
            return f"Error: {reason}. This command pattern is blocked for security."
    # else: allow_all - no restrictions

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
