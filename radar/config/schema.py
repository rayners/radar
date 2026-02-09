"""Configuration dataclasses for Radar."""

import dataclasses
import warnings
from dataclasses import dataclass, field
from typing import Any


def _dc_from_dict(cls, data: dict[str, Any]):
    """Construct a dataclass from a dict, using class defaults for missing keys."""
    return cls(**{
        f.name: data.get(f.name, f.default if f.default is not dataclasses.MISSING else f.default_factory())
        for f in dataclasses.fields(cls)
    })


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

    # Fallback model for rate limit errors (empty = disabled)
    # When the primary model returns 429/503, automatically retry with this model
    fallback_model: str = ""


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
    # Extra directories to scan for user-local tool files
    extra_dirs: list[str] = field(default_factory=list)


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
class HooksConfig:
    """Hook system configuration."""

    enabled: bool = True
    rules: list[dict] = field(default_factory=list)


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
class WebMonitorConfig:
    """URL monitor configuration."""

    default_interval_minutes: int = 60
    min_interval_minutes: int = 5
    fetch_timeout: int = 30
    user_agent: str = "Radar/1.0 (Web Monitor)"
    max_content_size: int = 1048576  # 1MB
    max_diff_length: int = 2000
    max_error_count: int = 5


@dataclass
class SummariesConfig:
    """Conversation summary configuration."""

    enabled: bool = True
    daily_summary_time: str = "21:00"
    weekly_summary_day: str = "sun"
    monthly_summary_day: int = 1
    auto_notify: bool = False
    max_conversations_per_summary: int = 50


@dataclass
class DocumentsConfig:
    """Document indexing configuration."""

    enabled: bool = True
    chunk_size: int = 800
    chunk_overlap_pct: float = 0.1
    generate_embeddings: bool = True
    collections: list[dict] = field(default_factory=list)


@dataclass
class RetryConfig:
    """Retry with exponential backoff configuration."""

    max_retries: int = 3  # 0 = disable retries
    base_delay: float = 1.0  # seconds
    max_delay: float = 30.0  # seconds cap
    llm_retries: bool = True
    embedding_retries: bool = True
    url_monitor_retries: bool = True


@dataclass
class SkillsConfig:
    """Agent Skills configuration."""

    enabled: bool = True
    dirs: list[str] = field(default_factory=list)  # Extra skill directories


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
    hooks: HooksConfig = field(default_factory=HooksConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    web_monitor: WebMonitorConfig = field(default_factory=WebMonitorConfig)
    summaries: SummariesConfig = field(default_factory=SummariesConfig)
    documents: DocumentsConfig = field(default_factory=DocumentsConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
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

        # Build section overrides for fields with non-matching config keys
        section_data = {
            "llm": llm_data,
            "embedding": embedding_data,
            "notifications": data.get("notifications", {}),
            "ollama": ollama_data,
        }

        # Build all dataclass-typed fields generically
        kwargs: dict[str, Any] = {}
        for f in dataclasses.fields(cls):
            if dataclasses.is_dataclass(f.type if isinstance(f.type, type) else None):
                dc_cls = f.type
                dc_data = section_data.get(f.name) if f.name in section_data else data.get(f.name, {})
                kwargs[f.name] = _dc_from_dict(dc_cls, dc_data)
            else:
                # Scalar fields (system_prompt, max_tool_iterations, etc.)
                default = f.default if f.default is not dataclasses.MISSING else f.default_factory()
                kwargs[f.name] = data.get(f.name, default)

        return cls(**kwargs)
