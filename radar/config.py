"""Configuration management for Radar."""

import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ===== Data Paths =====


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


# ===== Config Dataclasses =====


@dataclass
class LLMConfig:
    """LLM provider configuration."""

    # Provider: "ollama" or "openai" (OpenAI-compatible API)
    provider: str = "ollama"

    # Model name
    # Ollama: "qwen3:latest", "llama3.2"
    # OpenAI: "gpt-4o", "claude-3-5-sonnet" (via LiteLLM proxy)
    model: str = "qwen3:latest"

    # Base URL for API
    # Ollama: "http://localhost:11434"
    # OpenAI/LiteLLM proxy: "http://litellm.internal:4000" or "https://api.openai.com/v1"
    base_url: str = "http://localhost:11434"

    # API key (use env var RADAR_API_KEY, not config file)
    api_key: str = ""


@dataclass
class EmbeddingConfig:
    """Embedding provider configuration."""

    # Provider: "ollama", "openai", "local", or "none"
    # - ollama: Use Ollama's /api/embed endpoint
    # - openai: Use OpenAI-compatible embedding API
    # - local: Use sentence-transformers locally
    # - none: Disable semantic memory features
    provider: str = "ollama"

    # Model name
    # Ollama: "nomic-embed-text"
    # OpenAI: "text-embedding-3-small"
    # Local: "all-MiniLM-L6-v2"
    model: str = "nomic-embed-text"

    # Base URL (defaults to LLM base_url if not set)
    base_url: str = ""

    # API key (defaults to LLM api_key if not set)
    api_key: str = ""


@dataclass
class OllamaConfig:
    """Ollama API configuration (deprecated, use LLMConfig)."""

    base_url: str = "http://localhost:11434"
    model: str = "qwen3:latest"


@dataclass
class NotifyConfig:
    """Notification (ntfy) configuration."""

    url: str = "https://ntfy.sh"
    topic: str = ""


@dataclass
class ToolsConfig:
    """Tools configuration."""

    max_file_size: int = 102400  # 100KB
    exec_timeout: int = 30
    # Exec security mode: "safe_only", "block_dangerous", "allow_all"
    # - safe_only: Only allow known safe commands (ls, cat, etc.)
    # - block_dangerous: Block known dangerous patterns, allow others (default)
    # - allow_all: No restrictions (dangerous!)
    exec_mode: str = "block_dangerous"


@dataclass
class HeartbeatConfig:
    """Heartbeat/scheduler configuration."""

    interval_minutes: int = 15
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"


@dataclass
class WebConfig:
    """Web server configuration."""

    host: str = "127.0.0.1"
    port: int = 8420
    # Auth token required when binding to non-localhost
    # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    auth_token: str = ""


@dataclass
class PluginsConfig:
    """Plugin system configuration."""

    # Maximum debug/fix attempts before giving up
    max_debug_attempts: int = 5
    # Timeout for running plugin tests
    test_timeout_seconds: int = 10
    # Maximum code size for generated plugins
    max_code_size_bytes: int = 10000
    # Allow LLM to generate new tools
    allow_llm_generated: bool = True
    # Auto-approve all plugins (dangerous - default False)
    auto_approve: bool = False
    # Auto-approve if all tests pass (opt-in for power users)
    auto_approve_if_tests_pass: bool = False


@dataclass
class PersonalityEvolutionConfig:
    """Personality evolution/feedback configuration."""

    # Allow LLM to suggest personality changes
    allow_suggestions: bool = True
    # Auto-approve personality suggestions (default False for safety)
    auto_approve_suggestions: bool = False
    # Minimum feedback entries required before analysis
    min_feedback_for_analysis: int = 10


@dataclass
class WebSearchConfig:
    """Web search configuration."""

    # Provider: "duckduckgo" (default), "brave", or "searxng"
    provider: str = "duckduckgo"
    # Brave Search API key (use RADAR_BRAVE_API_KEY env var)
    brave_api_key: str = ""
    # SearXNG instance URL (use RADAR_SEARXNG_URL env var)
    searxng_url: str = ""
    # Maximum results to return
    max_results: int = 10
    # Safe search level (not used by all providers)
    safe_search: str = "moderate"


@dataclass
class Config:
    """Main configuration container."""

    llm: LLMConfig = field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    notifications: NotifyConfig = field(default_factory=NotifyConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    web: WebConfig = field(default_factory=WebConfig)
    plugins: PluginsConfig = field(default_factory=PluginsConfig)
    personality_evolution: PersonalityEvolutionConfig = field(default_factory=PersonalityEvolutionConfig)
    search: WebSearchConfig = field(default_factory=WebSearchConfig)
    system_prompt: str = ""
    max_tool_iterations: int = 10
    watch_paths: list[dict] = field(default_factory=list)
    personality: str = "default"  # Personality file name or path
    data_dir: str = ""  # Custom data directory path (prefer RADAR_DATA_DIR env var)

    # Deprecated: Use llm.base_url, llm.model instead
    # Kept for backward compatibility
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    embedding_model: str = "nomic-embed-text"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        """Create Config from dictionary."""
        llm_data = data.get("llm", {})
        embedding_data = data.get("embedding", {})
        ollama_data = data.get("ollama", {})
        notify_data = data.get("notifications", {})
        tools_data = data.get("tools", {})
        heartbeat_data = data.get("heartbeat", {})
        web_data = data.get("web", {})
        plugins_data = data.get("plugins", {})
        personality_evolution_data = data.get("personality_evolution", {})
        search_data = data.get("search", {})

        # Backward compatibility: if 'ollama' section exists but not 'llm', migrate
        if ollama_data and not llm_data:
            warnings.warn(
                "Config 'ollama' section is deprecated. Use 'llm' with provider='ollama' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            llm_data = {
                "provider": "ollama",
                "base_url": ollama_data.get("base_url", LLMConfig.base_url),
                "model": ollama_data.get("model", LLMConfig.model),
            }

        # Backward compatibility: if 'embedding_model' exists but not 'embedding', migrate
        old_embedding_model = data.get("embedding_model")
        if old_embedding_model and not embedding_data:
            warnings.warn(
                "Config 'embedding_model' is deprecated. Use 'embedding.model' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            embedding_data = {"model": old_embedding_model}

        # Security warning: API key in config file
        if llm_data.get("api_key") or embedding_data.get("api_key"):
            warnings.warn(
                "API key found in config file. For security, use RADAR_API_KEY "
                "environment variable instead to avoid committing secrets.",
                UserWarning,
                stacklevel=2,
            )

        return cls(
            llm=LLMConfig(
                provider=llm_data.get("provider", LLMConfig.provider),
                model=llm_data.get("model", LLMConfig.model),
                base_url=llm_data.get("base_url", LLMConfig.base_url),
                api_key=llm_data.get("api_key", LLMConfig.api_key),
            ),
            embedding=EmbeddingConfig(
                provider=embedding_data.get("provider", EmbeddingConfig.provider),
                model=embedding_data.get("model", EmbeddingConfig.model),
                base_url=embedding_data.get("base_url", EmbeddingConfig.base_url),
                api_key=embedding_data.get("api_key", EmbeddingConfig.api_key),
            ),
            notifications=NotifyConfig(
                url=notify_data.get("url", NotifyConfig.url),
                topic=notify_data.get("topic", NotifyConfig.topic),
            ),
            tools=ToolsConfig(
                max_file_size=tools_data.get("max_file_size", ToolsConfig.max_file_size),
                exec_timeout=tools_data.get("exec_timeout", ToolsConfig.exec_timeout),
                exec_mode=tools_data.get("exec_mode", ToolsConfig.exec_mode),
            ),
            heartbeat=HeartbeatConfig(
                interval_minutes=heartbeat_data.get("interval_minutes", HeartbeatConfig.interval_minutes),
                quiet_hours_start=heartbeat_data.get("quiet_hours_start", HeartbeatConfig.quiet_hours_start),
                quiet_hours_end=heartbeat_data.get("quiet_hours_end", HeartbeatConfig.quiet_hours_end),
            ),
            web=WebConfig(
                host=web_data.get("host", WebConfig.host),
                port=web_data.get("port", WebConfig.port),
                auth_token=web_data.get("auth_token", WebConfig.auth_token),
            ),
            plugins=PluginsConfig(
                max_debug_attempts=plugins_data.get("max_debug_attempts", PluginsConfig.max_debug_attempts),
                test_timeout_seconds=plugins_data.get("test_timeout_seconds", PluginsConfig.test_timeout_seconds),
                max_code_size_bytes=plugins_data.get("max_code_size_bytes", PluginsConfig.max_code_size_bytes),
                allow_llm_generated=plugins_data.get("allow_llm_generated", PluginsConfig.allow_llm_generated),
                auto_approve=plugins_data.get("auto_approve", PluginsConfig.auto_approve),
                auto_approve_if_tests_pass=plugins_data.get("auto_approve_if_tests_pass", PluginsConfig.auto_approve_if_tests_pass),
            ),
            personality_evolution=PersonalityEvolutionConfig(
                allow_suggestions=personality_evolution_data.get("allow_suggestions", PersonalityEvolutionConfig.allow_suggestions),
                auto_approve_suggestions=personality_evolution_data.get("auto_approve_suggestions", PersonalityEvolutionConfig.auto_approve_suggestions),
                min_feedback_for_analysis=personality_evolution_data.get("min_feedback_for_analysis", PersonalityEvolutionConfig.min_feedback_for_analysis),
            ),
            search=WebSearchConfig(
                provider=search_data.get("provider", WebSearchConfig.provider),
                brave_api_key=search_data.get("brave_api_key", WebSearchConfig.brave_api_key),
                searxng_url=search_data.get("searxng_url", WebSearchConfig.searxng_url),
                max_results=search_data.get("max_results", WebSearchConfig.max_results),
                safe_search=search_data.get("safe_search", WebSearchConfig.safe_search),
            ),
            system_prompt=data.get("system_prompt", ""),
            max_tool_iterations=data.get("max_tool_iterations", 10),
            watch_paths=data.get("watch_paths", []),
            personality=data.get("personality", "default"),
            data_dir=data.get("data_dir", ""),
            # Keep deprecated fields for backward compatibility
            ollama=OllamaConfig(
                base_url=ollama_data.get("base_url", OllamaConfig.base_url),
                model=ollama_data.get("model", OllamaConfig.model),
            ),
            embedding_model=data.get("embedding_model", "nomic-embed-text"),
        )


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


# Global config instance
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
