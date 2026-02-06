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
    ToolsConfig,
    WebConfig,
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
    "WebSearchConfig",
    # Loader
    "load_config",
    "get_config_path",
    "_apply_env_overrides",
    # Singleton
    "get_config",
    "reload_config",
]


# Global config instance — must live here (not in loader.py) so that
# tests doing `radar.config._config = None` and `patch("radar.config.get_config")`
# target the correct module object.
_config: Config | None = None


def get_config() -> Config:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reload_config() -> Config:
    """Reload configuration from file."""
    global _config
    _config = load_config()
    return _config
