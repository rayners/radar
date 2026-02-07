"""Plugin system for dynamic tool creation and management."""

from radar.plugins.loader import PluginLoader
from radar.plugins.models import Plugin, PluginManifest, TestCase, ToolDefinition, ToolError
from radar.plugins.runner import TestRunner
from radar.plugins.validator import CodeValidator
from radar.plugins.versions import VersionManager

_loader: PluginLoader | None = None


def get_plugin_loader() -> PluginLoader:
    """Get the global plugin loader instance."""
    global _loader
    if _loader is None:
        _loader = PluginLoader()
    return _loader


__all__ = [
    "Plugin",
    "PluginManifest",
    "TestCase",
    "ToolDefinition",
    "ToolError",
    "CodeValidator",
    "TestRunner",
    "VersionManager",
    "PluginLoader",
    "get_plugin_loader",
]
