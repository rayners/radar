# Radar

Local-first AI assistant with native Ollama tool calling. Currently at Phase 2 (Semantic Memory).

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
- `radar/llm.py` - Ollama client (uses `/api/chat` with `stream: false`)
- `radar/memory.py` - JSONL conversation storage (one file per conversation)
- `radar/semantic.py` - Embedding client + SQLite semantic memory storage
- `radar/config.py` - YAML config with env var overrides
- `radar/tools/` - Tool modules registered via `@tool` decorator

## Code Conventions

- Tools are registered with the `@tool` decorator in `radar/tools/`
- Tools return strings (results displayed to user)
- Config: YAML in `radar.yaml` or `~/.config/radar/radar.yaml`
- Environment variables override config: `RADAR_OLLAMA_URL`, `RADAR_OLLAMA_MODEL`, `RADAR_NTFY_TOPIC`, `RADAR_EMBEDDING_MODEL`

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

Default Ollama: `http://big-think.internal:11434` with model `qwen3:latest`

Models tested working: `qwen3:latest`, `llama3.2` (note: llama3.2 has inconsistent tool calling)

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
