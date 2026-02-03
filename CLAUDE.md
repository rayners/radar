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
- `radar/scheduler.py` - APScheduler heartbeat with quiet hours + event queue
- `radar/watchers.py` - File system monitoring with watchdog
- `radar/security.py` - Path blocklists and command safety checks
- `radar/web/` - FastAPI + HTMX web dashboard (mobile responsive)

## Code Conventions

- Tools are registered with the `@tool` decorator in `radar/tools/`
- Tools return strings (results displayed to user)
- Config: YAML in `radar.yaml` or `~/.config/radar/radar.yaml`
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
- `RADAR_NTFY_URL`, `RADAR_NTFY_TOPIC` - Notification settings
- `RADAR_WEB_HOST`, `RADAR_WEB_PORT`, `RADAR_WEB_AUTH_TOKEN` - Web server settings

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

Pages: Dashboard, Chat, History, Memory, Tasks, Config, Logs

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
