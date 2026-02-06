# Radar

A lightweight, local-only AI assistant with native Ollama tool calling.

Inspired by [OpenClaw.ai](https://openclaw.ai), Radar is a personal AI assistant that runs entirely on your own hardware, backed by Ollama. It focuses on what matters: reliable native tool calling, persistent conversation memory, and practical automation tasks.

**Local-only by design.** Your conversations, memories, and data never leave your machine. No cloud APIs, no telemetry, no external dependencies beyond Ollama itself. The only network calls are to your own Ollama instance (local or on your LAN) and optional self-hosted services you configure (ntfy, CalDAV, etc.).

## Features

- **Native tool calling** via Ollama's OpenAI-compatible API
- **Built-in tools**: file operations, shell commands, PDF extraction, notifications
- **Conversation memory** with SQLite storage
- **Interactive chat** and one-shot question modes
- **Configurable** via YAML with environment variable overrides

### Available Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents (with size limits) |
| `write_file` | Write content to a file |
| `list_directory` | List files with optional glob pattern filtering |
| `exec` | Run shell commands with timeout |
| `pdf_extract` | Extract text from PDF pages |
| `notify` | Send push notifications via ntfy.sh |
| `weather` | Current weather and forecast via Open-Meteo |
| `github` | Query GitHub PRs, issues, notifications via `gh` CLI |
| `web_search` | Search the web (DuckDuckGo, Brave, SearXNG) |
| `remember` / `recall` | Persistent semantic memory |
| `schedule_task` | Natural language task scheduling |
| `create_tool` | LLM-generated plugin tools |

## Installation

Requires Python 3.11+ and a running [Ollama](https://ollama.ai) instance.

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

## Configuration

Radar looks for `radar.yaml` in the current directory or `~/.config/radar/radar.yaml`.

```yaml
llm:
  provider: ollama          # or "openai" for OpenAI-compatible APIs
  base_url: "http://localhost:11434"
  model: "qwen3:latest"

notifications:
  url: "https://ntfy.sh"
  topic: "your-topic-here"

tools:
  max_file_size: 102400  # bytes
  exec_timeout: 30       # seconds
  extra_dirs:             # Additional directories for user-local tools
    - ~/my-radar-tools

max_tool_iterations: 10
```

### Environment Variables

Override config values with environment variables:

- `RADAR_LLM_PROVIDER` - "ollama" or "openai"
- `RADAR_LLM_BASE_URL` - API endpoint URL
- `RADAR_LLM_MODEL` - Model name
- `RADAR_API_KEY` - API key for OpenAI-compatible providers
- `RADAR_NTFY_URL` - ntfy server URL
- `RADAR_NTFY_TOPIC` - ntfy topic

See `CLAUDE.md` for full configuration reference.

## Architecture

```
radar/
├── cli.py          # Click-based CLI (ask, chat, config, history)
├── agent.py        # Orchestrates context building + LLM interaction
├── llm.py          # LLM client (Ollama native or OpenAI-compatible)
├── memory.py       # JSONL conversation storage
├── semantic.py     # Embedding client for semantic memory
├── config.py       # YAML config loader with env overrides
├── plugins.py      # Dynamic plugin system for LLM-generated tools
├── scheduler.py    # APScheduler heartbeat with quiet hours
├── security.py     # Path blocklists and command safety checks
├── web/            # FastAPI + HTMX web dashboard
└── tools/          # Auto-discovered tool modules
    ├── __init__.py     # Tool registry, @tool decorator, auto-discovery
    ├── weather.py
    ├── github.py
    └── ...             # Just add a .py file — it's auto-discovered
```

### Tool Registration

Tools are auto-discovered from `radar/tools/`. Just create a file with the `@tool` decorator:

```python
# radar/tools/my_tool.py — automatically discovered on import
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

### Key Design Decisions

- **`stream: false` always** - Ollama's streaming breaks tool calling
- **No frameworks** - The tool call loop is ~50 lines of code
- **SQLite for everything** - Simple, reliable, no external dependencies
- **Tools are just functions** - Decorated Python functions that return strings

## Requirements

- Python 3.11+
- Ollama running locally or on a remote host
- A model that supports tool calling (e.g., qwen3:latest, llama3.1:8b)

## License

MIT
