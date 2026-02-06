"""Data models for the plugin system."""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable


@dataclass
class PluginManifest:
    """Plugin manifest describing a tool."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = "unknown"
    trust_level: str = "sandbox"  # "sandbox" or "trusted"
    permissions: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "PluginManifest":
        """Create manifest from dictionary."""
        return cls(
            name=data.get("name", "unknown"),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            author=data.get("author", "unknown"),
            trust_level=data.get("trust_level", "sandbox"),
            permissions=data.get("permissions", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
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
    enabled: bool = True
    path: Path | None = None
    test_cases: list[TestCase] = field(default_factory=list)
    errors: list[ToolError] = field(default_factory=list)
