# Radar

Local-only AI assistant with native Ollama tool calling. Inspired by [OpenClaw.ai](https://openclaw.ai).

**Local-first by design** - all data stays on your machine. Supports Ollama (default) and OpenAI-compatible APIs (LiteLLM proxy, OpenAI, etc.).

Currently at Phase 2 (Daemon + Web Dashboard).

## Development

source .venv/bin/activate   # Always activate before running radar commands

## Quick Reference

```bash
# Install
pip install -e .

# Commands
radar ask "question"     # One-shot question
radar chat               # Interactive chat
radar config             # Show configuration
radar history            # View conversation history

# Daemon mode
radar start              # Start daemon (scheduler + web UI)
radar start -h 0.0.0.0   # Listen on all interfaces (remote access)
radar stop               # Stop daemon
radar status             # Show daemon/scheduler status
radar heartbeat          # Trigger manual heartbeat

# Testing with specific LLM endpoint
RADAR_LLM_BASE_URL="http://host:11434" radar ask "test"

# Using OpenAI-compatible API
RADAR_LLM_PROVIDER=openai RADAR_LLM_BASE_URL=https://api.openai.com/v1 RADAR_API_KEY=sk-... radar ask "test"
```

## Architecture

- `radar/agent.py` - Orchestrates context building + tool call loop
- `radar/llm.py` - LLM client (Ollama native or OpenAI-compatible APIs)
- `radar/memory.py` - JSONL conversation storage (one file per conversation)
- `radar/semantic.py` - Embedding client (Ollama, OpenAI, or local sentence-transformers)
- `radar/config.py` - YAML config with env var overrides
- `radar/tools/` - Tool modules registered via `@tool` decorator
- `radar/plugins.py` - Dynamic plugin system for LLM-generated tools
- `radar/scheduler.py` - APScheduler heartbeat with quiet hours + event queue
- `radar/watchers.py` - File system monitoring with watchdog
- `radar/security.py` - Path blocklists and command safety checks
- `radar/web/` - FastAPI + HTMX web dashboard (mobile responsive)

## Code Conventions

- Tools are registered with the `@tool` decorator in `radar/tools/`
- Tools return strings (results displayed to user)
- Config: Copy `radar.example.yaml` to `radar.yaml` (gitignored) or `~/.config/radar/radar.yaml`
- Environment variables override config (see Configuration section below)

## Key Design Decisions

- **Always `stream: false`** - Ollama streaming breaks tool calling
- **No frameworks** - No LangChain/agent frameworks; tool loop is ~50 lines
- **JSONL conversations** - One file per conversation in `~/.local/share/radar/conversations/`
- **SQLite semantic memory** - Embeddings stored in `~/.local/share/radar/memory.db`
- **Tools are functions** - Decorated Python functions returning strings

## Adding a New Tool

```python
# radar/tools/my_tool.py
from radar.tools import tool

@tool(
    name="my_tool",
    description="What it does",
    parameters={
        "arg": {"type": "string", "description": "Argument description"},
    },
)
def my_tool(arg: str) -> str:
    return f"Result: {arg}"
```

Then import in `radar/tools/__init__.py`.

## Adding New Config Sections

1. Add `@dataclass` class in `radar/config.py`
2. Add field to `Config` class with `field(default_factory=...)`
3. Parse in `Config.from_dict()` - extract data and construct instance
4. Add env var overrides in `_apply_env_overrides()`

## Configuration

### LLM Provider

Supports two providers: `ollama` (default) and `openai` (OpenAI-compatible APIs).

```yaml
# radar.yaml - Local Ollama (default)
llm:
  provider: ollama
  model: qwen3:latest
  base_url: http://localhost:11434

# LiteLLM proxy or OpenAI-compatible API
llm:
  provider: openai
  model: gpt-4o  # Or any model your proxy provides
  base_url: http://litellm.internal:4000  # Or https://api.openai.com/v1
```

API keys should be set via environment variable (not config file):
```bash
export RADAR_API_KEY=your-api-key
```

### Embedding Provider

Supports: `ollama` (default), `openai`, `local` (sentence-transformers), or `none` (disable).

```yaml
# Ollama embeddings (default)
embedding:
  provider: ollama
  model: nomic-embed-text

# OpenAI-compatible embeddings
embedding:
  provider: openai
  model: text-embedding-3-small

# Local embeddings (CPU, no API needed)
embedding:
  provider: local
  model: all-MiniLM-L6-v2  # Requires: pip install sentence-transformers

# Disable semantic memory
embedding:
  provider: none
```

### Environment Variables

LLM settings:
- `RADAR_API_KEY` - API key for OpenAI-compatible providers
- `RADAR_LLM_PROVIDER` - "ollama" or "openai"
- `RADAR_LLM_BASE_URL` - API endpoint URL
- `RADAR_LLM_MODEL` - Model name

Embedding settings:
- `RADAR_EMBEDDING_PROVIDER` - "ollama", "openai", "local", or "none"
- `RADAR_EMBEDDING_MODEL` - Embedding model name
- `RADAR_EMBEDDING_BASE_URL` - Embedding API endpoint (defaults to LLM URL)
- `RADAR_EMBEDDING_API_KEY` - Embedding API key (defaults to LLM key)

Other:
- `RADAR_CONFIG_PATH` - Explicit config file path (overrides default locations)
- `RADAR_NTFY_URL`, `RADAR_NTFY_TOPIC` - Notification settings
- `RADAR_WEB_HOST`, `RADAR_WEB_PORT`, `RADAR_WEB_AUTH_TOKEN` - Web server settings
- `RADAR_PERSONALITY` - Active personality name or path
- `RADAR_DATA_DIR` - Custom data directory (default: `~/.local/share/radar`)

Deprecated (still work, but emit warnings):
- `RADAR_OLLAMA_URL` - Use `RADAR_LLM_BASE_URL` instead
- `RADAR_OLLAMA_MODEL` - Use `RADAR_LLM_MODEL` instead

### Config Examples

**Local Ollama (default):**
```yaml
llm:
  provider: ollama
  model: qwen3:latest
  base_url: http://localhost:11434
embedding:
  provider: ollama
  model: nomic-embed-text
```

**LiteLLM Proxy:**
```yaml
llm:
  provider: openai
  model: gpt-4o
  base_url: http://litellm.internal:4000
embedding:
  provider: none  # If proxy doesn't support embeddings
```
Set: `RADAR_API_KEY=your-proxy-key`

**Direct OpenAI:**
```yaml
llm:
  provider: openai
  model: gpt-4o
  base_url: https://api.openai.com/v1
embedding:
  provider: openai
  model: text-embedding-3-small
```
Set: `RADAR_API_KEY=sk-...`

**OpenAI Chat + Local Embeddings (no Ollama needed):**
```yaml
llm:
  provider: openai
  model: gpt-4o
  base_url: https://api.openai.com/v1
embedding:
  provider: local
  model: all-MiniLM-L6-v2
```
Requires: `pip install radar[local-embeddings]`

### Models Tested

Ollama: `qwen3:latest`, `llama3.2` (note: llama3.2 has inconsistent tool calling)

Default embedding model: `nomic-embed-text`

## Semantic Memory

The `remember` and `recall` tools provide persistent semantic memory:

```bash
# Ensure embedding model is available
ollama pull nomic-embed-text

# In chat, the LLM can use these tools:
# remember - Store facts ("Remember that my favorite color is blue")
# recall - Search memories ("What's my favorite color?")

# Verify storage
sqlite3 ~/.local/share/radar/memory.db "SELECT id, content, created_at FROM memories"
```

Memory is stored with embeddings for semantic search (cosine similarity).

## Weather Tool

Get current weather and forecast using the free Open-Meteo API (no API key required).

```bash
# Ask for weather (will prompt for location if not saved)
radar ask "What's the weather?"

# Provide a location
radar ask "What's the weather in Seattle?"

# After providing a location, it's saved for future use
radar ask "Weather forecast?"  # Uses saved location
```

Features:
- Automatic location geocoding
- Current conditions + 3-day forecast
- Saves location preference in semantic memory
- No API key required

## GitHub Tool

Query GitHub PRs, issues, notifications, and CI status using the `gh` CLI.

**Prerequisites:** Install and authenticate the [GitHub CLI](https://cli.github.com/).

```bash
# List PRs requesting your review or assigned to you
radar ask "Show my open PRs"
radar ask "What PRs need my review?"

# List issues
radar ask "Show issues assigned to me"

# Filter by organization
radar ask "Show PRs in the anthropics org"  # Saves org preference

# Check notifications
radar ask "GitHub notifications"

# Check CI status
radar ask "What's the CI status?"
```

Operations:
- `prs` - List PRs (review-requested, assigned)
- `issues` - List issues (assigned, mentioned)
- `notifications` - Unread GitHub notifications
- `status` - PR status and recent CI runs

Organization preference is saved in semantic memory for future queries.

## Web Search Tool

Search the web for current information. Supports multiple providers.

```bash
# Basic search
radar ask "Search for Python 3.13 release notes"

# Search with time filter
radar ask "Search for AI news from this week"
```

### Providers

| Provider | API Key | Notes |
|----------|---------|-------|
| DuckDuckGo | None | Default, no setup needed |
| Brave Search | Required | 2,000 free/month, most reliable |
| SearXNG | None | Self-hosted option |

### Configuration

```yaml
# DuckDuckGo (default, no config needed)
search:
  provider: duckduckgo

# Brave Search (recommended for reliability)
search:
  provider: brave
# Set: RADAR_BRAVE_API_KEY=your-key

# Self-hosted SearXNG
search:
  provider: searxng
  searxng_url: http://localhost:8080
```

Environment variables:
- `RADAR_SEARCH_PROVIDER` - "duckduckgo", "brave", or "searxng"
- `RADAR_BRAVE_API_KEY` - Brave Search API key
- `RADAR_SEARXNG_URL` - SearXNG instance URL

## Testing Tools

Test tool functions directly (bypasses LLM):
```bash
python -c "from radar.tools.recall import recall; print(recall('query'))"
```

## Daemon Mode

The daemon runs the scheduler and web server together:

```bash
radar start                    # Default: localhost:8420
radar start -h 0.0.0.0 -p 9000 # Custom host/port
radar stop                     # Stop daemon
radar status                   # Check if running
```

PID file: `~/.local/share/radar/radar.pid`

Configuration in `radar.yaml`:
```yaml
web:
  host: "0.0.0.0"    # Listen on all interfaces
  port: 8420

heartbeat:
  interval_minutes: 15
  quiet_hours_start: "23:00"
  quiet_hours_end: "07:00"
```

## Web Dashboard

FastAPI + HTMX dashboard at `http://localhost:8420` when daemon is running.

Pages: Dashboard, Chat, History, Memory, Personalities, Plugins, Tasks, Config, Logs

Mobile responsive with hamburger menu for sidebar navigation.

## File Watchers

Monitor directories and queue events for heartbeat processing:

```yaml
# radar.yaml
watch_paths:
  - path: ~/Downloads
    patterns: ["*.pdf", "*.epub"]
    description: "Downloads"
    action: "Summarize this document and send key points via ntfy"
  - path: ~/Documents/notes
    patterns: ["*.md"]
    recursive: true
    action: "Extract any TODOs and remind me about them"
```

The `action` field tells the agent what to do when files matching the pattern are detected. Events without actions are just reported. Events are collected and processed at each heartbeat interval.

## Personalities

Personality files customize Radar's behavior. Stored as markdown files in `~/.local/share/radar/personalities/`.

### File Structure

```
~/.local/share/radar/personalities/
  default.md           # Default personality (created if missing)
  creative.md          # User-created personalities
  technical.md
```

### Personality File Format

```markdown
# Personality Name

Brief description of this personality style.

## Instructions

You are a helpful assistant with these characteristics:
- Be concise and practical
- Use technical language when appropriate

## Context

Additional context or knowledge to include.

Current time: {current_time}
```

The `{current_time}` placeholder is replaced with the current timestamp.

### Configuration

```yaml
# radar.yaml
personality: default    # Name of personality file (without .md)
# OR
personality: ~/my-custom-personality.md  # Explicit path
```

Environment variable: `RADAR_PERSONALITY=creative`

### CLI Commands

```bash
radar personality list           # List available personalities
radar personality show [name]    # Display a personality
radar personality edit [name]    # Open in $EDITOR
radar personality create <name>  # Create new from template
radar personality use <name>     # Set active personality

# Per-command override
radar ask -P creative "Tell me a joke"
radar chat -P technical
```

### Web UI

Navigate to `/personalities` to manage personalities via the web dashboard.

## Personality Evolution

Radar can evolve its personality based on user feedback. This enables continuous improvement of response quality through a feedback-driven loop.

### How It Works

1. **Collect Feedback**: In the web chat, use the + / - buttons on responses to indicate what worked and what didn't
2. **Analyze Patterns**: The `analyze_feedback` tool examines feedback to identify patterns
3. **Suggest Improvements**: The LLM can use `suggest_personality_update` to propose changes
4. **Review & Apply**: Review pending suggestions at `/personalities/suggestions` and approve or reject

### Tools

- `analyze_feedback` - Analyze recent feedback to identify patterns and suggest improvements
- `suggest_personality_update` - Propose a personality modification (goes to pending review)

### Configuration

```yaml
# radar.yaml
personality_evolution:
  allow_suggestions: true           # Enable LLM personality suggestions
  auto_approve_suggestions: false   # Require human review (safe default)
  min_feedback_for_analysis: 10     # Minimum feedback before analysis
```

### Feedback Flow

```
User gives thumbs up/down on chat message
    |
Stored in feedback table (processed=False)
    |
analyze_feedback tool runs (manual or heartbeat)
    |
LLM identifies patterns in positive/negative feedback
    |
LLM calls suggest_personality_update with improvements
    |
Suggestion stored in personality_suggestions (status=pending)
    |
User reviews at /personalities/suggestions
    |
Approve: Change applied to personality .md file
Reject: Stored with reason
    |
Changes take effect immediately (lazy loading)
```

### Web UI

- **Chat** (`/chat`) - Thumbs up/down buttons on assistant messages
- **Personalities** (`/personalities`) - Link to review suggestions
- **Suggestions** (`/personalities/suggestions`) - Review and approve/reject pending changes

### Database Tables

Feedback and suggestions are stored in `~/.local/share/radar/memory.db`:

```sql
-- User feedback on responses
SELECT * FROM feedback ORDER BY created_at DESC;

-- Pending personality changes
SELECT * FROM personality_suggestions WHERE status = 'pending';
```

## Plugin System (Self-Improvement)

Radar can create new tools dynamically through LLM-generated plugins. This enables self-improvement capabilities where Radar can extend its own functionality.

### Directory Structure

```
~/.local/share/radar/plugins/
  enabled/              # Active plugins (symlinks to available/)
  available/            # Approved plugins ready to use
  pending_review/       # LLM-generated plugins awaiting approval
  failed/               # Rejected plugins
  versions/             # Version history for rollback
  errors/               # Error logs for debugging
```

### Plugin Creation

The LLM can use the `create_tool` meta-tool to generate new tools:

```
"Create a tool that reverses strings"
```

This will:
1. Generate Python code for the tool
2. Validate code for safety (no dangerous imports/operations)
3. Run test cases in a sandbox
4. Save to `pending_review/` for human approval (default) or auto-enable if configured

### Debugging Failed Plugins

Use `debug_tool` to iteratively fix plugins that fail validation or tests:

```
"Debug the reverse_string tool"  # View error details
"Fix the reverse_string tool"    # Apply a fix and re-test
```

The system tracks attempts and stops after max_debug_attempts (default: 5).

### Version Control

Plugins are versioned automatically. Use `rollback_tool` to revert to a previous version:

```
"Show versions of my_tool"
"Rollback my_tool to v1"
```

### Configuration

```yaml
# radar.yaml
plugins:
  allow_llm_generated: true       # Enable LLM tool creation
  auto_approve: false             # Require human review (safe default)
  auto_approve_if_tests_pass: false  # Auto-approve if tests pass (power users)
  max_debug_attempts: 5           # Give up after N fix attempts
  test_timeout_seconds: 10        # Timeout for running tests
  max_code_size_bytes: 10000      # Max code size for generated plugins
```

### Security

- **AST validation** - Blocks dangerous imports (os, subprocess, etc.) and operations (eval, exec, open)
- **Sandboxed execution** - Tests run with restricted builtins
- **Human review** - Default requires manual approval via web UI
- **Version history** - Can rollback to previous working versions

### Web UI

Navigate to `/plugins` to:
- View all installed plugins
- Enable/disable plugins
- Review pending plugins at `/plugins/review`
- View plugin details, code, versions, and errors
- Manually edit plugin code

## Security

See `docs/security.md` for full security assessment.

### Path Blocklist

File tools block access to sensitive paths:
- **Blocked for read/write**: `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config/gcloud`, `~/.password-store`
- **Blocked for write only**: `~/.bashrc`, `~/.zshrc`, `~/.profile`, `~/.config/autostart`

### Exec Safety

The `exec` tool blocks dangerous command patterns by default:
- Destructive: `rm -rf`, `mkfs`, `dd if=`
- Network: `curl`, `wget`, `nc`
- Privilege: `sudo`, `su`, `chmod 777`
- Persistence: `crontab`, `systemctl enable`

Configure in `radar.yaml`:
```yaml
tools:
  exec_mode: "block_dangerous"  # safe_only | block_dangerous | allow_all
```

### Web UI Authentication

Required when binding to non-localhost:

```yaml
web:
  host: "0.0.0.0"
  auth_token: "your-secret-token"  # Required for non-localhost
```

Or via environment: `RADAR_WEB_AUTH_TOKEN=your-token`

Generate a token:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```
