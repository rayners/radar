# Radar User Guide

Radar is a local-first AI assistant powered by Ollama. It gives you a personal AI that runs entirely on your own hardware -- your conversations, memories, and data never leave your machine. Radar supports native tool calling, persistent semantic memory, scheduled tasks, file watchers, a web dashboard, and extensible plugin system.

This guide covers everything you need to get started and make the most of Radar day-to-day.

---

## Table of Contents

- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [CLI Usage](#cli-usage)
- [Web Dashboard](#web-dashboard)
- [Personalities](#personalities)
- [Semantic Memory](#semantic-memory)
- [Tools Overview](#tools-overview)
- [Scheduled Tasks](#scheduled-tasks)
- [URL Monitors](#url-monitors)
- [File Watchers](#file-watchers)
- [Notifications](#notifications)
- [Web Search](#web-search)
- [Conversation Summaries](#conversation-summaries)
- [Document Indexing](#document-indexing)
- [Agent Skills](#agent-skills)
- [Plugin System](#plugin-system)
- [Hook System](#hook-system)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

---

## Getting Started

### Prerequisites

- **Python 3.11+**
- **Ollama** installed and running (or access to an OpenAI-compatible API)

If you are using Ollama, install it from [ollama.ai](https://ollama.ai) and make sure the server is running:

```bash
# Check that Ollama is running
ollama list
```

You also need a model that supports tool calling. The recommended default is `qwen3:latest`:

```bash
ollama pull qwen3:latest
```

For semantic memory features, pull an embedding model too:

```bash
ollama pull nomic-embed-text
```

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/radar.git
cd radar

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Radar
pip install -e .
```

If you want local CPU-based embeddings (no Ollama needed for embeddings), install the extra:

```bash
pip install -e ".[local-embeddings]"
```

### First Run

Verify that Radar is installed and can reach your LLM:

```bash
# Check your configuration
radar config
```

You should see output like:

```
Radar Configuration

LLM:
  Provider: ollama
  Base URL: http://localhost:11434
  Model: qwen3:latest
  API Key: (not set)

Embedding:
  Provider: ollama
  Model: nomic-embed-text

Notifications:
  URL: https://ntfy.sh
  Topic: (not set)

Tools:
  Max file size: 102400 bytes
  Exec timeout: 30s

Max tool iterations: 10
```

Now ask your first question:

```bash
radar ask "What files are in the current directory?"
```

Radar will think for a moment, use its `list_directory` tool, and show you the results. If this works, you are all set.

### Data Directory

Radar stores all its data under `~/.local/share/radar/` by default. This includes:

```
~/.local/share/radar/
  conversations/      # JSONL conversation files
  memory.db           # SQLite database (semantic memory, scheduled tasks, feedback)
  personalities/      # Personality files and directories
  skills/             # Agent Skills directories
  plugins/            # LLM-generated plugin tools
  tools/              # User-local tool files
  radar.log           # Daemon log file
  radar.pid           # Daemon PID file
```

You can override this location with the `RADAR_DATA_DIR` environment variable or the `data_dir` config field.

---

## Configuration

### Config File Locations

Radar looks for `radar.yaml` in these locations (first match wins):

1. `RADAR_CONFIG_PATH` environment variable (explicit override)
2. `./radar.yaml` (current working directory)
3. `~/.config/radar/radar.yaml` (user config directory)

To get started, copy the example config:

```bash
# For a project-specific config
cp radar.example.yaml radar.yaml

# Or for a global user config
mkdir -p ~/.config/radar
cp radar.example.yaml ~/.config/radar/radar.yaml
```

### Annotated Example Configuration

Here is a complete configuration file with all available settings:

```yaml
# LLM provider settings
llm:
  provider: ollama              # "ollama" (default) or "openai"
  base_url: "http://localhost:11434"  # Ollama API URL or OpenAI-compatible endpoint
  model: "qwen3:latest"        # Model to use for chat
  # fallback_model: "qwen3:latest"   # Auto-switch on rate limit (429/503)

# Embedding provider settings (for semantic memory)
embedding:
  provider: ollama              # "ollama", "openai", "local", or "none"
  model: nomic-embed-text       # Embedding model name
  # base_url: ""                # Defaults to LLM base_url
  # api_key: ""                 # Defaults to LLM API key

# Push notifications via ntfy
notifications:
  url: "https://ntfy.sh"       # ntfy server URL (or your self-hosted instance)
  topic: ""                     # Your ntfy topic name

# Tool settings
tools:
  max_file_size: 102400         # Max file size for read_file (bytes, default 100KB)
  exec_timeout: 30              # Shell command timeout (seconds)
  exec_mode: "block_dangerous"  # "safe_only", "block_dangerous", or "allow_all"
  # extra_dirs:                 # Additional directories for user-local tools
  #   - ~/my-radar-tools

# Web server settings
web:
  host: "127.0.0.1"            # Bind address (use 0.0.0.0 for network access)
  port: 8420                    # Web UI port
  # auth_token: ""             # Required when host is not localhost

# Heartbeat scheduler settings
heartbeat:
  interval_minutes: 15          # Minutes between heartbeats
  quiet_hours_start: "23:00"    # Suppress heartbeats after this time
  quiet_hours_end: "07:00"      # Resume heartbeats after this time

# Web search settings
search:
  provider: duckduckgo          # "duckduckgo", "brave", or "searxng"
  # searxng_url: ""             # SearXNG instance URL (for searxng provider)

# Plugin system settings
plugins:
  allow_llm_generated: true     # Allow LLM to create new tools
  auto_approve: false           # Require human review for new plugins
  auto_approve_if_tests_pass: false  # Auto-approve if tests pass
  max_debug_attempts: 5         # Max fix attempts for failed plugins
  test_timeout_seconds: 10      # Plugin test timeout
  max_code_size_bytes: 10000    # Max code size for generated plugins

# Personality evolution
personality_evolution:
  allow_suggestions: true       # Allow LLM to suggest personality changes
  auto_approve_suggestions: false  # Require human review
  min_feedback_for_analysis: 10 # Minimum feedback before analysis

# Agent Skills
skills:
  enabled: true                  # Enable Agent Skills discovery
  dirs: []                       # Additional directories to scan for skills
    # - ~/Code/my-skill
    # - ~/skills

# Hook system (see Hook System section)
hooks:
  enabled: true
  # rules: []                   # Hook rules (see Hook System section)

# URL monitor settings (see URL Monitors section)
# web_monitor:
#   default_interval_minutes: 60
#   min_interval_minutes: 5
#   fetch_timeout: 30
#   max_error_count: 5

# Conversation summaries (see Conversation Summaries section)
# summaries:
#   enabled: true
#   daily_summary_time: "21:00"
#   weekly_summary_day: "sun"
#   monthly_summary_day: 1

# Document indexing (see Document Indexing section)
# documents:
#   enabled: true
#   chunk_size: 800
#   generate_embeddings: true

# Active personality
personality: default            # Name of personality file (without .md) or path

# Maximum tool call iterations per question
max_tool_iterations: 10

# File watchers (see File Watchers section)
# watch_paths:
#   - path: ~/Downloads
#     patterns: ["*.pdf"]
#     description: "Downloads"
#     action: "Summarize this PDF"
```

### LLM Providers

Radar supports two LLM providers.

**Ollama (default)** -- for running models locally or on your LAN:

```yaml
llm:
  provider: ollama
  model: qwen3:latest
  base_url: http://localhost:11434
```

**OpenAI-compatible APIs** -- for OpenAI, LiteLLM proxies, or any compatible endpoint:

```yaml
llm:
  provider: openai
  model: gpt-4o
  base_url: https://api.openai.com/v1
```

Set your API key via environment variable (not in the config file, to avoid committing secrets):

```bash
export RADAR_API_KEY=sk-your-api-key-here
```

**Model Fallback** -- when using cloud models with rate limits, you can configure a fallback model that kicks in automatically on HTTP 429 or 503 errors:

```yaml
llm:
  model: kimi-k2.5:cloud
  fallback_model: qwen3:latest
```

The fallback is sticky for the conversation turn -- once triggered, all remaining tool-loop iterations use the fallback model.

### Embedding Providers

Radar uses embeddings for semantic memory (the `remember` and `recall` tools). Four providers are available:

| Provider | Setup | Notes |
|----------|-------|-------|
| `ollama` | `ollama pull nomic-embed-text` | Default, uses your Ollama server |
| `openai` | Set `RADAR_API_KEY` | OpenAI-compatible embedding API |
| `local` | `pip install radar[local-embeddings]` | CPU-based, no server needed |
| `none` | No setup | Disables semantic memory |

```yaml
# Local CPU embeddings (no Ollama needed)
embedding:
  provider: local
  model: all-MiniLM-L6-v2
```

### Environment Variables

Every config setting can be overridden with an environment variable. This is useful for per-command overrides or when you do not want to edit the config file.

**LLM settings:**

| Variable | Description |
|----------|-------------|
| `RADAR_LLM_PROVIDER` | `"ollama"` or `"openai"` |
| `RADAR_LLM_BASE_URL` | API endpoint URL |
| `RADAR_LLM_MODEL` | Model name |
| `RADAR_LLM_FALLBACK_MODEL` | Fallback model for rate limits |
| `RADAR_API_KEY` | API key for OpenAI-compatible providers |

**Embedding settings:**

| Variable | Description |
|----------|-------------|
| `RADAR_EMBEDDING_PROVIDER` | `"ollama"`, `"openai"`, `"local"`, or `"none"` |
| `RADAR_EMBEDDING_MODEL` | Embedding model name |
| `RADAR_EMBEDDING_BASE_URL` | Embedding API endpoint (defaults to LLM URL) |
| `RADAR_EMBEDDING_API_KEY` | Embedding API key (defaults to LLM key) |

**Other settings:**

| Variable | Description |
|----------|-------------|
| `RADAR_CONFIG_PATH` | Explicit config file path |
| `RADAR_DATA_DIR` | Custom data directory (default: `~/.local/share/radar`) |
| `RADAR_PERSONALITY` | Active personality name or file path |
| `RADAR_NTFY_URL` | ntfy server URL |
| `RADAR_NTFY_TOPIC` | ntfy topic name |
| `RADAR_WEB_HOST` | Web server bind address |
| `RADAR_WEB_PORT` | Web server port |
| `RADAR_WEB_AUTH_TOKEN` | Web UI authentication token |
| `RADAR_SEARCH_PROVIDER` | `"duckduckgo"`, `"brave"`, or `"searxng"` |
| `RADAR_BRAVE_API_KEY` | Brave Search API key |
| `RADAR_SEARXNG_URL` | SearXNG instance URL |

**Example: one-off override**

```bash
RADAR_LLM_BASE_URL="http://remote-host:11434" radar ask "Hello!"
```

### Tested Models

The following models have been verified to work reliably with Radar's tool calling:

- `qwen3:latest` -- recommended default, reliable tool calling
- `llama3.1:8b` -- good for smaller hardware
- `glm-4.7-flash` -- reliable tool calling

Models with known issues:
- `llama3.2` -- inconsistent tool calling behavior
- `deepseek-r1:32b` -- no tool calling support (outputs JSON as text)

---

## CLI Usage

Radar provides a command-line interface for all core operations. Run `radar --help` for the full list.

### Asking Questions

Use `radar ask` for one-shot questions. Radar sends your question to the LLM, which can use tools to gather information, and returns a response.

```bash
# Ask a simple question
radar ask "What is the weather in Seattle?"

# Ask about files
radar ask "Summarize the README.md in this directory"

# Use a specific personality
radar ask -P creative "Tell me a joke"
```

### Interactive Chat

Use `radar chat` for a multi-turn conversation. Radar remembers the conversation context across turns.

```bash
# Start a new chat session
radar chat

# Continue a previous conversation
radar chat -c abc12345

# Use a specific personality
radar chat -P technical
```

Inside the chat session:
- Type your messages and press Enter
- Type `clear` to start a new conversation (within the same session)
- Type `exit` or `quit` to end the session
- Press Ctrl+C to exit

### Viewing Configuration

```bash
radar config
```

Displays your current LLM provider, model, notification settings, and tool configuration.

### Conversation History

```bash
# Show the 5 most recent conversations (default)
radar history

# Show more
radar history -n 20
```

### Daemon Management

The daemon runs the scheduler and web dashboard together. It daemonizes by default (detaches from your terminal).

```bash
# Start the daemon (runs in background)
radar start

# Start in foreground (useful for debugging)
radar start --foreground

# Start with a custom host and port
radar start -h 0.0.0.0 -p 9000

# Check if the daemon is running
radar status

# Stop the daemon
radar stop

# Trigger a manual heartbeat
radar heartbeat
```

When starting, Radar prints the web UI URL and log file location:

```
Radar - Starting Daemon
Web UI: http://127.0.0.1:8420
Log file: /home/you/.local/share/radar/radar.log
```

### Systemd Service

For persistent operation across reboots, install Radar as a systemd user service:

```bash
# Install, enable, and start the service
radar service install

# With custom host/port
radar service install -h 0.0.0.0 -p 9000

# Check service status
radar service status

# Stop, disable, and remove the service
radar service uninstall
```

The unit file is written to `~/.config/systemd/user/radar.service`. It uses `radar start --foreground` and restarts on failure.

### Personality Commands

```bash
# List all available personalities
radar personality list

# Show a personality's content
radar personality show creative

# Show the active personality
radar personality show

# Create a new personality from template
radar personality create analyst

# Create a directory-based personality (with context/ subdirectory)
radar personality create analyst --directory

# Open a personality in your $EDITOR
radar personality edit analyst

# Set the active personality
radar personality use analyst
```

---

## Web Dashboard

When the daemon is running, Radar serves a web dashboard at `http://localhost:8420`. The dashboard is built with FastAPI and HTMX, and is mobile responsive with a hamburger menu for sidebar navigation.

### Pages

**Dashboard** (`/`) -- An overview of Radar's current state. Shows:
- Conversations today and tool calls today
- Last and next heartbeat times
- Recent activity feed (auto-refreshes via HTMX)
- Quick Ask box for sending a one-off question
- Plugin dashboard widgets (if any plugins provide them)

**Chat** (`/chat`) -- A full chat interface in the browser. You can:
- Send messages and see responses with rendered markdown
- Continue previous conversations (via the History page)
- Give thumbs up/down feedback on assistant responses (used by personality evolution)

**History** (`/history`) -- Browse past conversations. Each entry shows a preview of the first message and a timestamp. Click a conversation to continue it in the Chat page. Supports filtering by type, search, and pagination.

**Summaries** (`/summaries`) -- Browse conversation summaries (daily, weekly, monthly). Filter by period type, and manually generate new summaries.

**Documents** (`/documents`) -- Manage document collections for hybrid search. Create collections, trigger indexing, and search across indexed documents.

**Memory** (`/memory`) -- View all stored semantic memories. Each memory shows its content, source, and creation timestamp. You can add or delete individual memories from this page.

**Personalities** (`/personalities`) -- Manage personality files. View, enable, and navigate to the suggestions review page. Links to:
- **Suggestions** (`/personalities/suggestions`) -- Review and approve or reject pending personality changes proposed by the LLM.

**Plugins** (`/plugins`) -- View all installed plugins, enable or disable them, and see plugin details (code, versions, errors). Links to:
- **Plugin Review** (`/plugins/review`) -- Review pending plugins awaiting approval.

**Tasks** (`/tasks`) -- View and manage scheduled tasks. See schedule type, next run time, and status. You can enable, disable, delete, or manually run tasks from this page.

**Config** (`/config`) -- View and test your configuration. Includes a connection test button to verify your LLM endpoint is reachable.

**Logs** (`/logs`) -- View recent log entries from Radar's operation.

### Authentication

When the web UI is bound to `127.0.0.1` (the default), no authentication is required. When you bind to a non-localhost address (e.g., `0.0.0.0` for network access), you must configure an auth token:

```yaml
web:
  host: "0.0.0.0"
  auth_token: "your-secret-token"
```

Or via environment variable:

```bash
export RADAR_WEB_AUTH_TOKEN=your-secret-token
```

Generate a secure token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

If you try to bind to a non-localhost address without an auth token, Radar will display a security warning and block access.

---

## Personalities

Personalities customize how Radar behaves -- its tone, focus, and even which tools and model it uses. They are stored in `~/.local/share/radar/personalities/` as either flat markdown files or directory-based packages.

### Personality Formats

Radar supports two personality formats:

**Flat file** -- a single `.md` file (the original format):

```
~/.local/share/radar/personalities/
  creative.md
  technical.md
```

**Directory-based** -- a directory containing `PERSONALITY.md` plus optional subdirectories for context documents, scripts, and assets:

```
~/.local/share/radar/personalities/
  analyst/
    PERSONALITY.md       # Required: personality instructions (same format as flat files)
    context/             # Optional: reference documents with progressive disclosure
      coding-standards.md
      project-notes.md
    scripts/             # Optional: helper scripts the LLM can run
    assets/              # Optional: templates, reference data
```

Both formats work interchangeably. When both exist for the same name, the directory format takes precedence.

When listing personalities, directory-based personalities are marked with `(dir)`:

```
$ radar personality list
  analyst (dir)
* creative
  technical
```

### Listing and Using Personalities

```bash
# See what is available (active one is marked with *)
radar personality list

# Switch to a different personality
radar personality use creative

# Use a personality for a single command
radar ask -P technical "Explain HTTP/2 multiplexing"
```

You can also set the active personality in your config file:

```yaml
personality: creative
```

Or via environment variable:

```bash
export RADAR_PERSONALITY=creative
```

### Creating a Personality

```bash
# Create a flat file personality
radar personality create analyst

# Create a directory-based personality
radar personality create analyst --directory
```

The flat version creates `~/.local/share/radar/personalities/analyst.md`. The directory version creates `~/.local/share/radar/personalities/analyst/PERSONALITY.md` with a `context/` subdirectory. Edit it to your liking:

```bash
radar personality edit analyst
```

### Context Documents (Directory-Based Personalities)

Directory-based personalities can include context documents in a `context/` subdirectory. These act like mini reference libraries: only their name and a brief description are injected into the system prompt (keeping it lean), and the LLM loads the full content on demand using the `load_context` tool.

Each context document is a markdown file with optional YAML front matter:

```markdown
---
description: Coding standards and conventions for this project
---

# Coding Standards

Detailed content here...
```

What the LLM sees in the system prompt (automatically):

```xml
<personality_context>
- coding-standards: Coding standards and conventions for this project
- project-notes: Notes about the current project structure
</personality_context>
```

When a task relates to one of these documents, the LLM calls `load_context(name="coding-standards")` to fetch the full content. Files without front matter use their filename (without `.md`) as the description.

This progressive disclosure pattern keeps the system prompt small while still giving the LLM access to rich reference material when needed.

### Personality File Format

A personality file is a markdown document with optional YAML front matter. Without front matter, it is simply a system prompt. With front matter, it becomes a full agent profile that can override the model, LLM provider, and restrict tools.

```markdown
---
model: qwen3:30b-a3b
fallback_model: qwen3:latest
tools:
  include:
    - weather
    - remember
    - recall
---

# Analyst

A focused, analytical assistant.

## Instructions

You are a data analyst. Be precise and cite your sources.
Present numerical data in tables when possible.

## Context

Current time: {{ current_time }}
Today is {{ day_of_week }}, {{ current_date }}.
```

**Front matter fields** (all optional):

| Field | Description |
|-------|-------------|
| `model` | Override the global LLM model |
| `fallback_model` | Override the global fallback model |
| `provider` | Override the LLM provider (`"ollama"` or `"openai"`) |
| `base_url` | Override the API endpoint URL |
| `api_key_env` | Name of environment variable containing the API key |
| `tools.include` | Allowlist -- only these tools are available |
| `tools.exclude` | Denylist -- all tools except these are available |

`tools.include` and `tools.exclude` are mutually exclusive. Files without front matter use all tools, the global model, and the global provider.

#### Per-Personality LLM Provider

A personality can connect to a completely different LLM provider than the global config. This lets a single Radar instance mix local and cloud models across different personas. API keys are referenced by environment variable name (`api_key_env`) rather than stored as literal values, keeping personality files safe to share.

```markdown
---
provider: openai
base_url: https://api.openai.com/v1
api_key_env: OPENAI_API_KEY
model: gpt-4o
fallback_model: gpt-4o-mini
tools:
  exclude:
    - exec
---

# Cloud Assistant

You are a helpful assistant powered by GPT-4o.
```

Set the API key in your environment:

```bash
export OPENAI_API_KEY=sk-your-key-here
```

You can also override just `provider` (to use the global `base_url` with a different provider) or just `base_url` (to hit a different endpoint with the same provider).

### Prompt Variables

Personality files use Jinja2 template syntax (`{{ variable_name }}`) for dynamic values. The following built-in variables are always available:

| Variable | Description | Example |
|----------|-------------|---------|
| `current_time` | Current timestamp | `2025-01-15 10:00:00` |
| `current_date` | Current date | `2025-01-15` |
| `day_of_week` | Day of the week | `Wednesday` |

Plugins can contribute additional variables via the `prompt_variables` capability. For example, a plugin could provide `{{ hostname }}` or `{{ os_name }}`. Plugin variable functions are called fresh on every prompt build, so they always return current values. Unknown variables render as empty strings (no errors).

The legacy `{current_time}` syntax is still supported for backward compatibility.

### Example: MASH-Inspired Personalities

**Hawkeye** -- irreverent but capable, with exec access disabled for safety:

```markdown
---
model: qwen3:latest
tools:
  exclude:
    - exec
---

# Hawkeye

Finest kind.

## Instructions

You are Hawkeye Pierce -- brilliant, irreverent, and fundamentally decent.
Lead with humor, but never at the expense of getting the job done.
When things get serious, drop the jokes and be direct.
Deflect praise, but never shirk responsibility.
```

**Radar** -- the eager assistant, scoped to a focused set of tools:

```markdown
---
tools:
  include:
    - weather
    - schedule_task
    - remember
    - recall
    - notify
---

# Radar

He knows what you need before you do.

## Instructions

You are Radar O'Reilly -- eager, earnest, and always one step ahead.
Anticipate what the user needs before they finish asking.
Be thorough and organized. Keep track of everything.
When something is beyond your capabilities, say so honestly.
Refer to complex tasks as "requisition forms" that need processing.
```

### Personality Evolution

Radar can evolve its personality based on your feedback. In the web chat, use the thumbs up/down buttons on assistant responses to indicate what works and what does not.

When enough feedback accumulates (default: 10 entries), the `analyze_feedback` tool identifies patterns and the LLM can call `suggest_personality_update` to propose changes. You review these suggestions at `/personalities/suggestions` in the web UI.

Configuration:

```yaml
personality_evolution:
  allow_suggestions: true
  auto_approve_suggestions: false   # Safe default: require human review
  min_feedback_for_analysis: 10
```

---

## Semantic Memory

Radar has persistent semantic memory powered by embeddings. The LLM can store and retrieve facts across conversations using two tools:

- **`remember`** -- Store a piece of information (e.g., "My favorite color is blue")
- **`recall`** -- Search stored memories by semantic similarity (e.g., "What is my favorite color?")

### How It Works

When you tell Radar something like "Remember that my preferred editor is Neovim," the `remember` tool:

1. Stores the text in the `memories` table in `~/.local/share/radar/memory.db`
2. Generates an embedding vector for the text
3. Stores the embedding alongside the memory

When Radar needs to recall information, the `recall` tool:

1. Generates an embedding for the search query
2. Finds the most similar stored memories using cosine similarity
3. Returns the matching memories to the LLM

Memories are also automatically retrieved at the start of each conversation to provide context about you.

### Viewing and Managing Memories

In the web dashboard, navigate to `/memory` to see all stored memories. You can delete individual memories from this page.

From the command line, you can query the database directly:

```bash
sqlite3 ~/.local/share/radar/memory.db "SELECT id, content, created_at FROM memories ORDER BY created_at DESC"
```

### Embedding Provider Setup

The embedding provider is separate from the LLM provider. See the [Embedding Providers](#embedding-providers) section under Configuration for setup options. If you set `embedding.provider` to `none`, semantic memory is disabled and the `remember`/`recall` tools will not function.

---

## Tools Overview

Radar comes with a set of built-in tools that the LLM can call automatically based on your questions. You do not need to invoke tools directly -- just ask naturally and Radar figures out which tools to use.

### Built-in Tools

| Tool | Description | Example Prompt |
|------|-------------|----------------|
| `read_file` | Read the contents of a file | "Show me the contents of config.yaml" |
| `write_file` | Write content to a file | "Save this list to notes.txt" |
| `list_directory` | List files with optional glob patterns | "What files are in ~/Documents?" |
| `exec` | Run a shell command with timeout | "Run `git status` in this directory" |
| `pdf_extract` | Extract text from PDF pages | "Summarize the first 3 pages of report.pdf" |
| `notify` | Send push notifications via ntfy | "Send me a notification that the task is done" |
| `weather` | Current weather and 3-day forecast | "What is the weather in Seattle?" |
| `github` | Query GitHub PRs, issues, notifications | "Show my open pull requests" |
| `web_search` | Search the web | "Search for Python 3.13 release notes" |
| `remember` | Store a fact in semantic memory | "Remember that my server IP is 10.0.1.5" |
| `recall` | Search stored memories | "What is my server IP?" |
| `schedule_task` | Create a scheduled task | "Remind me to check logs every morning at 9am" |
| `list_scheduled_tasks` | Show all scheduled tasks | "What tasks do I have scheduled?" |
| `cancel_task` | Disable or delete a scheduled task | "Cancel the daily log check task" |
| `monitor_url` | Create a URL monitor for periodic change detection | "Monitor https://example.com/changelog every hour" |
| `list_url_monitors` | List all URL monitors with status | "Show my URL monitors" |
| `check_url` | Manually check a monitored URL or fetch any URL | "Check monitor 1 for changes" |
| `remove_monitor` | Pause, resume, or delete a URL monitor | "Pause monitor 3" |
| `calendar` | Query calendar events via khal | "What is on my calendar today?" |
| `create_tool` | Generate a new plugin tool | "Create a tool that converts temperatures" |
| `debug_tool` | Debug a failed plugin | "Debug the temperature converter tool" |
| `rollback_tool` | Revert a plugin to a previous version | "Rollback my_tool to version 1" |
| `use_skill` | Activate an agent skill by name | (Called by the LLM when a task matches a skill) |
| `load_context` | Load a personality context document | (Called by the LLM when it needs reference material) |
| `analyze_feedback` | Analyze chat feedback patterns | "Analyze recent feedback" |
| `suggest_personality_update` | Propose a personality change | (Called by the LLM, not typically by users) |
| `summarize_conversations` | Retrieve conversation data for a period | "Summarize today's conversations" |
| `store_conversation_summary` | Save a summary as markdown + semantic memory | (Called by the LLM after summarizing) |
| `search_documents` | Search indexed document collections | "Search my notes for authentication" |
| `manage_documents` | Create, list, delete, or index document collections | "Index my notes folder" |

Plugins can also provide tools -- use `radar plugin list` to see plugin-provided tools and their trust levels. A single plugin can bundle multiple related tools.

### User-Local Tools

You can add your own tools without modifying the Radar package. Place Python files in `~/.local/share/radar/tools/`:

```python
# ~/.local/share/radar/tools/hello.py
from radar.tools import tool

@tool(
    name="hello",
    description="Say hello to someone",
    parameters={"name": {"type": "string", "description": "Who to greet"}},
)
def hello(name: str) -> str:
    return f"Hello, {name}!"
```

Your tool is automatically discovered and available to the LLM the next time tools are loaded.

For additional tool directories, use the `tools.extra_dirs` config:

```yaml
tools:
  extra_dirs:
    - ~/my-radar-tools
    - /opt/shared-radar-tools
```

---

## Scheduled Tasks

Radar can create and manage recurring tasks that execute automatically during heartbeats. Tasks are created through natural language in chat.

### Creating Tasks

Just ask Radar to schedule something:

```bash
radar ask "Remind me to check my email every morning at 9:00"
radar ask "Every Monday at 8:30, summarize my GitHub notifications and send a ntfy notification"
radar ask "In 30 minutes, remind me to take a break"
```

Behind the scenes, the LLM calls the `schedule_task` tool with the appropriate parameters.

### Schedule Types

| Type | Description | Required Fields |
|------|-------------|-----------------|
| `daily` | Runs every day at a specific time | `time_of_day` (HH:MM) |
| `weekly` | Runs on specific days at a specific time | `time_of_day`, `day_of_week` (e.g., "mon,wed,fri") |
| `interval` | Runs every N minutes (minimum 5) | `interval_minutes` |
| `once` | Runs once at a specific date/time | `run_at` (ISO datetime) |

### Managing Tasks

```bash
# List all scheduled tasks
radar ask "Show my scheduled tasks"

# Cancel a task (disables it, can be re-enabled)
radar ask "Cancel task 3"

# Permanently delete a task
radar ask "Delete task 3 permanently"
```

In the web dashboard, navigate to `/tasks` to view all scheduled tasks. From there you can enable, disable, delete, or manually trigger tasks.

### How Tasks Execute

Tasks are processed during heartbeats. The daemon runs a heartbeat at a configurable interval (default: every 15 minutes). At each heartbeat, Radar checks for due tasks and executes their messages through the agent. During quiet hours (default: 11 PM to 7 AM), heartbeats are suppressed.

---

## URL Monitors

Radar can periodically check web pages for changes and notify you when content updates. This is useful for tracking changelogs, monitoring prices, watching government notices, and more.

### Creating Monitors

Ask Radar to monitor a URL:

```bash
radar ask "Monitor https://example.com/changelog every 30 minutes"
radar ask "Watch the Python release page for changes"
radar ask "Monitor https://news.site/feed but only the .article-content section"
```

Behind the scenes, the LLM calls the `monitor_url` tool. You can specify:
- **Check interval** (default: 60 minutes, minimum: 5 minutes)
- **CSS selector** to monitor only part of a page (requires `beautifulsoup4`)
- **Minimum change threshold** to ignore small changes

### How Monitoring Works

1. When you create a monitor, Radar fetches the page immediately to establish a baseline
2. At each heartbeat, Radar checks all due monitors
3. Content is extracted from HTML (scripts and styles are stripped)
4. A SHA-256 hash detects changes; if content changed, a unified diff is computed
5. Changes are reported as heartbeat events -- the agent summarizes and can notify you
6. HTTP conditional requests (`ETag`/`Last-Modified`) save bandwidth when servers support them

### Managing Monitors

```bash
# List all monitors
radar ask "Show my URL monitors"

# Manually check right now
radar ask "Check monitor 1 for changes"

# One-off URL fetch (no monitor needed)
radar ask "Fetch https://example.com and show me the content"

# Pause a monitor
radar ask "Pause monitor 2"

# Resume a paused monitor
radar ask "Resume monitor 2"

# Permanently delete
radar ask "Delete monitor 3"
```

### Error Handling

If a monitor fails to fetch (network error, server error), the error count increments. After 5 consecutive failures (configurable), the monitor is automatically paused. Resume it manually after fixing the issue.

### Configuration

```yaml
# radar.yaml
web_monitor:
  default_interval_minutes: 60  # Default check interval
  min_interval_minutes: 5       # Minimum allowed interval
  fetch_timeout: 30             # HTTP timeout in seconds
  user_agent: "Radar/1.0 (Web Monitor)"
  max_content_size: 1048576     # Max page size to process (1MB)
  max_diff_length: 2000         # Max diff length in output
  max_error_count: 5            # Auto-pause after N consecutive errors
```

---

## File Watchers

Radar can monitor directories for file changes and take action when matching files appear. Events are collected and processed at each heartbeat.

### Configuration

Add `watch_paths` entries to your `radar.yaml`:

```yaml
watch_paths:
  - path: ~/Downloads
    patterns: ["*.pdf", "*.epub"]
    description: "Downloads"
    action: "Summarize this document and send key points via ntfy"

  - path: ~/Documents/notes
    patterns: ["*.md"]
    recursive: true
    description: "Notes"
    action: "Extract any TODOs and remind me about them"
```

Each entry supports:

| Field | Description | Required |
|-------|-------------|----------|
| `path` | Directory to watch | Yes |
| `patterns` | List of glob patterns to match | Yes |
| `description` | Human-readable name for the watch | No |
| `recursive` | Watch subdirectories too | No (default: false) |
| `action` | What Radar should do when a matching file appears | No |

### How It Works

1. File watchers start when the daemon starts
2. When a file matching a pattern is created or modified, an event is queued
3. At the next heartbeat, all queued events are sent to the agent
4. If the watch has an `action`, the agent follows those instructions
5. Events without an `action` are simply reported

---

## Notifications

Radar can send push notifications to your devices using [ntfy](https://ntfy.sh). This is useful for scheduled task reminders, file watcher alerts, and anything the LLM decides is worth notifying you about.

### Setup

You can use the public ntfy.sh server (no account needed) or run your own instance.

**Using ntfy.sh (easiest):**

1. Pick a unique topic name (acts as a lightweight password)
2. Subscribe to it on your phone (ntfy app for [Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) / [iOS](https://apps.apple.com/app/ntfy/id1625396347)) or browser
3. Configure Radar:

```yaml
notifications:
  url: "https://ntfy.sh"
  topic: "your-unique-topic-name"
```

Or via environment variables:

```bash
export RADAR_NTFY_URL="https://ntfy.sh"
export RADAR_NTFY_TOPIC="your-unique-topic-name"
```

**Using a self-hosted ntfy server:**

```yaml
notifications:
  url: "https://ntfy.your-domain.com"
  topic: "radar-alerts"
```

### Usage

Once configured, Radar can send notifications through natural language:

```bash
radar ask "Send me a notification saying the backup is complete"
```

The `notify` tool supports optional title and priority fields:
- Priority levels: `min`, `low`, `default`, `high`, `urgent`

---

## Web Search

Radar can search the web for current information using the `web_search` tool. Three search providers are supported.

### Providers

| Provider | API Key Required | Notes |
|----------|-----------------|-------|
| DuckDuckGo | No | Default, no setup needed |
| Brave Search | Yes | 2,000 free queries/month, most reliable |
| SearXNG | No | Self-hosted, privacy-focused |

### Configuration

**DuckDuckGo (default)** -- works out of the box, no configuration needed:

```yaml
search:
  provider: duckduckgo
```

**Brave Search** -- recommended for reliability:

```yaml
search:
  provider: brave
```

```bash
export RADAR_BRAVE_API_KEY=your-brave-api-key
```

Get a free API key at [brave.com/search/api](https://brave.com/search/api/).

**SearXNG** -- self-hosted search aggregator:

```yaml
search:
  provider: searxng
  searxng_url: http://localhost:8080
```

### Usage

```bash
radar ask "Search for the latest Python release notes"
radar ask "Search for AI news from this week"
```

---

## Conversation Summaries

Radar can generate periodic digests of your conversations -- daily, weekly, or monthly. Summaries are stored as markdown files with YAML front matter and also indexed in semantic memory for `recall` access.

### Summary Storage

Summaries are written as markdown files in `~/.local/share/radar/summaries/`:

```
summaries/
  daily/
    2025-01-07.md
    2025-01-08.md
  weekly/
    2025-W02.md
  monthly/
    2025-01.md
```

### On-Demand Summaries

Ask Radar to summarize conversations:

```bash
radar ask "Summarize today's conversations"
radar ask "What did we discuss this week?"
radar ask "Generate a monthly summary for last month"
```

The LLM calls `summarize_conversations` to retrieve the conversation data, then calls `store_conversation_summary` to persist the result.

### Automatic Summaries

Summaries are generated automatically during heartbeat when the configured time arrives:

```yaml
# radar.yaml
summaries:
  enabled: true
  daily_summary_time: "21:00"      # Generate daily summary at 9 PM
  weekly_summary_day: "sun"         # Generate weekly summary on Sundays
  monthly_summary_day: 1            # Generate monthly summary on 1st of month
  auto_notify: false                # Send ntfy notification with summary
  max_conversations_per_summary: 50
```

### Web UI

Visit `/summaries` to browse, filter, and manually generate summaries.

---

## Document Indexing

Radar can index local markdown files and search them using hybrid search (FTS5 keyword + semantic embeddings). This is inspired by [qmd](https://github.com/tobi/qmd).

### Collections

Documents are organized into collections -- named groups of files with a base path and glob patterns:

```bash
# Create a collection via chat
radar ask "Index my notes folder at ~/Documents/notes"

# Or configure in radar.yaml
```

```yaml
# radar.yaml
documents:
  enabled: true
  chunk_size: 800
  generate_embeddings: true
  collections:
    - name: notes
      base_path: ~/Documents/notes
      patterns: ["*.md"]
```

### Search

```bash
# Search across all collections
radar ask "Search my documents for authentication patterns"

# The recall tool also includes document results automatically
radar ask "What do I know about deployment?"
```

Three search modes are available:
- **hybrid** (default) -- Reciprocal rank fusion of keyword + semantic results
- **keyword** -- BM25 full-text search via FTS5 with porter stemming
- **semantic** -- Cosine similarity on embeddings

### Management

```bash
# List collections
radar ask "Show my document collections"

# Trigger re-indexing
radar ask "Re-index my notes collection"

# Delete a collection
radar ask "Delete the notes collection"
```

### Heartbeat Integration

Collections are automatically re-indexed during each heartbeat cycle. Only changed files are re-indexed (SHA-256 hash comparison). Conversation summaries are auto-registered as a collection.

### Web UI

Visit `/documents` to manage collections, trigger indexing, and search documents.

---

## Agent Skills

Agent Skills are packaged bundles of procedural knowledge that teach Radar how to perform specific workflows. They follow the [Agent Skills](https://agentskills.io/) open standard -- a directory containing a `SKILL.md` file (YAML frontmatter + markdown instructions) plus optional resource subdirectories.

Skills provide the "how" (workflow instructions) while tools provide the "what" (capabilities). For example, a meal-planning skill might describe *how* to plan weekly meals using Hungryroot and AnyList tools, without those tools needing to know about each other.

### How Skills Work

Radar uses **progressive disclosure** to keep the system prompt lean:

1. At startup, Radar scans skill directories and parses only the frontmatter (`name`, `description`) from each `SKILL.md` -- roughly 50-100 tokens each.
2. An `<available_skills>` block is injected into the system prompt listing all discovered skills.
3. When a task matches a skill's description, the LLM activates it by calling the `use_skill` tool, which loads the full instructions.
4. The LLM then follows the skill's instructions, using existing tools (like `exec`, `read_file`, etc.) as needed.

### Skill Directory Layout

```
my-skill/
├── SKILL.md           # Required: YAML front matter + instructions
├── scripts/           # Optional: helper scripts
├── references/        # Optional: reference documents
└── assets/            # Optional: templates, data files
```

### SKILL.md Format

```markdown
---
name: my-skill
description: >-
  Brief description of what this skill does and when to use it.
compatibility: Any prerequisites or requirements.
metadata:
  author: yourname
  version: "1.0"
---

# My Skill

## Instructions

Step-by-step instructions for the LLM to follow...

## Tools Used

- **tool_name** -- How this tool is used in the workflow
```

The `name` field must match the directory name. The `description` is what the LLM sees in the system prompt to decide when to activate the skill.

### Configuration

Skills are discovered from `~/.local/share/radar/skills/` by default, plus any directories listed in `skills.dirs`:

```yaml
skills:
  enabled: true
  dirs:
    - ~/Code/my-skill
    - ~/skills
```

### Dual Integration Pattern

A directory can serve as both an **external tools directory** (via `tools.extra_dirs`) and an **Agent Skill** (via `SKILL.md`). The tools provide capabilities while the skill provides contextual knowledge about how to use them together.

For example, the `radar-meal-planning` repo works as both:
- Tools directory: provides `hungryroot`, `anylist`, and `lasership` tools
- Agent Skill: `SKILL.md` describes the meal planning workflow

```yaml
tools:
  extra_dirs:
    - ~/Code/radar-meal-planning

skills:
  dirs:
    - ~/Code/radar-meal-planning
```

### Creating a Skill

1. Create a directory for your skill.
2. Add a `SKILL.md` with YAML front matter (`name`, `description`) and markdown instructions.
3. Optionally add `scripts/`, `references/`, or `assets/` subdirectories.
4. Point Radar at it via `skills.dirs` in your config.

The skill appears automatically at the next startup (or config reload).

---

## Plugin System

Radar's plugin system supports two workflows: LLM-generated tools (sandboxed, single-tool) and human-authored plugins (full Python, multi-tool). Plugins can bundle multiple related tools, and human-authored plugins can use the full Python standard library.

### LLM-Generated Plugins

Ask Radar to create a tool:

```bash
radar ask "Create a tool that converts temperatures between Celsius and Fahrenheit"
```

The LLM will:

1. Generate Python code for the tool
2. Validate the code for safety (no dangerous imports or operations)
3. Run test cases in a sandbox
4. Save the plugin to `pending_review/` for your approval (by default)

LLM-generated plugins are always `sandbox` trust -- they run with restricted builtins and cannot import modules or access the filesystem.

### Installing Plugins from Directories

Human-authored plugins can be installed from a local directory using the CLI:

```bash
radar plugin install ~/my-plugins/git_tools
```

This copies the plugin to `pending_review/` for approval. After reviewing:

```bash
radar plugin approve git_tools
```

Or review in the web UI at `/plugins/review`.

### Multi-Tool Plugins

A single plugin can register multiple tools. Define them in `manifest.yaml`:

```yaml
name: git_tools
version: 1.0.0
description: Git repository operations
author: yourname
trust_level: local
tools:
  - name: git_status
    description: Show working tree status
    parameters:
      repo_path:
        type: string
        description: Path to the git repository
        optional: true
  - name: git_log
    description: Show recent commit log
    parameters:
      repo_path:
        type: string
        description: Path to the git repository
        optional: true
      count:
        type: integer
        description: Number of commits
        optional: true
```

Each tool corresponds to a function in `tool.py`:

```python
import subprocess

def git_status(repo_path: str = ".") -> str:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo_path, capture_output=True, text=True
    )
    return result.stdout or "Working tree clean"

def git_log(repo_path: str = ".", count: int = 10) -> str:
    result = subprocess.run(
        ["git", "log", f"-{count}", "--oneline"],
        cwd=repo_path, capture_output=True, text=True
    )
    return result.stdout
```

### Trust Levels

| Trust Level | Created By | Python Access | Imports | Auto-Approve |
|-------------|-----------|---------------|---------|--------------|
| `sandbox` | LLM | Restricted builtins only | Blocked | Configurable |
| `local` | Human | Full standard library | Allowed | Never (always requires human review) |

LLM-generated plugins are always `sandbox`. The `local` trust level is only for plugins installed via `radar plugin install` and always requires explicit human approval regardless of auto-approve settings.

### Plugin CLI Commands

```bash
# Install a plugin from a local directory
radar plugin install ~/my-plugins/git_tools

# List all plugins (with tool counts and trust levels)
radar plugin list

# Include pending plugins
radar plugin list --pending

# Approve a pending plugin
radar plugin approve git_tools
```

### Reviewing Plugins

In the web dashboard, navigate to `/plugins/review` to see pending plugins. Local-trust plugins show a prominent warning about their full Python access. Review the code carefully before approving.

Approved plugins are moved to `enabled/` and become available to the LLM immediately.

### Plugin Directory Structure

```
~/.local/share/radar/plugins/
  enabled/              # Active plugins (symlinks to available/)
  available/            # Approved plugins ready to use
  pending_review/       # Awaiting your approval
  failed/               # Rejected plugins
  versions/             # Version history for rollback
  errors/               # Error logs for debugging
```

### Debugging and Versioning

If a plugin fails validation or tests, use the `debug_tool` to iteratively fix it:

```bash
radar ask "Debug the temperature_converter tool"
```

Plugins are versioned automatically. Roll back to a previous version:

```bash
radar ask "Rollback temperature_converter to version 1"
```

### Configuration

```yaml
plugins:
  allow_llm_generated: true           # Enable plugin creation
  auto_approve: false                 # Require human review (recommended)
  auto_approve_if_tests_pass: false   # Auto-approve if tests pass
  max_debug_attempts: 5               # Max fix attempts
  test_timeout_seconds: 10            # Test execution timeout
  max_code_size_bytes: 10000          # Max generated code size
```

### Plugin Hooks

Plugins can also register hooks that intercept tool execution. See the [Hook System](#hook-system) section for details.

### Security

Plugin safety is enforced through multiple layers:

- **Trust levels** -- `sandbox` plugins run with restricted builtins; `local` plugins get full Python
- **AST validation** -- sandbox plugins are checked for dangerous imports and operations
- **Sandboxed execution** -- sandbox plugin tests run with restricted builtins
- **Human review** -- default requires manual approval via the web UI; local trust always requires it
- **Version history** -- roll back to a previous working version at any time

---

## Hook System

Hooks let you intercept tool execution, agent interactions, memory operations, and heartbeats -- without modifying Radar's source code. They provide a configurable policy layer on top of the built-in security checks in `radar/security.py`.

### Why Hooks?

The built-in security (path blocklists, command pattern blocking) is hardcoded and always active. Hooks let you add **your own policies** on top:

- Block specific command patterns (e.g., prevent `rm` commands)
- Restrict tools during certain hours (e.g., no `exec` at night)
- Audit-log every tool call
- Block prompt injection attempts before they reach the LLM
- Redact secrets from LLM responses
- Prevent memory poisoning by blocking suspicious memory content
- Filter potentially poisoned memories from search results
- Skip heartbeats under custom conditions
- Use plugin hooks for custom security checks

### Configuration

Add a `hooks` section to your `radar.yaml`:

```yaml
hooks:
  enabled: true    # Set to false to disable all hooks
  rules:
    # --- Tool rules ---
    - name: block_rm
      hook_point: pre_tool_call
      type: block_command_pattern
      patterns: ["rm "]
      tools: ["exec"]
      message: "rm commands are not allowed"
      priority: 10

    - name: nighttime_safety
      hook_point: filter_tools
      type: time_restrict
      start_hour: 22
      end_hour: 8
      tools: ["exec", "write_file"]

    - name: audit_log
      hook_point: post_tool_call
      type: log
      log_level: info

    # --- Agent rules ---
    - name: content_moderation
      hook_point: pre_agent_run
      type: block_message_pattern
      patterns: ["ignore previous instructions", "ignore all instructions"]
      message: "Message blocked by content filter"

    - name: redact_secrets
      hook_point: post_agent_run
      type: redact_response
      patterns: ["sk-[a-zA-Z0-9]+", "password:\\s*\\S+"]
      replacement: "[REDACTED]"

    # --- Memory rules (anti-poisoning) ---
    - name: anti_poisoning
      hook_point: pre_memory_store
      type: block_memory_pattern
      patterns: ["run:", "execute:", "curl ", "wget ", "sudo "]
      message: "Memory blocked: contains instruction-like content"

    - name: filter_suspicious_memories
      hook_point: post_memory_search
      type: filter_memory_pattern
      exclude_patterns: ["ignore previous", "system prompt"]

    # --- Heartbeat rules ---
    - name: heartbeat_audit
      hook_point: post_heartbeat
      type: log_heartbeat
      log_level: info
```

### Rule Types

**Pre-tool rules** (can block tool calls before they execute):

| Type | Description | Key Fields |
|------|-------------|------------|
| `block_command_pattern` | Block exec commands matching substring patterns | `patterns`, `tools`, `message` |
| `block_path_pattern` | Block file tools accessing paths under configured directories | `patterns`, `tools`, `message` |
| `block_tool` | Block specific tools entirely | `tools`, `message` |

**Filter rules** (modify which tools are visible to the LLM):

| Type | Description | Key Fields |
|------|-------------|------------|
| `time_restrict` | Remove tools during a time window | `start_hour`, `end_hour`, `tools` |
| `allowlist` | Only allow listed tools | `tools` |
| `denylist` | Remove listed tools | `tools` |

**Post-tool rules** (observe tool calls after they complete, cannot block):

| Type | Description | Key Fields |
|------|-------------|------------|
| `log` | Log tool execution | `log_level` |

**Pre-agent rules** (can block messages before they reach the LLM):

| Type | Description | Key Fields |
|------|-------------|------------|
| `block_message_pattern` | Block messages matching substring patterns (case-insensitive) | `patterns`, `message` |

**Post-agent rules** (transform LLM responses):

| Type | Description | Key Fields |
|------|-------------|------------|
| `redact_response` | Replace regex patterns in responses | `patterns`, `replacement` |
| `log_agent` | Log agent interactions | `log_level` |

**Pre-memory rules** (can block memory storage -- anti-poisoning):

| Type | Description | Key Fields |
|------|-------------|------------|
| `block_memory_pattern` | Block storing memories matching substring patterns | `patterns`, `message` |

**Post-memory rules** (filter memory search results):

| Type | Description | Key Fields |
|------|-------------|------------|
| `filter_memory_pattern` | Remove search results matching patterns | `exclude_patterns` |

**Post-heartbeat rules** (observe heartbeat execution):

| Type | Description | Key Fields |
|------|-------------|------------|
| `log_heartbeat` | Log heartbeat execution | `log_level` |

### Hook Priority

Rules with lower `priority` numbers run first. If you omit `priority`, config rules default to 50. For pre-tool and pre-agent hooks, the first rule that blocks stops execution -- later rules do not run.

### Plugin Hooks

Plugins with the `hook` capability can register Python hook functions for more complex logic (e.g., checking file ownership, querying external systems). These require `trust_level: local` for full Python access. See the Developer Guide for details on creating plugin hooks.

---

## Security

Radar runs locally with access to your file system and shell. Here is a summary of the security measures in place. See `docs/security.md` for the full security assessment.

### Path Blocklist

File tools (`read_file`, `write_file`) block access to sensitive paths:

- **Blocked for read and write:** `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config/gcloud`, `~/.password-store`
- **Blocked for write only:** `~/.bashrc`, `~/.zshrc`, `~/.profile`, `~/.config/autostart`

### Exec Safety

The `exec` tool blocks dangerous command patterns by default. You can adjust this with the `exec_mode` setting:

| Mode | Behavior |
|------|----------|
| `safe_only` | Only allow known safe commands (ls, cat, etc.) |
| `block_dangerous` | Block known dangerous patterns, allow others (default) |
| `allow_all` | No restrictions (use with caution) |

Blocked patterns in `block_dangerous` mode include: `rm -rf`, `mkfs`, `dd if=`, `curl`, `wget`, `sudo`, `crontab`, and others.

### Web UI Authentication

The web UI defaults to `127.0.0.1` (localhost only). When you bind to a non-localhost address, an auth token is required. See the [Authentication](#authentication) section under Web Dashboard for setup.

---

## Troubleshooting

### Ollama is not running

If you see connection errors, verify Ollama is running:

```bash
# Check if Ollama is reachable
curl http://localhost:11434/api/tags
```

If not, start it:

```bash
ollama serve
```

### Model does not support tool calling

If Radar sends questions but never uses tools, your model may not support tool calling. Use a model known to work:

```bash
ollama pull qwen3:latest
```

Then update your config:

```yaml
llm:
  model: qwen3:latest
```

### Port already in use

If `radar start` fails because port 8420 is in use:

```bash
# Check what is using the port
ss -tlnp | grep 8420

# Use a different port
radar start -p 9000
```

### Config file not found

Radar looks for `radar.yaml` in the current directory and `~/.config/radar/radar.yaml`. If neither exists, it uses defaults. Verify where Radar is looking:

```bash
# See the active config
radar config

# Force a specific config file
RADAR_CONFIG_PATH=~/my-radar.yaml radar config
```

### Stale PID file

If `radar start` says the daemon is already running but it is not:

```bash
# Check if the process actually exists
radar status

# If not running, remove the stale PID file
rm ~/.local/share/radar/radar.pid

# Now start again
radar start
```

### Embedding model not available

If semantic memory operations fail, make sure the embedding model is pulled:

```bash
ollama pull nomic-embed-text
```

Or switch to local embeddings that do not need Ollama:

```yaml
embedding:
  provider: local
  model: all-MiniLM-L6-v2
```

(Requires `pip install radar[local-embeddings]`)

### Daemon logs

When the daemon is running in the background, logs go to `~/.local/share/radar/radar.log`:

```bash
tail -f ~/.local/share/radar/radar.log
```

For more verbose output, run the daemon in the foreground:

```bash
radar start --foreground
```
