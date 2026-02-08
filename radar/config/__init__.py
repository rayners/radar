"""Configuration management for Radar."""

from .loader import _apply_env_overrides, get_config_path, load_config
from .paths import DataPaths, get_data_paths, reset_data_paths
from .schema import (
    Config,
    EmbeddingConfig,
    HeartbeatConfig,
    LLMConfig,
    NotifyConfig,
    OllamaConfig,
    PersonalityEvolutionConfig,
    PluginsConfig,
    RetryConfig,
    SkillsConfig,
    ToolsConfig,
    WebConfig,
    WebMonitorConfig,
    WebSearchConfig,
)

__all__ = [
    # Paths
    "DataPaths",
    "get_data_paths",
    "reset_data_paths",
    # Schema (dataclasses)
    "Config",
    "LLMConfig",
    "EmbeddingConfig",
    "OllamaConfig",
    "NotifyConfig",
    "ToolsConfig",
    "HeartbeatConfig",
    "WebConfig",
    "PluginsConfig",
    "PersonalityEvolutionConfig",
    "RetryConfig",
    "SkillsConfig",
    "WebMonitorConfig",
    "WebSearchConfig",
    # Loader
    "load_config",
    "get_config_path",
    "_apply_env_overrides",
    # Singleton
    "get_config",
    "reload_config",
    "config_file_changed",
]


# Global config instance — must live here (not in loader.py) so that
# tests doing `radar.config._config = None` and `patch("radar.config.get_config")`
# target the correct module object.
_config: Config | None = None
_config_mtime: float | None = None


def _stamp_config_mtime() -> None:
    """Record the current config file's mtime."""
    global _config_mtime
    path = get_config_path()
    if path is not None:
        try:
            _config_mtime = path.stat().st_mtime
        except OSError:
            pass


def config_file_changed() -> bool:
    """Check if the config file has been modified since last load."""
    global _config_mtime
    path = get_config_path()
    if path is None:
        return False
    try:
        current_mtime = path.stat().st_mtime
    except OSError:
        return False
    if _config_mtime is None:
        _config_mtime = current_mtime
        return False
    return current_mtime != _config_mtime


def get_config() -> Config:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = load_config()
        _stamp_config_mtime()
    return _config


def reload_config() -> Config:
    """Reload configuration from file."""
    global _config
    _config = load_config()
    _stamp_config_mtime()
    return _config
