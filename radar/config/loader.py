"""Configuration loading and environment overrides for Radar."""

import os
import warnings
from pathlib import Path

import yaml

from .paths import get_data_paths
from .schema import Config


def _apply_env_overrides(config: Config) -> Config:
    """Apply environment variable overrides."""
    # New LLM config env vars
    if api_key := os.environ.get("RADAR_API_KEY"):
        config.llm.api_key = api_key
    if llm_provider := os.environ.get("RADAR_LLM_PROVIDER"):
        config.llm.provider = llm_provider
    if base_url := os.environ.get("RADAR_LLM_BASE_URL"):
        config.llm.base_url = base_url
    if model := os.environ.get("RADAR_LLM_MODEL"):
        config.llm.model = model
    if fallback_model := os.environ.get("RADAR_LLM_FALLBACK_MODEL"):
        config.llm.fallback_model = fallback_model

    # New embedding config env vars
    if emb_provider := os.environ.get("RADAR_EMBEDDING_PROVIDER"):
        config.embedding.provider = emb_provider
    if emb_model := os.environ.get("RADAR_EMBEDDING_MODEL"):
        config.embedding.model = emb_model
    if emb_base_url := os.environ.get("RADAR_EMBEDDING_BASE_URL"):
        config.embedding.base_url = emb_base_url
    if emb_api_key := os.environ.get("RADAR_EMBEDDING_API_KEY"):
        config.embedding.api_key = emb_api_key

    # Backward compatibility: old Ollama env vars (deprecated)
    if url := os.environ.get("RADAR_OLLAMA_URL"):
        warnings.warn(
            "RADAR_OLLAMA_URL is deprecated. Use RADAR_LLM_BASE_URL instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        config.llm.base_url = url
        config.ollama.base_url = url
    if ollama_model := os.environ.get("RADAR_OLLAMA_MODEL"):
        warnings.warn(
            "RADAR_OLLAMA_MODEL is deprecated. Use RADAR_LLM_MODEL instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        config.llm.model = ollama_model
        config.ollama.model = ollama_model

    # Notification env vars
    if ntfy_url := os.environ.get("RADAR_NTFY_URL"):
        config.notifications.url = ntfy_url
    if ntfy_topic := os.environ.get("RADAR_NTFY_TOPIC"):
        config.notifications.topic = ntfy_topic

    # Web server env vars
    if web_host := os.environ.get("RADAR_WEB_HOST"):
        config.web.host = web_host
    if web_port := os.environ.get("RADAR_WEB_PORT"):
        config.web.port = int(web_port)
    if web_auth := os.environ.get("RADAR_WEB_AUTH_TOKEN"):
        config.web.auth_token = web_auth

    # Personality
    if personality := os.environ.get("RADAR_PERSONALITY"):
        config.personality = personality

    # Data directory (env var takes precedence - handled in DataPaths)
    # We still store in config for introspection, but DataPaths._resolve_base_dir()
    # checks the env var first
    if data_dir := os.environ.get("RADAR_DATA_DIR"):
        config.data_dir = data_dir

    # Web search env vars
    if search_provider := os.environ.get("RADAR_SEARCH_PROVIDER"):
        config.search.provider = search_provider
    if brave_api_key := os.environ.get("RADAR_BRAVE_API_KEY"):
        config.search.brave_api_key = brave_api_key
    if searxng_url := os.environ.get("RADAR_SEARXNG_URL"):
        config.search.searxng_url = searxng_url

    return config


def get_config_path() -> Path | None:
    """Get the path to the config file if it exists.

    Priority:
    1. RADAR_CONFIG_PATH env var (explicit override)
    2. ./radar.yaml (current directory)
    3. ~/.config/radar/radar.yaml (user config)
    """
    # Priority 1: Explicit env var
    if env_path := os.environ.get("RADAR_CONFIG_PATH"):
        path = Path(env_path).expanduser()
        if path.exists():
            return path
        # Warn if specified but doesn't exist
        warnings.warn(f"RADAR_CONFIG_PATH={env_path} does not exist", UserWarning)
        return None

    # Priority 2/3: Standard locations
    config_paths = [
        Path.cwd() / "radar.yaml",
        Path.home() / ".config" / "radar" / "radar.yaml",
    ]
    for path in config_paths:
        if path.exists():
            return path
    return None


def load_config() -> Config:
    """Load configuration from file with fallbacks."""
    config_path = get_config_path()

    if config_path:
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        config = Config.from_dict(data)
        config = _apply_env_overrides(config)
    else:
        # Return defaults if no config file found
        config = _apply_env_overrides(Config())

    # Initialize data paths with config file value (env var takes precedence in DataPaths)
    paths = get_data_paths()
    if config.data_dir and not os.environ.get("RADAR_DATA_DIR"):
        # Only use config file value if env var is not set
        paths.set_base_dir(config.data_dir)

    return config
