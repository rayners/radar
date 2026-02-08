# Radar

A lightweight, local-first AI assistant with native tool calling.

Inspired by [OpenClaw.ai](https://openclaw.ai), Radar is a personal AI assistant that runs on your own hardware. It focuses on what matters: reliable native tool calling, persistent conversation memory, scheduled automation, and a web dashboard for managing it all.

**Local-first by design.** Your conversations, memories, and data stay on your machine. Supports Ollama (default) and OpenAI-compatible APIs (LiteLLM proxy, OpenAI, etc.). The only network calls are to your LLM endpoint and optional services you configure (ntfy, CalDAV, etc.).

## Features

- **Native tool calling** via Ollama or OpenAI-compatible APIs
- **30+ built-in tools**: file operations, shell commands, web search, calendar, weather, GitHub, notifications, and more
- **Persistent semantic memory** with embeddings (Ollama, OpenAI, or local CPU)
- **Daemon mode** with heartbeat scheduler and quiet hours
- **Web dashboard** (FastAPI + HTMX) with chat, history, config, and management pages
- **Scheduled tasks** via natural language ("remind me every morning at 9am")
- **URL monitors** for periodic web page change detection
- **File watchers** that trigger actions when files appear or change
- **Conversation summaries** with automatic daily/weekly/monthly digests
- **Document indexing** with hybrid search (FTS5 keyword + semantic embeddings)
- **Personality system** with YAML front matter for per-personality model and tool scoping
- **Agent Skills** following the [agentskills.io](https://agentskills.io/) open standard
- **Plugin system** for LLM-generated and human-authored tools with trust levels
- **Hook system** for intercepting tool calls, agent runs, memory operations, and heartbeats
- **Systemd service** for persistent operation across reboots
- **Configurable** via YAML with environment variable overrides

### Available Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents (with size limits and path security) |
| `write_file` | Write content to a file |
| `list_directory` | List files with optional glob pattern filtering |
| `exec` | Run shell commands with timeout and safety checks |
| `pdf_extract` | Extract text from PDF pages |
| `notify` | Send push notifications via ntfy.sh |
| `weather` | Current weather and 3-day forecast via Open-Meteo |
| `github` | Query GitHub PRs, issues, notifications, CI status via `gh` CLI |
| `web_search` | Search the web (DuckDuckGo, Brave, SearXNG) |
| `calendar` | Query calendar events via khal CLI |
| `remember` / `recall` | Persistent semantic memory |
| `schedule_task` | Natural language task scheduling (daily, weekly, interval, one-time) |
| `list_scheduled_tasks` | View all scheduled tasks |
| `cancel_task` | Disable or delete scheduled tasks |
| `monitor_url` | Create periodic URL monitors for change detection |
| `list_url_monitors` | List all URL monitors with status |
| `check_url` | Manual URL check or one-off fetch |
| `remove_monitor` | Pause, resume, or delete URL monitors |
| `summarize_conversations` | Retrieve conversation data for a period |
| `store_conversation_summary` | Save a summary as markdown + semantic memory |
| `search_documents` | Search indexed document collections (hybrid search) |
| `manage_documents` | Create, list, delete, or index document collections |
| `use_skill` | Activate an agent skill by name |
| `load_context` | Load a personality context document on demand |
| `create_tool` | LLM-generated plugin tools |
| `debug_tool` | Debug a failing plugin iteratively |
| `rollback_tool` | Revert a plugin to a previous version |
| `analyze_feedback` | Analyze chat feedback patterns |
| `suggest_personality_update` | Propose personality improvements |

User-local tools and plugins extend this list further.

## Installation

Requires Python 3.11+ and a running [Ollama](https://ollama.ai) instance (or an OpenAI-compatible API).

```bash
# Clone the repository
git clone https://github.com/yourusername/radar.git
cd radar

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install
pip install -e .
```

## Quick Start

```bash
# One-shot question
radar ask "List the files in the current directory"

# Interactive chat
radar chat

# View configuration
radar config

# View conversation history
radar history
```

### Daemon Mode

The daemon runs the heartbeat scheduler and web dashboard together.

```bash
# Start daemon (daemonizes by default)
radar start

# Start in foreground (useful for debugging)
radar start --foreground

# Check status
radar status

# Stop daemon
radar stop

# Trigger manual heartbeat
radar heartbeat
```

### Systemd Service

For persistent operation across reboots:

```bash
radar service install     # Install, enable, and start
radar service status      # Check service status
radar service uninstall   # Stop, disable, and remove
```

### Web Dashboard

When the daemon is running, visit `http://localhost:8420` for the web UI.

Pages: Dashboard, Chat, History, Summaries, Documents, Memory, Personalities, Plugins, Tasks, Config, Logs. Mobile responsive with hamburger menu navigation.

## Configuration

Radar looks for `radar.yaml` in the current directory or `~/.config/radar/radar.yaml`.

```yaml
llm:
  provider: ollama          # or "openai" for OpenAI-compatible APIs
  base_url: "http://localhost:11434"
  model: "qwen3:latest"
  # fallback_model: "qwen3:latest"  # Auto-switch on rate limit (429/503)

embedding:
  provider: ollama          # "ollama", "openai", "local", or "none"
  model: nomic-embed-text

notifications:
  url: "https://ntfy.sh"
  topic: "your-topic-here"

web:
  host: "127.0.0.1"
  port: 8420

heartbeat:
  interval_minutes: 15
  quiet_hours_start: "23:00"
  quiet_hours_end: "07:00"

tools:
  exec_mode: "block_dangerous"  # "safe_only", "block_dangerous", or "allow_all"
  extra_dirs:
    - ~/my-radar-tools

personality: default
max_tool_iterations: 10
```

### Environment Variables

Override config values with environment variables:

- `RADAR_LLM_PROVIDER` - "ollama" or "openai"
- `RADAR_LLM_BASE_URL` - API endpoint URL
- `RADAR_LLM_MODEL` - Model name
- `RADAR_API_KEY` - API key for OpenAI-compatible providers
- `RADAR_PERSONALITY` - Active personality name or path
- `RADAR_DATA_DIR` - Custom data directory (default: `~/.local/share/radar`)

See the [User Guide](docs/user-guide.md) for the full configuration reference.

## Architecture

```
radar/
├── cli.py              # Click-based CLI (ask, chat, config, history, start, stop, etc.)
├── agent.py            # Orchestrates context building + tool call loop
├── llm.py              # LLM client (Ollama native or OpenAI-compatible)
├── memory.py           # JSONL conversation storage (one file per conversation)
├── semantic.py         # Embedding client (Ollama, OpenAI, local, or none)
├── config/             # YAML config with env var overrides
├── plugins/            # Dynamic plugin system (validation, sandbox, versioning)
├── scheduler.py        # APScheduler heartbeat with quiet hours + event queue
├── scheduled_tasks.py  # Scheduled task CRUD (SQLite)
├── url_monitors.py     # URL monitor CRUD, fetching, diffing
├── summaries.py        # Conversation summary I/O and heartbeat integration
├── documents.py        # Document indexing with FTS5 + semantic hybrid search
├── skills.py           # Agent Skills discovery and progressive disclosure
├── hooks.py            # Hook system (9 hook points for tool, agent, memory, heartbeat)
├── hooks_builtin.py    # Config-driven hook builders
├── watchers.py         # File system monitoring with watchdog
├── feedback.py         # User feedback collection + personality suggestions
├── security.py         # Path blocklists and command safety checks
├── web/                # FastAPI + HTMX web dashboard (mobile responsive)
│   └── routes/         # Route modules (dashboard, chat, tasks, memory, etc.)
└── tools/              # Auto-discovered tool modules
    ├── __init__.py     # Tool registry, @tool decorator, auto-discovery
    └── ...             # Just add a .py file -- it's auto-discovered
```

### Tool Registration

Tools are auto-discovered from `radar/tools/`. Just create a file with the `@tool` decorator:

```python
# radar/tools/my_tool.py -- automatically discovered on import
from radar.tools import tool

@tool(
    name="my_tool",
    description="Does something useful",
    parameters={
        "arg": {"type": "string", "description": "An argument"},
    },
)
def my_tool(arg: str) -> str:
    return f"Result: {arg}"
```

User-local tools can also be placed in `~/.local/share/radar/tools/` or directories listed in `tools.extra_dirs` config.

### Personalities

Personality files customize Radar's behavior, model, and available tools. They live in `~/.local/share/radar/personalities/` as markdown files (or directories) with optional YAML front matter.

```bash
radar personality list           # List available personalities
radar personality create hawkeye # Create a new personality
radar personality use hawkeye    # Set active personality
radar ask -P hawkeye "question"  # Per-command override
```

Front matter turns a personality from "just a system prompt" into a full agent profile:

```markdown
---
model: qwen3:latest
tools:
  exclude:
    - exec
---

# Hawkeye

You are Hawkeye Pierce -- brilliant, irreverent, and fundamentally decent.
```

### Key Design Decisions

- **`stream: false` always** -- Ollama's streaming breaks tool calling
- **No frameworks** -- The tool call loop is ~50 lines of code
- **SQLite for everything** -- Simple, reliable, no external dependencies
- **Tools are just functions** -- Decorated Python functions that return strings
- **Wrap CLIs, don't import libraries** -- Prefer wrapping existing CLI tools (e.g., `gh`, `khal`) via subprocess

## Documentation

- [User Guide](docs/user-guide.md) -- Installation, configuration, CLI usage, all features
- [Developer Guide](docs/developer-guide.md) -- Architecture, tutorials, testing patterns
- [Security](docs/security.md) -- Full security assessment
- [Scenarios](docs/scenarios.md) -- Capability inventory and use case analysis
- [Recipes](docs/recipes/) -- Ready-to-use scenario guides (daily briefing, homelab monitor, research monitor)

## Requirements

- Python 3.11+
- Ollama running locally or on a remote host (or an OpenAI-compatible API)
- A model that supports tool calling (recommended: `qwen3:latest`)

## License

MIT
