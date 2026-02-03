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
ollama:
  base_url: "http://localhost:11434"
  model: "llama3.2"

notifications:
  url: "https://ntfy.sh"
  topic: "your-topic-here"

tools:
  max_file_size: 102400  # bytes
  exec_timeout: 30       # seconds

max_tool_iterations: 10
```

### Environment Variables

Override config values with environment variables:

- `RADAR_OLLAMA_URL` - Ollama API base URL
- `RADAR_OLLAMA_MODEL` - Model name
- `RADAR_NTFY_URL` - ntfy server URL
- `RADAR_NTFY_TOPIC` - ntfy topic

## Architecture

```
radar/
├── cli.py          # Click-based CLI (ask, chat, config, history)
├── agent.py        # Orchestrates context building + LLM interaction
├── llm.py          # Ollama client with tool call loop
├── memory.py       # SQLite conversation storage
├── config.py       # YAML config loader with env overrides
└── tools/
    ├── __init__.py     # Tool registry + @tool decorator
    ├── read_file.py
    ├── write_file.py
    ├── list_directory.py
    ├── exec.py
    ├── notify.py
    └── pdf_extract.py
```

### Tool Registration

Tools are registered via decorator:

```python
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

### Key Design Decisions

- **`stream: false` always** - Ollama's streaming breaks tool calling
- **No frameworks** - The tool call loop is ~50 lines of code
- **SQLite for everything** - Simple, reliable, no external dependencies
- **Tools are just functions** - Decorated Python functions that return strings

## Requirements

- Python 3.11+
- Ollama running locally or on a remote host
- A model that supports tool calling (e.g., llama3.2, qwen3, mistral)

## License

MIT
