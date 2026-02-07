"""Data models for the plugin system."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass
class ToolDefinition:
    """A tool definition within a multi-tool plugin."""

    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "ToolDefinition":
        """Create tool definition from dictionary."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            parameters=data.get("parameters", {}),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


@dataclass
class PluginManifest:
    """Plugin manifest describing a tool."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "unknown"
    trust_level: str = "sandbox"  # "sandbox" or "local"
    permissions: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    capabilities: list[str] = field(default_factory=lambda: ["tool"])
    widget: dict | None = None  # {title, template, position, refresh_interval}
    personalities: list[str] = field(default_factory=list)  # filenames
    scripts: list[str] = field(default_factory=list)  # filenames
    tools: list[ToolDefinition] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        """Create manifest from dictionary."""
        tools_data = data.get("tools", [])
        tools = [ToolDefinition.from_dict(t) for t in tools_data]
        return cls(
            name=data.get("name", "unknown"),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", "unknown"),
            trust_level=data.get("trust_level", "sandbox"),
            permissions=data.get("permissions", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            capabilities=data.get("capabilities", ["tool"]),
            widget=data.get("widget"),
            personalities=data.get("personalities", []),
            scripts=data.get("scripts", []),
            tools=tools,
        )

    def to_dict(self) -> dict:
        """Convert manifest to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "trust_level": self.trust_level,
            "permissions": self.permissions,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "capabilities": self.capabilities,
            "widget": self.widget,
            "personalities": self.personalities,
            "scripts": self.scripts,
            "tools": [t.to_dict() for t in self.tools],
        }


@dataclass
class TestCase:
    """A test case for a plugin."""

    name: str
    input_args: dict
    expected_output: str | None = None  # None means just check no exception
    expected_contains: str | None = None  # Output should contain this

    @classmethod
    def from_dict(cls, data: dict) -> "TestCase":
        """Create test case from dictionary."""
        return cls(
            name=data.get("name", "test"),
            input_args=data.get("input_args", data.get("input", {})),
            expected_output=data.get("expected_output", data.get("expected")),
            expected_contains=data.get("expected_contains"),
        )


@dataclass
class ToolError:
    """Error information for debugging failed tools."""

    tool_name: str
    error_type: str  # "syntax", "runtime", "test_failure", "validation"
    message: str
    traceback_str: str
    input_args: dict
    expected_output: str | None
    actual_output: str | None
    attempt_number: int
    max_attempts: int = 5
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "tool_name": self.tool_name,
            "error_type": self.error_type,
            "message": self.message,
            "traceback": self.traceback_str,
            "input_args": self.input_args,
            "expected_output": self.expected_output,
            "actual_output": self.actual_output,
            "attempt_number": self.attempt_number,
            "max_attempts": self.max_attempts,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ToolError":
        """Create from dictionary."""
        return cls(
            tool_name=data["tool_name"],
            error_type=data["error_type"],
            message=data["message"],
            traceback_str=data.get("traceback", ""),
            input_args=data.get("input_args", {}),
            expected_output=data.get("expected_output"),
            actual_output=data.get("actual_output"),
            attempt_number=data.get("attempt_number", 1),
            max_attempts=data.get("max_attempts", 5),
            timestamp=data.get("timestamp", ""),
        )


@dataclass
class Plugin:
    """A loaded plugin."""

    name: str
    manifest: PluginManifest
    code: str
    function: Callable | None = None
    functions: dict[str, Callable] = field(default_factory=dict)
    enabled: bool = True
    path: Path | None = None
    test_cases: list[TestCase] = field(default_factory=list)
    errors: list[ToolError] = field(default_factory=list)
