# RADAR — Project Specification

> A lightweight, local-first AI assistant with a heartbeat.

## Overview

Radar is a personal AI assistant that runs locally, backed by Ollama. Unlike OpenClaw/Moltbot (which inspired this project), Radar is intentionally minimal: no messaging platform bridges, no bloated system prompt, no complex gateway architecture. It focuses on what matters: a proactive heartbeat loop, reliable native tool calling, persistent memory, and practical automation tasks.

The user has two machines available:

- **Mac mini**: Apple Silicon, 24GB unified memory — target for running Radar + smaller models (7–32B)
- **Headless Linux box**: Quadro RTX 4000 (8GB VRAM), 64GB system RAM — can serve larger models via Ollama remotely

Radar should be able to use Ollama running locally or on a remote host.

## Design Principles

1. **Minimal system prompt** — Keep it tight. Every token in the system prompt is a token a small model has to process on every heartbeat tick. Target under 500 tokens for the core prompt.
1. **Native tool calling** — Use Ollama’s OpenAI-compatible `/v1/chat/completions` endpoint with the `tools` parameter and `stream: false`. Do NOT embed tool definitions in the prompt. This is critical for small model reliability.
1. **Heartbeat-first** — Radar’s primary mode of operation is proactive. It wakes on a schedule, checks for things that need attention, and acts or notifies. Interactive chat is secondary.
1. **Incremental build** — The architecture should support adding new tools/capabilities without modifying core logic. Each capability is a tool module.
1. **Local-first, privacy-respecting** — All data stays on disk. No cloud dependencies except Ollama model APIs if configured remotely.

## Tech Stack

- **Language**: Python 3.11+ (the user is comfortable with Python; it has excellent libraries for PDF processing, email, browser automation, etc.)
- **LLM Backend**: Ollama via OpenAI-compatible API (`/v1/chat/completions`)
- **Database**: SQLite for conversation history, memory, and task state
- **Notifications**: ntfy.sh (simple HTTP POST to send push notifications)
- **Web UI**: A simple web interface (FastAPI + HTMX, or similar lightweight approach) for viewing conversation history, managing configuration, and interacting with Radar directly. Nothing fancy — functional over pretty.
- **Terminal UI**: Optional TUI for direct interaction (could be as simple as a CLI chat mode using `readline` or `prompt_toolkit`)

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   Scheduler                      │
│              (APScheduler / cron)                 │
│                                                   │
│  Heartbeat tick every N minutes                   │
│  Event-driven triggers (file watcher, etc.)       │
└──────────────────┬────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│                 Core Agent                        │
│                                                   │
│  1. Build context (system prompt + memory +       │
│     recent events + available tools)              │
│  2. Call Ollama /v1/chat/completions              │
│     (stream: false, tools: [...])                 │
│  3. If tool_calls in response, execute them       │
│  4. Return tool results to LLM for follow-up      │
│  5. Repeat until LLM has no more tool calls       │
│  6. Store conversation in SQLite                  │
│  7. If notification-worthy, POST to ntfy.sh       │
└──────────────────┬────────────────────────────────┘
                   │
          ┌────────┴────────┐
          ▼                 ▼
┌──────────────┐   ┌──────────────────┐
│  Tool Layer  │   │  Memory Layer     │
│              │   │                    │
│  - exec      │   │  - SQLite store    │
│  - read_file │   │  - Summaries       │
│  - write_file│   │  - User prefs      │
│  - web_search│   │  - Learned facts   │
│  - notify    │   │  - Task history    │
│  - pdf_extract│  │                    │
│  - browse    │   │                    │
│  - (etc.)    │   │                    │
└──────────────┘   └──────────────────────┘
```

## Core Components

### 1. Ollama Client (`radar/llm.py`)

A thin wrapper around Ollama’s OpenAI-compatible API.

Key requirements:

- Use `/v1/chat/completions` endpoint
- Always send `stream: false` (critical — streaming breaks tool calling in Ollama)
- Pass tools via the `tools` parameter (OpenAI function calling format)
- Support configurable `base_url` (for local or remote Ollama)
- Support configurable model name
- Handle the tool call loop: LLM responds with tool_calls → execute tools → send results back → repeat until done
- Respect a maximum iteration limit (e.g., 10 tool call rounds) to prevent runaway loops

Example request shape:

```json
{
  "model": "qwen2.5:14b",
  "stream": false,
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."}
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "read_file",
        "description": "Read contents of a file",
        "parameters": {
          "type": "object",
          "properties": {
            "path": {"type": "string", "description": "Path to the file"}
          },
          "required": ["path"]
        }
      }
    }
  ]
}
```

### 2. Tool System (`radar/tools/`)

Each tool is a Python module that registers itself with a name, description, parameter schema, and an execute function. The tool registry collects these and generates the `tools` array for the API call.

**Core tools to implement first:**

- `exec` — Run a shell command, return stdout/stderr. Include safety: configurable allowlist/blocklist of commands, confirmation mode for destructive operations.
- `read_file` — Read a file and return its contents (with size limits).
- `write_file` — Write content to a file.
- `list_directory` — List files in a directory.
- `notify` — Send a notification via ntfy.sh. Parameters: title, message, priority, tags.
- `web_search` — Search the web (could use SearXNG self-hosted, or a simple API like Brave Search).
- `pdf_extract` — Extract text and/or images from the first N and last N pages of a PDF. Uses `pymupdf` (fitz). Returns extracted text. For image-based pages, note that they’d need a vision model (future enhancement).
- `remember` — Store a fact or preference in the memory database.
- `recall` — Search the memory database for relevant facts.

**Tool registration pattern:**

```python
from radar.tools import tool

@tool(
    name="read_file",
    description="Read the contents of a file at the given path",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute or relative file path"}
        },
        "required": ["path"]
    }
)
def read_file(path: str) -> str:
    """Read a file and return its contents."""
    with open(path, 'r') as f:
        return f.read()
```

### 3. Memory System (`radar/memory.py`)

SQLite-backed persistent memory. Two layers:

**Conversation history:**

- Store every heartbeat and interactive conversation
- Fields: timestamp, role, content, tool_calls, tool_results, conversation_id
- Support retrieval of recent N conversations for context building

**Semantic memory (knowledge base):**

- Key-value style facts the LLM explicitly stores via the `remember` tool
- Fields: timestamp, category, key, value, source (which conversation created it)
- Categories like: `user_preference`, `learned_fact`, `task_state`, `personality_note`
- Simple keyword search via the `recall` tool (FTS5 in SQLite)
- Future enhancement: vector embeddings for semantic search

**Personality evolution:**

- Radar has a base personality defined in config (a short description)
- Over time, it can store personality notes (“user prefers brief responses”, “user likes dry humor”)
- These are injected into the system prompt from the memory DB
- Keep this bounded — only include the N most recent/relevant personality notes

### 4. Heartbeat Scheduler (`radar/scheduler.py`)

Uses APScheduler (or similar) to run periodic tasks.

**Heartbeat tick:**

- Default: every 15 minutes (configurable)
- On each tick, build a context message: “It is {time}. Here is a summary of recent events: {events}. Check if anything needs attention.”
- The LLM decides what to do (or nothing)
- Events come from registered event sources (new files in watched dirs, unread email summaries, etc.)

**Event sources (registered as plugins):**

- File watcher: monitor specified directories for new/changed files
- Email checker: IMAP connection, fetch unread count + subjects (not full bodies unless asked)
- Calendar: check upcoming events (ical file or CalDAV)
- Custom: user-defined checks via config

**Task scheduling:**

- Support cron-style scheduled tasks: “Every Monday at 9am, summarize my week”
- Stored in SQLite, loaded on startup

### 5. Configuration (`radar/config.py`)

YAML or TOML config file. Keep it simple.

```yaml
# radar.yaml
radar:
  name: "Radar"
  personality: "A competent, understated assistant. Concise and practical. Dry wit when appropriate. Anticipates needs without being overbearing."

ollama:
  base_url: "http://localhost:11434/v1"
  model: "qwen2.5:14b"
  # Optional: different model for different tasks
  # vision_model: "llava:13b"

heartbeat:
  interval_minutes: 15
  quiet_hours:
    start: "23:00"
    end: "07:00"

notifications:
  ntfy:
    url: "https://ntfy.sh"
    topic: "radar-alerts"
    # or self-hosted: url: "https://ntfy.yourdomain.com"

memory:
  max_conversation_context: 10  # number of recent exchanges to include
  max_personality_notes: 5

watchers:
  - path: "~/Downloads"
    pattern: "*.pdf"
    action: "new_pdf_detected"
  - path: "~/Comics/Inbox"
    pattern: "*.cb?"
    action: "new_comic_detected"

# email:
#   imap_host: "imap.example.com"
#   imap_user: "user@example.com"
#   imap_password_cmd: "pass show email/imap"  # or use keyring

tools:
  exec:
    enabled: true
    confirm_destructive: true
  web_search:
    provider: "brave"  # or "searxng"
    # api_key_cmd: "pass show api/brave-search"
```

### 6. Web UI (`radar/web/`)

A simple FastAPI application with HTMX for interactivity. Not a SPA — keep it server-rendered and lightweight.

**Pages:**

- `/` — Dashboard: last heartbeat status, recent notifications, quick stats
- `/chat` — Interactive chat with Radar (send messages, see responses with tool call details)
- `/history` — Browse conversation history (heartbeats and interactive)
- `/memory` — View and manage stored memories/facts
- `/config` — View/edit configuration
- `/tasks` — View scheduled tasks and their status
- `/logs` — Tail the agent log

### 7. CLI Interface (`radar/cli.py`)

Simple CLI for quick interaction and management.

```bash
# Interactive chat
radar chat

# One-shot question
radar ask "What PDFs did I download this week?"

# Trigger a heartbeat manually
radar heartbeat

# Manage memory
radar memory list
radar memory search "favorite"
radar memory forget <id>

# Status
radar status

# Start the daemon (scheduler + web UI)
radar start
radar stop
```

## Phase 1 — MVP (Start Here)

The goal of Phase 1 is to validate that a small local model can reliably do native tool calling through Ollama with a minimal prompt. Everything else is secondary.

**Build these components:**

1. `radar/llm.py` — Ollama client with tool call loop
1. `radar/tools/__init__.py` — Tool registry
1. `radar/tools/exec.py` — Shell exec tool
1. `radar/tools/read_file.py` — File read tool
1. `radar/tools/write_file.py` — File write tool
1. `radar/tools/list_directory.py` — Directory listing tool
1. `radar/tools/notify.py` — ntfy.sh notification tool
1. `radar/tools/pdf_extract.py` — PDF first/last page extraction
1. `radar/memory.py` — SQLite conversation store (basic, no semantic memory yet)
1. `radar/config.py` — YAML config loader
1. `radar/cli.py` — `radar chat` and `radar ask` commands
1. A minimal system prompt

**Phase 1 system prompt (target: ~300 tokens):**

```
You are Radar, a personal AI assistant running locally on the user's machine.
You are concise, practical, and proactive. You use tools to take action rather
than just suggesting what the user could do.

When given a task, execute it using your available tools. If you need multiple
steps, work through them sequentially. Report results briefly.

If you discover something noteworthy during a task, flag it. If you're unsure
about a destructive action, ask for confirmation.

Current time: {current_time}
```

**Validation test:** Once Phase 1 is built, test it with these prompts:

- “List the PDFs in my Downloads folder”
- “Read the first page of [some PDF] and tell me what it is”
- “Send me a notification saying hello”
- “Create a file called test.txt with today’s date in it”

If the model handles these reliably with proper tool calls (not hallucinated tools or embedded-in-text fake tool calls), Phase 1 is a success.

## Phase 2 — Heartbeat & Memory

- APScheduler integration for periodic heartbeat
- File watcher event source
- Semantic memory with `remember` and `recall` tools
- Personality notes injection
- `radar start` daemon mode
- Basic web dashboard

## Phase 3 — Practical Automation

- PDF/comic metadata extraction pipeline (extract → search APIs → update metadata)
- Email monitoring via IMAP
- Browser automation via Playwright for web form filling
- Finance transaction categorization
- Calendar integration

## Phase 4 — Polish

- Full web UI with chat, history, memory management
- Vision model support for image-based PDF pages
- Remote Ollama configuration (Mac mini → Linux box)
- Multiple model routing (fast small model for triage, larger model for complex tasks)
- MCP server support (to integrate with other tools)

## Project Structure

```
radar/
├── radar/
│   ├── __init__.py
│   ├── agent.py          # Core agent loop (context building, tool call orchestration)
│   ├── cli.py            # Click-based CLI
│   ├── config.py         # YAML config loader
│   ├── llm.py            # Ollama client
│   ├── memory.py         # SQLite memory layer
│   ├── scheduler.py      # APScheduler heartbeat (Phase 2)
│   ├── tools/
│   │   ├── __init__.py   # Tool registry + @tool decorator
│   │   ├── exec.py
│   │   ├── read_file.py
│   │   ├── write_file.py
│   │   ├── list_directory.py
│   │   ├── notify.py
│   │   ├── pdf_extract.py
│   │   ├── remember.py   # (Phase 2)
│   │   └── recall.py     # (Phase 2)
│   └── web/
│       ├── __init__.py   # FastAPI app (Phase 2+)
│       ├── routes.py
│       └── templates/
├── tests/
├── radar.yaml            # Default config
├── pyproject.toml
└── README.md
```

## Dependencies (Phase 1)

```
httpx          # HTTP client for Ollama API
click          # CLI framework
pyyaml         # Config parsing
pymupdf        # PDF text/image extraction (fitz)
rich           # Pretty terminal output
```

## Key Technical Decisions

1. **`stream: false` always** — Ollama’s streaming breaks tool calling. This is non-negotiable. See: https://github.com/openclaw/openclaw/issues/5769
1. **No LangChain, no agent frameworks** — This is intentionally lean. The tool call loop is ~50 lines of code. Adding a framework adds thousands of tokens of abstraction for no benefit at this scale.
1. **SQLite over everything** — No need for Redis, Postgres, or vector DBs in Phase 1. SQLite with FTS5 handles keyword search well enough. Vector search can come later if needed.
1. **Tools are just functions** — No complex plugin architecture. A decorated Python function that takes typed params and returns a string. The registry generates the OpenAI tool schema from the decorator metadata.
1. **Heartbeat messages are just user messages** — No special protocol. The scheduler constructs a user message (“It’s 9:15am, here’s what’s new…”) and sends it through the same agent loop as interactive chat. The LLM doesn’t need to know the difference.
