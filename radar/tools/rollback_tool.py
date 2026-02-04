"""Rollback tool for reverting plugins to previous versions."""

from radar.plugins import get_plugin_loader
from radar.tools import tool


@tool(
    name="rollback_tool",
    description="""Rollback a plugin to a previous version.

Use this to revert a plugin to an earlier working state if a recent change broke it.
Call without version to list available versions.
Call with version to rollback to that specific version.""",
    parameters={
        "tool_name": {
            "type": "string",
            "description": "Name of the tool to rollback",
        },
        "version": {
            "type": "string",
            "description": "Version to rollback to (e.g., 'v1', 'v2'). Omit to list versions.",
            "optional": True,
        },
    },
)
def rollback_tool(tool_name: str, version: str = None) -> str:
    """Rollback a plugin to a previous version."""
    loader = get_plugin_loader()

    if version is None:
        # List available versions
        versions = loader.version_manager.get_versions(tool_name)

        if not versions:
            return f"No versions found for tool '{tool_name}'"

        result = f"=== Versions for '{tool_name}' ===\n\n"
        for v in versions:
            result += f"  {v['version']}"
            if v.get("created_at"):
                result += f" - {v['created_at']}"
            result += "\n"

        result += f"\nTo rollback, call: rollback_tool(tool_name='{tool_name}', version='vN')"
        return result

    # Perform rollback
    success, message = loader.rollback_plugin(tool_name, version)

    if success:
        return f"Successfully rolled back '{tool_name}' to {version}"
    else:
        return f"Rollback failed: {message}"
