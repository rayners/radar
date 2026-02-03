# Radar

Local-first AI assistant with native Ollama tool calling. Currently at Phase 1 (MVP).

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

# Testing with specific Ollama host
RADAR_OLLAMA_URL="http://host:11434" radar ask "test"
```

## Architecture

- `radar/agent.py` - Orchestrates context building + tool call loop
- `radar/llm.py` - Ollama client (uses `/v1/chat/completions` with `stream: false`)
- `radar/memory.py` - JSONL conversation storage (one file per conversation)
- `radar/config.py` - YAML config with env var overrides
- `radar/tools/` - Tool modules registered via `@tool` decorator

## Code Conventions

- Tools are registered with the `@tool` decorator in `radar/tools/`
- Tools return strings (results displayed to user)
- Config: YAML in `radar.yaml` or `~/.config/radar/radar.yaml`
- Environment variables override config: `RADAR_OLLAMA_URL`, `RADAR_OLLAMA_MODEL`, `RADAR_NTFY_TOPIC`

## Key Design Decisions

- **Always `stream: false`** - Ollama streaming breaks tool calling
- **No frameworks** - No LangChain/agent frameworks; tool loop is ~50 lines
- **JSONL conversations** - One file per conversation in `~/.local/share/radar/conversations/`
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

Default Ollama: `http://big-think.internal:11434` with model `llama3.2`

Models tested working: `llama3.2`, `qwen3:latest`
