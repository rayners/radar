"""File system watchers using watchdog."""

from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from radar.scheduler import add_event

# Global state
_observers: list[Observer] = []


class RadarEventHandler(FileSystemEventHandler):
    """Handle file system events and queue them for the scheduler."""

    def __init__(self, watch_config: dict[str, Any]):
        """Initialize handler with watch configuration.

        Args:
            watch_config: Dict with path, patterns (optional), description (optional)
        """
        super().__init__()
        self.watch_config = watch_config
        self.patterns = watch_config.get("patterns", ["*"])
        self.description = watch_config.get("description", watch_config.get("path", ""))

    def _matches_pattern(self, path: str) -> bool:
        """Check if path matches any configured pattern."""
        from fnmatch import fnmatch
        name = Path(path).name
        return any(fnmatch(name, pattern) for pattern in self.patterns)

    def _create_event(self, event_type: str, event: FileSystemEvent) -> None:
        """Create and queue an event."""
        if event.is_directory:
            return  # Skip directory events

        if not self._matches_pattern(event.src_path):
            return

        add_event(event_type, {
            "path": event.src_path,
            "description": f"{event_type} in {self.description}: {Path(event.src_path).name}",
        })

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation."""
        self._create_event("file_created", event)

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification."""
        self._create_event("file_modified", event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file deletion."""
        self._create_event("file_deleted", event)

    def on_moved(self, event: FileSystemEvent) -> None:
        """Handle file move/rename."""
        self._create_event("file_moved", event)


def start_watchers(watch_configs: list[dict[str, Any]]) -> None:
    """Start file system watchers.

    Args:
        watch_configs: List of watch configurations, each with:
            - path: Directory path to watch
            - patterns: Optional list of glob patterns (default: ["*"])
            - description: Optional description for events
            - recursive: Optional bool to watch recursively (default: True)
    """
    global _observers

    for config in watch_configs:
        path = Path(config.get("path", "")).expanduser()

        if not path.exists():
            continue  # Skip non-existent paths

        observer = Observer()
        handler = RadarEventHandler(config)
        recursive = config.get("recursive", True)

        observer.schedule(handler, str(path), recursive=recursive)
        observer.start()
        _observers.append(observer)


def stop_watchers() -> None:
    """Stop all file system watchers."""
    global _observers

    for observer in _observers:
        observer.stop()
        observer.join(timeout=2.0)

    _observers.clear()
