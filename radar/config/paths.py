"""Data path management for Radar."""

import os
from pathlib import Path


class DataPaths:
    """Centralized data path management.

    All radar data files are stored under a single base directory.
    Priority: RADAR_DATA_DIR env var > config file data_dir > default (~/.local/share/radar)
    """

    _base_dir: Path | None = None

    @property
    def base(self) -> Path:
        """Get the base data directory, creating if needed."""
        if self._base_dir is None:
            self._base_dir = self._resolve_base_dir()
        self._base_dir.mkdir(parents=True, exist_ok=True)
        return self._base_dir

    def _resolve_base_dir(self) -> Path:
        """Resolve the base directory from env var, config, or default."""
        # Priority 1: Environment variable
        if env_dir := os.environ.get("RADAR_DATA_DIR"):
            return Path(env_dir).expanduser()
        # Priority 2/3: Config file value or default (handled by caller)
        # This is the default; config override happens via set_base_dir()
        return Path.home() / ".local" / "share" / "radar"

    def set_base_dir(self, path: str) -> None:
        """Set base directory from config file value."""
        if path:
            self._base_dir = Path(path).expanduser()

    def reset(self) -> None:
        """Reset cached base directory (for testing)."""
        self._base_dir = None

    @property
    def conversations(self) -> Path:
        """Get conversations directory."""
        path = self.base / "conversations"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db(self) -> Path:
        """Get memory database path."""
        return self.base / "memory.db"

    @property
    def personalities(self) -> Path:
        """Get personalities directory."""
        path = self.base / "personalities"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def plugins(self) -> Path:
        """Get plugins directory."""
        path = self.base / "plugins"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def tools(self) -> Path:
        """Get user tools directory."""
        path = self.base / "tools"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def log_file(self) -> Path:
        """Get log file path."""
        return self.base / "radar.log"

    @property
    def pid_file(self) -> Path:
        """Get PID file path."""
        return self.base / "radar.pid"


# Global paths instance
_paths: DataPaths | None = None


def get_data_paths() -> DataPaths:
    """Get the global data paths instance."""
    global _paths
    if _paths is None:
        _paths = DataPaths()
    return _paths


def reset_data_paths() -> None:
    """Reset the global data paths instance (for testing)."""
    global _paths
    if _paths is not None:
        _paths.reset()
    _paths = None
