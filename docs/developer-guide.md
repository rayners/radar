# Radar Developer Guide

A comprehensive guide for developers who want to extend Radar with new tools,
plugins, web routes, or contribute to the core codebase.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Development Setup](#development-setup)
3. [Tutorial: Your First Radar Tool](#tutorial-your-first-radar-tool)
4. [Tutorial: Your First Radar Plugin](#tutorial-your-first-radar-plugin)
5. [Tutorial: Hook System](#tutorial-hook-system)
6. [Tutorial: User-Local Tools](#tutorial-user-local-tools)
7. [Tutorial: Agent Skills](#tutorial-agent-skills)
8. [Tutorial: Directory-Based Personalities](#tutorial-directory-based-personalities)
9. [Adding Config Sections](#adding-config-sections)
10. [Web Routes](#web-routes)
11. [Testing Patterns](#testing-patterns)
12. [Security Considerations](#security-considerations)
13. [Design Philosophy](#design-philosophy)

---

## Architecture Overview

### Module Map

```
radar/
├── agent.py            # Orchestrates context building + tool call loop
├── llm.py              # LLM client (Ollama native + OpenAI-compatible)
├── memory.py           # JSONL conversation storage (one file per conversation)
├── semantic.py         # Embedding client (Ollama, OpenAI, local, or none)
├── security.py         # Path blocklists and command safety checks
├── scheduler.py        # APScheduler heartbeat with quiet hours + event queue
├── scheduled_tasks.py  # Scheduled task CRUD (SQLite memory.db)
├── url_monitors.py     # URL monitor CRUD, fetching, diffing (SQLite memory.db)
├── watchers.py         # File system monitoring with watchdog
├── feedback.py         # User feedback collection + personality suggestions
├── logging.py          # Structured logging with stats tracking
├── cli.py              # Click-based CLI entry point
├── config/             # Configuration package
│   ├── __init__.py     # get_config() / reload_config() singleton
│   ├── schema.py       # @dataclass definitions (Config, LLMConfig, etc.)
│   ├── loader.py       # YAML loading + env var overrides
│   └── paths.py        # DataPaths (centralized data directory management)
├── tools/              # Auto-discovered tool modules
│   ├── __init__.py     # @tool decorator, registry, execute_tool()
│   ├── weather.py      # Weather via Open-Meteo API
│   ├── notify.py       # Push notifications via ntfy.sh
│   ├── github.py       # GitHub queries via gh CLI
│   ├── exec.py         # Shell command execution
│   ├── read_file.py    # File reading
│   ├── write_file.py   # File writing
│   ├── skills.py       # use_skill + load_context tools
│   └── ...             # Add a .py file here and it is auto-discovered
├── skills.py           # Agent Skills discovery, loading, and prompt building
├── hooks.py            # Hook system (pre/post tool call, filter tools)
├── hooks_builtin.py    # Config-driven hook builders (block patterns, time restrict, etc.)
├── plugins/            # Dynamic plugin system
│   ├── __init__.py     # get_plugin_loader() singleton
│   ├── models.py       # PluginManifest, ToolDefinition, TestCase, ToolError, Plugin
│   ├── validator.py    # AST-based code validation (CodeValidator)
│   ├── runner.py       # Sandboxed test execution (TestRunner)
│   ├── versions.py     # Version history management
│   ├── hooks.py        # Plugin hook loading (load/unload plugin hooks)
│   └── loader.py       # Plugin lifecycle (PluginLoader)
└── web/                # FastAPI + HTMX web dashboard
    ├── __init__.py     # FastAPI app, auth middleware, common context
    ├── routes/         # Route modules (one per domain)
    │   ├── dashboard.py
    │   ├── chat.py
    │   ├── tasks.py
    │   ├── memory.py
    │   ├── config.py
    │   ├── logs.py
    │   ├── personalities.py
    │   ├── plugins.py
    │   ├── auth.py
    │   └── health.py
    ├── static/         # CSS, JS
    └── templates/      # Jinja2 HTML templates
```

### Data Flow

```
User Input (CLI or Web)
       │
       ▼
   agent.py          ← Builds system prompt (personality + memory notes)
       │                Loads conversation history from JSONL
       ▼
    llm.py           ← Sends messages + tool schemas to LLM
       │                Always stream: false
       │
       ├──── Tool calls? ──► tools/__init__.py  ← execute_tool(name, args)
       │         │                                  Runs pre-tool hooks (can block)
       │         │                                  Dispatches to registered function
       │         │                                  Runs post-tool hooks (observe)
       │         │                                  Returns string result
       │         ▼
       │    Tool results added to messages
       │    Loop back to LLM (up to max_tool_iterations)
       │
       ▼
  Final response stored in memory.py (JSONL)
  Returned to user
```

The tool call loop is in `radar/llm.py` (`_chat_ollama` / `_chat_openai`).
It is roughly 50 lines of code -- no frameworks, no abstractions.

### Key Design Decisions

- **`stream: false` always** -- Ollama's streaming mode breaks tool calling.
  This is non-negotiable. Every LLM request uses `"stream": False`.

- **No frameworks** -- No LangChain, no agent frameworks. The tool call loop
  is plain Python: send messages, check for `tool_calls`, execute, repeat.

- **JSONL conversations** -- Each conversation is one `.jsonl` file in
  `~/.local/share/radar/conversations/`. Simple, human-readable, appendable.

- **SQLite for everything else** -- Semantic memory (embeddings), scheduled
  tasks, and feedback all live in `~/.local/share/radar/memory.db`.

- **Tools are functions** -- A decorated Python function that takes typed
  parameters and returns a string. The registry generates the OpenAI tool
  schema from the decorator metadata.

- **Wrap CLIs, don't import libraries** -- Prefer wrapping existing CLI
  tools (e.g., `gh`, `khal`) via subprocess over pulling in third-party
  libraries. The CLI already handles the hard parts; we just parse its output.

- **SQLite datetime format** -- Use `strftime("%Y-%m-%d %H:%M:%S")` (space
  separator), NOT `.isoformat()` (T separator). ISO `T` breaks SQLite
  `datetime()` comparisons.

---

## Development Setup

### Prerequisites

- Python 3.11+
- An Ollama instance (local or remote) with a tool-calling model
- Recommended models: `qwen3:latest`, `llama3.1:8b`, `glm-4.7-flash`

### Clone and Install

```bash
git clone https://github.com/yourusername/radar.git
cd radar

python3 -m venv .venv
source .venv/bin/activate

pip install -e .
```

Always activate the virtualenv before working:

```bash
source .venv/bin/activate
```

### Verify Installation

```bash
# Run the test suite
python -m pytest tests/ -v

# Check the CLI
radar config

# One-shot question (requires Ollama)
radar ask "What tools do you have available?"
```

### Code Conventions

- Tools are registered with the `@tool` decorator in `radar/tools/`.
- Tools always return strings.
- Config file: `radar.yaml` in the current directory or `~/.config/radar/radar.yaml`.
- Environment variables override config values (see `radar/config/loader.py`).
- Every new feature or bug fix must include tests.

---

## Tutorial: Your First Radar Tool

This tutorial walks through creating a simple tool from scratch, testing it,
and understanding how auto-discovery works.

### Step 1: Create the Tool File

Create `radar/tools/hello.py`:

```python
# radar/tools/hello.py
from radar.tools import tool


@tool(
    name="hello",
    description="Greet someone by name",
    parameters={
        "name": {
            "type": "string",
            "description": "The name of the person to greet",
        },
    },
)
def hello(name: str) -> str:
    """Say hello to someone."""
    return f"Hello, {name}! Welcome to Radar."
```

That is the entire tool. Let's break down what happens:

1. The `@tool` decorator registers the function in the global `_registry`
   dict in `radar/tools/__init__.py`.

2. The `parameters` dict uses JSON Schema format. Each key is a parameter
   name, and the value describes its type and purpose.

3. The `name` in the decorator becomes the tool name the LLM sees and calls.

4. The function must return a `str`. The return value is sent back to the
   LLM as the tool result.

### Step 2: Understand Auto-Discovery

You do not need to import your tool anywhere. The `_discover_tools()` function
in `radar/tools/__init__.py` uses `pkgutil.iter_modules` to find and import
every `.py` file in the `radar/tools/` package at import time:

```python
def _discover_tools() -> set[str]:
    """Auto-discover and import tool modules from this package."""
    import importlib
    import pkgutil

    snapshot = set(_registry.keys())
    for _finder, module_name, _is_pkg in pkgutil.iter_modules(__path__):
        if module_name.startswith("_"):
            continue
        importlib.import_module(f"radar.tools.{module_name}")
    return set(_registry.keys()) - snapshot
```

Files starting with `_` are skipped. Everything else is imported, which
triggers the `@tool` decorator and registers the function.

### Step 3: Test It Directly

You can test the tool function without any LLM involvement:

```bash
python -c "from radar.tools.hello import hello; print(hello('World'))"
# Output: Hello, World! Welcome to Radar.
```

### Step 4: Test It Through the Agent

With Ollama running:

```bash
radar ask "Say hello to World"
```

The LLM will see the `hello` tool in its available tools, call it with
`{"name": "World"}`, and relay the result back.

### Step 5: Write Tests

Create `tests/test_hello.py`:

```python
"""Tests for the hello tool."""

from radar.tools.hello import hello


def test_hello_basic():
    """Test basic greeting."""
    result = hello("World")
    assert result == "Hello, World! Welcome to Radar."


def test_hello_empty_name():
    """Test with empty name."""
    result = hello("")
    assert "Hello, !" in result
```

Run the tests:

```bash
python -m pytest tests/test_hello.py -v
```

### Step 6: Optional Parameters

To make a parameter optional, add `"optional": True`:

```python
@tool(
    name="hello",
    description="Greet someone by name",
    parameters={
        "name": {
            "type": "string",
            "description": "The name of the person to greet",
        },
        "style": {
            "type": "string",
            "description": "Greeting style: formal or casual",
            "optional": True,
        },
    },
)
def hello(name: str, style: str | None = None) -> str:
    if style == "formal":
        return f"Good day, {name}. How may I assist you?"
    return f"Hello, {name}! Welcome to Radar."
```

Optional parameters are excluded from the `required` list in the generated
JSON Schema. The decorator handles this automatically by checking for
`v.get("optional", False)` in each parameter definition.

### A Real-World Example: The Notify Tool

For reference, here is the actual `radar/tools/notify.py` -- a complete,
production tool:

```python
"""Notification tool using ntfy.sh."""

import httpx

from radar.config import get_config
from radar.tools import tool


@tool(
    name="notify",
    description="Send a push notification via ntfy.sh. Requires ntfy topic to be configured.",
    parameters={
        "message": {
            "type": "string",
            "description": "The notification message body",
        },
        "title": {
            "type": "string",
            "description": "Optional notification title",
            "optional": True,
        },
        "priority": {
            "type": "string",
            "description": "Priority level: min, low, default, high, urgent",
            "optional": True,
        },
    },
)
def notify(message: str, title: str | None = None, priority: str | None = None) -> str:
    """Send a notification via ntfy."""
    config = get_config()

    if not config.notifications.topic:
        return "Error: ntfy topic not configured. Set notifications.topic in radar.yaml"

    url = f"{config.notifications.url.rstrip('/')}/{config.notifications.topic}"

    headers = {}
    if title:
        headers["Title"] = title
    if priority:
        headers["Priority"] = priority

    try:
        response = httpx.post(url, content=message, headers=headers, timeout=10)
        response.raise_for_status()
        return "Notification sent successfully"
    except httpx.TimeoutException:
        return "Error: Notification request timed out"
    except httpx.HTTPStatusError as e:
        return f"Error: ntfy returned status {e.response.status_code}"
    except Exception as e:
        return f"Error sending notification: {e}"
```

Key patterns to follow:
- Import config with `from radar.config import get_config` and call it inside
  the function (not at module level).
- Return error strings, don't raise exceptions. The LLM receives whatever
  string you return.
- Handle network errors gracefully.

---

## Tutorial: Your First Radar Plugin

Plugins are dynamically generated tools -- created by the LLM (or manually)
and managed through a review workflow. They differ from built-in tools in
several ways:

- Plugins are created at runtime, not bundled in the package.
- Plugin code is validated by AST analysis for safety.
- Plugin tests run in a sandboxed environment with restricted builtins.
- Plugins go through a review pipeline: pending -> approved -> enabled.

### Plugin Directory Structure

All plugins live under `~/.local/share/radar/plugins/`:

```
plugins/
├── enabled/            # Active plugins (symlinks to available/)
├── available/          # Approved plugins ready to use
├── pending_review/     # Awaiting human approval
├── failed/             # Rejected plugins
├── versions/           # Version history for rollback
└── errors/             # Error logs for debugging
```

### Step 1: Understand the Plugin Manifest

Every plugin has a `manifest.yaml` file (`radar/plugins/models.py:PluginManifest`):

```yaml
name: reverse_string
version: "1.0.0"
description: "Reverse a string"
author: llm-generated
trust_level: sandbox
permissions: []
created_at: "2025-01-15T10:00:00"
capabilities:
  - tool           # Always present for basic plugins
  # - widget       # Adds a dashboard widget
  # - personality  # Bundles personality files
widget: null       # Widget config (see advanced section)
personalities: []  # Bundled personality filenames
scripts: []        # Helper script filenames
```

The `capabilities` field controls what the plugin provides:
- `tool` -- registers a callable tool (the default)
- `widget` -- renders a Jinja2 template on the dashboard
- `personality` -- bundles personality `.md` files
- `prompt_variables` -- contributes dynamic values to personality templates
- `hook` -- registers hook functions that intercept tool execution

### Step 2: Create a Plugin Manually

Create the plugin directory and files:

```bash
mkdir -p ~/.local/share/radar/plugins/pending_review/reverse_string
```

Create `tool.py` -- the actual tool code:

```python
def reverse_string(text):
    """Reverse a string."""
    return text[::-1]
```

Create `manifest.yaml`:

```yaml
name: reverse_string
version: "1.0.0"
description: "Reverse a string"
author: manual
trust_level: sandbox
capabilities:
  - tool
```

Create `schema.yaml` -- the tool's parameter schema:

```yaml
name: reverse_string
description: "Reverse a string"
parameters:
  text:
    type: string
    description: "The string to reverse"
```

Create `tests.yaml` -- test cases:

```yaml
- name: basic_reverse
  input_args:
    text: "hello"
  expected_output: "olleh"

- name: palindrome
  input_args:
    text: "racecar"
  expected_output: "racecar"

- name: empty_string
  input_args:
    text: ""
  expected_output: ""
```

### Step 3: Understand Code Validation

Before any plugin runs, its code passes through `CodeValidator`
(`radar/plugins/validator.py`). The validator uses Python's `ast` module
to check for dangerous patterns:

**Forbidden imports** (blocked at AST level):
`os`, `subprocess`, `sys`, `socket`, `shutil`, `multiprocessing`, `threading`,
`ctypes`, `marshal`

**Forbidden function calls** (blocked at AST level):
`eval`, `exec`, `compile`, `__import__`, `open`, `globals`, `locals`,
`getattr`, `setattr`, `delattr`

**Forbidden attribute access:**
`__code__`, `__globals__`, `__builtins__`, `__subclasses__`, `__bases__`,
`__mro__`

The validator also checks that the code defines at least one function.

### Step 4: Understand the Test Sandbox

Plugin tests run in `TestRunner` (`radar/plugins/runner.py`) with a restricted
namespace. Only these builtins are available:

`True`, `False`, `None`, `abs`, `all`, `any`, `bool`, `chr`, `dict`,
`divmod`, `enumerate`, `filter`, `float`, `format`, `frozenset`, `hash`,
`hex`, `int`, `isinstance`, `issubclass`, `iter`, `len`, `list`, `map`,
`max`, `min`, `next`, `oct`, `ord`, `pow`, `print`, `range`, `repr`,
`reversed`, `round`, `set`, `slice`, `sorted`, `str`, `sum`, `tuple`,
`type`, `zip`

**What is NOT available in the sandbox:**
- `ValueError`, `TypeError`, and other exception classes
- `open`, `import`, `exec`, `eval`
- Any module imports

This means plugin tests cannot catch specific exception types. To test error
handling, use operations that trigger built-in errors (e.g., `1/0` for
`ZeroDivisionError`).

### Step 5: Plugin Lifecycle via the LLM

The LLM can create plugins using the `create_tool` meta-tool. When a user
says "Create a tool that reverses strings", the LLM:

1. Calls `create_tool` with name, description, parameters, code, and tests.
2. `PluginLoader.create_plugin()` validates the code and runs tests.
3. If tests pass and auto-approve is off: plugin goes to `pending_review/`.
4. If tests fail: plugin goes to `pending_review/` with error details saved.
5. A human reviews at `/plugins/review` in the web UI.
6. On approval: plugin moves to `available/`, a symlink is created in
   `enabled/`, and the tool is registered via `register_dynamic_tool()`.

### Step 6: Approve via Web UI or Programmatically

**Web UI:** Navigate to `/plugins/review`, review the code, and click Approve.

**Programmatically:**

```python
from radar.plugins import get_plugin_loader

loader = get_plugin_loader()
success, message = loader.approve_plugin("reverse_string")
# Moves from pending_review/ to available/, creates symlink in enabled/
```

### Step 7: Version History and Rollback

Every code update is versioned automatically. To rollback:

```python
loader = get_plugin_loader()

# Rollback to a specific version
success, message = loader.rollback_plugin("reverse_string", "v1")
```

### Advanced: Dashboard Widget

A plugin with `widget` capability can render HTML on the dashboard.

Add to `manifest.yaml`:

```yaml
capabilities:
  - tool
  - widget
widget:
  title: "Reverse String"
  template: widget.html
  position: default        # "default", "sidebar", etc.
  refresh_interval: 60     # seconds (0 = no auto-refresh)
```

Create `widget.html` (Jinja2 template, rendered in a sandboxed environment):

```html
<div class="widget-body">
  <p>Plugin: {{ plugin_name }}</p>
  <p>Reverse any string using the reverse_string tool.</p>
</div>
```

Widget templates are rendered through `jinja2.sandbox.SandboxedEnvironment`
for security.

### Advanced: Bundled Personality

A plugin can bundle personality files by adding a `personalities/` subdirectory:

```
reverse_string/
├── manifest.yaml
├── tool.py
├── tests.yaml
├── schema.yaml
└── personalities/
    └── wordsmith.md
```

Add to `manifest.yaml`:

```yaml
capabilities:
  - tool
  - personality
personalities:
  - wordsmith.md
```

The bundled personality will be discoverable via `load_personality()`.

### Advanced: Helper Scripts

Plugins can include validated helper scripts in a `scripts/` subdirectory.
These scripts are validated by `CodeValidator` and executed in the same
restricted namespace as the main tool code. Functions defined in helper
scripts are injected into the tool's namespace via `extra_namespace`.

```
reverse_string/
├── manifest.yaml
├── tool.py
├── scripts/
│   └── utils.py
```

`scripts/utils.py`:

```python
def clean_text(text):
    """Strip whitespace and lowercase."""
    return text.strip().lower()
```

`tool.py` can then call `clean_text()` as if it were defined locally:

```python
def reverse_string(text):
    cleaned = clean_text(text)  # Available from helper script
    return cleaned[::-1]
```

### Multi-Tool Plugins

A single plugin can register multiple tools by listing them in `manifest.yaml`.
This is useful for bundling related operations together (e.g., git operations,
file format converters, API clients).

**Manifest with multiple tools:**

```yaml
# git_tools/manifest.yaml
name: git_tools
version: 1.0.0
description: Git repository operations
author: rayners
trust_level: local
capabilities:
  - tool
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

**Code with matching functions:**

```python
# git_tools/tool.py
import subprocess

def git_status(repo_path: str = ".") -> str:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo_path, capture_output=True, text=True
    )
    if result.returncode != 0:
        return f"Error: {result.stderr}"
    return result.stdout or "Working tree clean"

def git_log(repo_path: str = ".", count: int = 10) -> str:
    result = subprocess.run(
        ["git", "log", f"-{count}", "--oneline"],
        cwd=repo_path, capture_output=True, text=True
    )
    if result.returncode != 0:
        return f"Error: {result.stderr}"
    return result.stdout
```

Each function name in `tool.py` must match the `name` field of a tool in the
manifest. When the plugin is loaded, all matching functions are registered as
separate tools in the tool registry.

**Backward compatibility:** Plugins without a `tools` list in the manifest
fall back to reading `schema.yaml` and registering a single tool (the
existing behavior). All existing single-tool plugins continue to work.

### Local Trust Plugins

Plugins have a `trust_level` field that controls how their code is loaded:

| Trust Level | Loading | Capabilities | Created By |
|-------------|---------|-------------|------------|
| `sandbox` | Restricted builtins, no imports | String manipulation, math, formatting | LLM or manual |
| `local` | Full Python via `importlib` | Imports, filesystem, network, subprocess | Human only |

**When to use `local` trust:**
- Your plugin needs to import Python packages (`subprocess`, `httpx`, etc.)
- Your plugin wraps a CLI tool or accesses the filesystem
- Your plugin calls external APIs

**Security rules for `local` trust:**
- The `create_tool` meta-tool always forces `trust_level: sandbox` -- the LLM
  cannot create local trust plugins
- Local trust plugins are **never** auto-approved, regardless of config settings
- The review page shows a prominent warning for local trust plugins
- Human review is the security gate (AST validation is skipped for local trust)

**How local trust loading works:** Instead of running code in a restricted
sandbox, the loader uses `importlib.util.spec_from_file_location` to load
`tool.py` as a standard Python module. Functions are extracted by name
(matching the `tools` list in the manifest) and registered directly via
`register_local_tool()`.

**Installing a local trust plugin from CLI:**

```bash
# Install from a local directory
radar plugin install ~/my-plugins/git_tools
# -> Plugin 'git_tools' (local trust) installed to pending review.
# -> Review at http://localhost:8420/plugins/review
# -> Or run: radar plugin approve git_tools

# Approve after reviewing the code
radar plugin approve git_tools
# -> Plugin 'git_tools' approved and enabled (2 tools: git_status, git_log)

# List all plugins
radar plugin list
# NAME         VERSION  TRUST    TOOLS  STATUS   ENABLED
# git_tools    1.0.0    local    2      approved yes
```

### Advanced: Prompt Variables

Plugins with `prompt_variables` capability contribute dynamic values to personality
templates. This lets plugins inject context into every LLM conversation without
requiring the user to modify their personality files.

**Manifest with prompt variables:**

```yaml
# system_context/manifest.yaml
name: system_context
version: "1.0.0"
description: "Adds system context to personality prompts"
author: rayners
trust_level: local
capabilities:
  - prompt_variables
prompt_variables:
  - name: hostname
    description: "Local machine hostname"
  - name: os_name
    description: "Operating system name"
```

**Code with matching functions:**

```python
# system_context/tool.py
import platform
import socket

def hostname() -> str:
    return socket.gethostname()

def os_name() -> str:
    return platform.system()
```

Each function name must match a `name` in `prompt_variables`. Functions take no
arguments and return a string. Functions are called on every prompt build (not
cached at startup), so they always return current values.

**Usage in personality files:**

```markdown
# My Assistant

You are running on {{ hostname }} ({{ os_name }}).
Current time: {{ current_time }}
Today is {{ day_of_week }}, {{ current_date }}.
```

Built-in variables (`current_time`, `current_date`, `day_of_week`) take
precedence over plugin variables with the same name. Unknown variables render
as empty strings.

**Combining with other capabilities:** A plugin can have both `tool` and
`prompt_variables` capabilities:

```yaml
capabilities:
  - tool
  - prompt_variables
tools:
  - name: system_info
    description: Get system information
    parameters: {}
prompt_variables:
  - name: hostname
    description: Machine hostname
```

### Advanced: Plugin Hooks

Plugins with the `hook` capability can intercept tool execution. This is useful
for adding custom security policies, audit logging, or conditional tool filtering
without modifying Radar's source code.

**Manifest with hooks:**

```yaml
# security_hooks/manifest.yaml
name: security_hooks
version: "1.0.0"
description: "Custom security hooks"
trust_level: local
capabilities:
  - hook
hooks:
  - hook_point: pre_tool_call
    function: check_file_ownership
    priority: 20
    description: "Block writes to files not owned by user"
```

**Code with matching functions:**

```python
# security_hooks/tool.py
import os
from pathlib import Path
from radar.hooks import HookResult

def check_file_ownership(tool_name, arguments):
    if tool_name != "write_file":
        return HookResult()
    path = Path(arguments.get("path", "")).expanduser().resolve()
    if path.exists() and path.stat().st_uid != os.getuid():
        return HookResult(blocked=True, message=f"Cannot write to '{path}': not owned by you")
    return HookResult()
```

Each function name must match a `function` in the `hooks` list. Hook functions
receive different arguments depending on the hook point:

| Hook Point | Signature | Return |
|---|---|---|
| `pre_tool_call` | `(tool_name, arguments)` | `HookResult` (blocked, message) |
| `post_tool_call` | `(tool_name, arguments, result, success)` | `None` |
| `filter_tools` | `(tools)` | `list[dict]` (filtered tool list) |
| `pre_agent_run` | `(user_message, conversation_id)` | `HookResult` (blocked, message) |
| `post_agent_run` | `(user_message, response, conversation_id)` | `str` or `None` |
| `pre_memory_store` | `(content, source)` | `HookResult` (blocked, message) |
| `post_memory_search` | `(query, results)` | `list[dict]` (filtered results) |
| `pre_heartbeat` | `(event_count)` | `HookResult` (blocked, message) |
| `post_heartbeat` | `(event_count, success, error)` | `None` |

**Trust levels for hooks:** Sandbox hooks get `HookResult` injected into their
namespace so they can return blocks. Local-trust hooks load via `importlib`
with full Python access and can import `HookResult` directly.

**Hook loading/unloading:** When a plugin with the `hook` capability is
registered (via `_register_plugin()`), its hooks are loaded automatically.
When unregistered, its hooks are removed via `unload_plugin_hooks()`.

### Plugin Configuration

In `radar.yaml`:

```yaml
plugins:
  allow_llm_generated: true        # Enable LLM tool creation
  auto_approve: false              # Require human review (safe default)
  auto_approve_if_tests_pass: false  # Auto-approve if tests pass
  max_debug_attempts: 5            # Give up after N fix attempts
  test_timeout_seconds: 10         # Timeout for running tests
  max_code_size_bytes: 10000       # Max code size for generated plugins
```

---

## Tutorial: Hook System

Hooks provide a configurable layer for intercepting tool execution and filtering
tool availability. They sit on top of the hardcoded security in `radar/security.py`
and run **before** the tool function is even called.

### Hook Points

| Hook Point | Fires When | Can Block? |
|---|---|---|
| `pre_tool_call` | Before `execute_tool()` runs the tool function | Yes |
| `post_tool_call` | After `execute_tool()` completes | No (observe only) |
| `filter_tools` | When `get_tools_schema()` builds the tool list | N/A (transforms list) |
| `pre_agent_run` | Before `agent.run()` / `agent.ask()` calls the LLM | Yes |
| `post_agent_run` | After `agent.run()` / `agent.ask()` returns | Transform (can modify response) |
| `pre_memory_store` | Before `semantic.store_memory()` embeds + inserts | Yes |
| `post_memory_search` | After `semantic.search_memories()` computes results | Transform (can filter/rerank) |
| `pre_heartbeat` | Before `scheduler._heartbeat_tick()` processes | Yes |
| `post_heartbeat` | After `scheduler._heartbeat_tick()` completes | No (observe only) |

### Two Sources of Hooks

**1. Config-driven rules** -- Simple YAML rules in `radar.yaml`, no Python needed:

```yaml
hooks:
  enabled: true
  rules:
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
```

Config rule types:
- `block_command_pattern` -- Block exec commands matching substring patterns
- `block_path_pattern` -- Block file tools accessing paths under configured directories
- `block_tool` -- Block specific tools entirely
- `time_restrict` -- Remove tools during a time window
- `allowlist` / `denylist` -- Static tool filtering
- `log` -- Log tool execution
- `block_message_pattern` -- Block messages matching substring patterns (pre-agent)
- `redact_response` -- Replace regex patterns in LLM responses (post-agent)
- `log_agent` -- Log agent interactions (post-agent)
- `block_memory_pattern` -- Block storing memories matching patterns (pre-memory)
- `filter_memory_pattern` -- Remove search results matching patterns (post-memory)
- `log_heartbeat` -- Log heartbeat execution (post-heartbeat)

**2. Plugin hooks** -- Python functions from plugins with `hook` capability.
See [Advanced: Plugin Hooks](#advanced-plugin-hooks) in the plugin tutorial.

### Core Module: `radar/hooks.py`

Key types:
- `HookPoint` enum: `PRE_TOOL_CALL`, `POST_TOOL_CALL`, `FILTER_TOOLS`,
  `PRE_AGENT_RUN`, `POST_AGENT_RUN`, `PRE_MEMORY_STORE`, `POST_MEMORY_SEARCH`,
  `PRE_HEARTBEAT`, `POST_HEARTBEAT`
- `HookResult` dataclass: `blocked: bool`, `message: str`
- `HookRegistration` dataclass: `name`, `hook_point`, `callback`, `priority`,
  `source`, `description`

Key functions:
- `register_hook()` / `unregister_hook()` -- Add/remove hooks
- `run_pre_tool_hooks()` -- Returns `HookResult` (short-circuits on first block)
- `run_post_tool_hooks()` -- Fire-and-forget observation
- `run_filter_tools_hooks()` -- Chain-filters the tool list
- `run_pre_agent_hooks()` -- Returns `HookResult` (short-circuits on first block)
- `run_post_agent_hooks()` -- Chain-transforms the response string
- `run_pre_memory_store_hooks()` -- Returns `HookResult` (short-circuits on first block)
- `run_post_memory_search_hooks()` -- Chain-filters/reranks search results
- `run_pre_heartbeat_hooks()` -- Returns `HookResult` (short-circuits on first block)
- `run_post_heartbeat_hooks()` -- Fire-and-forget observation
- `clear_all_hooks()` -- Reset (useful for testing)
- `list_hooks()` -- Introspection

### Design Details

- **Fast path**: `run_*` functions check `if not hooks: return` before iterating
  (zero overhead when no hooks are registered)
- **Priority ordering**: Lower numbers run first. Config hooks default to 50,
  plugin hooks to 100
- **Error isolation**: Failing hooks are logged and skipped, never crash the tool
- **Lazy imports**: Hook functions in `execute_tool()` and `get_tools_schema()`
  use lazy imports from `radar.hooks` to avoid circular imports

### Testing Hooks

Use the `clear_all_hooks()` function in an autouse fixture for test isolation:

```python
import pytest
from radar.hooks import clear_all_hooks

@pytest.fixture(autouse=True)
def clean_hooks():
    clear_all_hooks()
    yield
    clear_all_hooks()
```

When testing config-driven hooks, patch `radar.config.get_config` (the source
module), not `radar.hooks_builtin.get_config`, because `get_config` is imported
lazily inside `load_config_hooks()`.

When testing the `log` callback, patch `radar.logging.log` (the source module),
not `radar.hooks_builtin.log`.

---

## Tutorial: User-Local Tools

User-local tools live outside the Radar package but follow the exact same
`@tool` pattern as built-in tools. They are loaded lazily on first call
to `get_tools_schema()`.

### Default Directory

Place `.py` files in `~/.local/share/radar/tools/`:

```python
# ~/.local/share/radar/tools/greet.py
from radar.tools import tool


@tool(
    name="greet",
    description="Greet someone in their language",
    parameters={
        "name": {"type": "string", "description": "Person's name"},
        "language": {
            "type": "string",
            "description": "Language: en, es, fr, de",
            "optional": True,
        },
    },
)
def greet(name: str, language: str = "en") -> str:
    greetings = {
        "en": "Hello",
        "es": "Hola",
        "fr": "Bonjour",
        "de": "Hallo",
    }
    greeting = greetings.get(language, "Hello")
    return f"{greeting}, {name}!"
```

### Extra Directories

Configure additional directories in `radar.yaml`:

```yaml
tools:
  extra_dirs:
    - ~/my-radar-tools
    - /opt/shared-radar-tools
```

### How Loading Works

External tools are loaded by `ensure_external_tools_loaded()` in
`radar/tools/__init__.py`. This function:

1. Is called lazily the first time `get_tools_schema()` is invoked.
2. Scans the default tools directory (`~/.local/share/radar/tools/`).
3. Scans any directories listed in `tools.extra_dirs`.
4. Uses `importlib.util.spec_from_file_location` to load each `.py` file.
5. Tracks external tools separately from built-in tools in the `_external_tools` set.

Files starting with `_` are skipped, just like built-in tools.

### Differences from Built-in Tools

| Aspect | Built-in | User-Local |
|--------|----------|------------|
| Location | `radar/tools/` | `~/.local/share/radar/tools/` or `extra_dirs` |
| Loading | At package import time | Lazily on first `get_tools_schema()` call |
| Tracking | `_static_tools` set | `_external_tools` set |
| Updates | Requires package reinstall | Edit file and restart |

---

## Tutorial: Agent Skills

Agent Skills are packaged bundles of procedural knowledge following the
[Agent Skills](https://agentskills.io/) open standard. This tutorial covers
the internals of how Radar discovers, loads, and activates skills.

### Core Module: `radar/skills.py`

Key types and functions:

- `SkillInfo` dataclass: `name`, `description`, `path`, `license`,
  `compatibility`, `metadata`
- `discover_skills()` -- Scan skill directories, parse SKILL.md frontmatter,
  return cached list of `SkillInfo`
- `load_skill(name)` -- Load the full SKILL.md body content (frontmatter stripped)
- `get_skill_resource_path(name, resource)` -- Resolve a resource path within
  a skill directory (with path traversal protection)
- `build_skills_prompt_section(skills)` -- Build the `<available_skills>` XML
  block for the system prompt
- `invalidate_skills_cache()` -- Clear the cache (called on config hot-reload)
- `_list_skill_resources(skill)` -- List all files in scripts/, references/,
  assets/ subdirectories

### Discovery Flow

1. `discover_skills()` checks if skills are enabled via config
2. Scans default directory (`~/.local/share/radar/skills/`)
3. Scans additional directories from `config.skills.dirs`
4. For each directory, looks for `SKILL.md` and parses its YAML frontmatter
5. Validates: frontmatter exists, `name` field present, name matches directory name
6. If a configured directory itself contains `SKILL.md` (not just subdirectories),
   it's treated as a skill
7. Results are cached until `invalidate_skills_cache()` is called

### Progressive Disclosure

Skills use progressive disclosure to minimize system prompt size:

1. **Startup**: Only frontmatter is parsed (~50-100 tokens per skill)
2. **System prompt**: An `<available_skills>` XML block lists skill names and
   descriptions
3. **Activation**: The LLM calls `use_skill` to load full instructions
4. **Resources**: The LLM can read scripts/references/assets via existing
   file tools

### Tools: `radar/tools/skills.py`

Two tools are provided:

- `use_skill(name)` -- Loads and returns a skill's full SKILL.md body plus a
  list of available resource files. Returns an error with available skill names
  if the skill is not found.
- `load_context(name)` -- Loads a context document from the active
  personality's `context/` directory (see Directory-Based Personalities below).

### System Prompt Integration

In `radar/agent.py`, `_build_system_prompt()` calls `discover_skills()` and
appends the skills prompt section after the personality template:

```python
from radar.skills import discover_skills, build_skills_prompt_section
skills = discover_skills()
if skills:
    prompt += "\n\n" + build_skills_prompt_section(skills)
```

### Config Hot-Reload

When the config file changes, `radar/scheduler.py`'s `_check_config_reload()`
calls `invalidate_skills_cache()` so skills are re-discovered with updated
`skills.dirs`.

### Creating a SKILL.md

The frontmatter must include `name` (matching the directory name) and
`description`. Optional fields: `license`, `compatibility`, `metadata`.

```yaml
---
name: my-skill
description: >-
  What this skill does and when to use it.
compatibility: Requirements and prerequisites.
metadata:
  author: yourname
  version: "1.0"
---

# My Skill

Instructions for the LLM...
```

### Testing Skills

See `tests/test_skills.py` for patterns. Key fixtures:

- `skills_dir` -- Creates and returns the skills directory within
  `isolated_data_dir`
- `clear_skills_cache` -- Autouse fixture that invalidates the skills cache
  before and after each test

Test patterns:

```python
def test_discover_skills(skills_dir):
    _create_skill(skills_dir, "my-skill", "Test skill")
    skills = discover_skills()
    assert len(skills) == 1
    assert skills[0].name == "my-skill"

def test_use_skill_tool(skills_dir):
    _create_skill(skills_dir, "usable", "Usable skill",
                  body="# Instructions\n\nDo things.")
    from radar.tools.skills import use_skill
    result = use_skill("usable")
    assert "# Instructions" in result
```

---

## Tutorial: Directory-Based Personalities

Directory-based personalities extend the flat `.md` format with context
documents, scripts, and assets. This tutorial covers the implementation details.

### Resolution Order

`load_personality()` in `radar/agent.py` checks in this order:

1. Explicit file path (if the name looks like a path)
2. `{personalities_dir}/{name}/PERSONALITY.md` (directory-based)
3. `{personalities_dir}/{name}.md` (flat file)
4. Plugin-bundled personalities
5. `DEFAULT_PERSONALITY` fallback

### Context Documents: Progressive Disclosure

Context documents in `context/` use the same progressive disclosure pattern
as skills:

1. `_get_personality_context_metadata(name)` parses YAML frontmatter from
   each `context/*.md` file, extracting `(name, description)` pairs
2. `_build_system_prompt()` injects a `<personality_context>` XML block with
   just names and descriptions
3. The LLM calls `load_context(name)` to fetch full content on demand
4. Full content is returned with frontmatter stripped

Files without frontmatter use their filename (without `.md`) as both name
and description.

### Scripts and Assets

When a directory personality has `scripts/` or `assets/` subdirectories,
`load_personality()` appends a "Available Resources" section noting their
paths. The LLM can then use `read_file` or `exec` to access them.

### CLI Updates

All personality CLI commands handle both formats:

- `personality list` -- Scans for both `*.md` files and directories containing
  `PERSONALITY.md`. Directory personalities show `(dir)` marker.
- `personality create --directory` -- Creates a directory personality with
  `PERSONALITY.md` and `context/` subdirectory.
- `personality show` -- For directory personalities, also shows context
  document listings.
- `personality edit` -- Opens `PERSONALITY.md` for directory personalities.

### Web Route Updates

All personality web routes (`radar/web/routes/personalities.py`) handle both
formats transparently. The create endpoint supports a `directory: true` form
parameter. Delete uses `shutil.rmtree` for directory personalities.

### Testing Directory Personalities

See `tests/test_personality_directory.py` for patterns. Key helpers:

```python
def _create_flat_personality(personalities_dir, name, content=None):
    """Create a flat .md personality file."""

def _create_dir_personality(personalities_dir, name, content=None,
                           context_files=None, scripts=None, assets=None):
    """Create a directory-based personality with optional subdirs."""
```

For system prompt injection tests, patch at source modules:

```python
# Correct: patch search_memories at the source module
with patch("radar.semantic.search_memories", side_effect=Exception("skip")):
    with patch("radar.skills.discover_skills", return_value=[]):
        prompt, pc = _build_system_prompt("my-personality")
```

---

## Adding Config Sections

When you add a new feature that needs configuration, follow this pattern:

### Step 1: Define the Dataclass

In `radar/config/schema.py`, add a `@dataclass`:

```python
@dataclass
class MyFeatureConfig:
    """Configuration for my feature."""

    enabled: bool = True
    api_url: str = "https://api.example.com"
    max_retries: int = 3
```

### Step 2: Add Field to Config

In the same file, add a field to the `Config` class:

```python
@dataclass
class Config:
    # ... existing fields ...
    my_feature: MyFeatureConfig = field(default_factory=MyFeatureConfig)
```

### Step 3: Parse in Config.from_dict()

In `Config.from_dict()`, extract and construct the instance:

```python
@classmethod
def from_dict(cls, data: dict[str, Any]) -> "Config":
    # ... existing parsing ...
    my_feature_data = data.get("my_feature", {})

    return cls(
        # ... existing fields ...
        my_feature=MyFeatureConfig(
            enabled=my_feature_data.get("enabled", MyFeatureConfig.enabled),
            api_url=my_feature_data.get("api_url", MyFeatureConfig.api_url),
            max_retries=my_feature_data.get("max_retries", MyFeatureConfig.max_retries),
        ),
    )
```

### Step 4: Add Environment Variable Overrides

In `radar/config/loader.py`, add to `_apply_env_overrides()`:

```python
def _apply_env_overrides(config: Config) -> Config:
    # ... existing overrides ...

    if my_feature_url := os.environ.get("RADAR_MY_FEATURE_URL"):
        config.my_feature.api_url = my_feature_url

    return config
```

### Step 5: Export from Package

In `radar/config/__init__.py`, add the new class to `__all__` and import it:

```python
from .schema import (
    # ... existing imports ...
    MyFeatureConfig,
)

__all__ = [
    # ... existing exports ...
    "MyFeatureConfig",
]
```

### Example YAML

```yaml
# radar.yaml
my_feature:
  enabled: true
  api_url: "https://custom.api.example.com"
  max_retries: 5
```

---

## Web Routes

The web dashboard uses FastAPI with Jinja2 templates and HTMX for
interactivity. Routes are organized by domain under `radar/web/routes/`.

### Route Module Structure

Each route module creates an `APIRouter` and defines its endpoints:

```python
# radar/web/routes/example.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from radar.web import templates, get_common_context

router = APIRouter()


@router.get("/example", response_class=HTMLResponse)
async def example_page(request: Request):
    """Example page."""
    # Lazy imports to avoid circular imports and speed up startup
    from radar.some_module import get_data

    context = get_common_context(request, "example")
    context["data"] = get_data()
    return templates.TemplateResponse("example.html", context)


@router.get("/api/example", response_class=HTMLResponse)
async def api_example():
    """Return HTML fragment for HTMX."""
    from html import escape
    from radar.some_module import get_items

    items = get_items()
    html = "".join(f'<div>{escape(item)}</div>' for item in items)
    return HTMLResponse(html)
```

### Registering a New Route

In `radar/web/__init__.py`, import and include the router:

```python
from radar.web.routes.example import router as example_router

for _r in [auth_router, dashboard_router, ..., example_router]:
    app.include_router(_r)
```

### Common Context

Every page route should call `get_common_context(request, active_page)`,
which provides:

- `request` -- the Starlette request object (required by Jinja2)
- `active_page` -- used by templates to highlight the active nav item
- `model` -- current LLM model name
- `llm_provider` -- "ollama" or "openai"
- `llm_url` -- API endpoint (hostname only)
- `ntfy_configured` -- whether notifications are set up
- `heartbeat_status` -- "ok", "quiet", or "stopped"
- `heartbeat_label` -- human-readable status label

### HTMX Patterns

Radar uses HTMX for dynamic updates. The pattern is:

1. Full page rendered by a `GET /page` route (returns full HTML template).
2. Dynamic fragments returned by `GET /api/page/data` or `POST /api/page/action`
   routes (return raw HTML fragments, no template wrapper).
3. HTMX attributes in templates trigger requests and swap content.

API endpoints that return HTML fragments do NOT use `templates.TemplateResponse`.
They return `HTMLResponse` with inline HTML strings.

### Lazy Imports

Routes use lazy imports inside function bodies to avoid circular imports and
keep startup fast:

```python
@router.get("/")
async def dashboard(request: Request):
    from radar.memory import get_recent_activity  # Lazy import
    from radar.scheduler import get_status          # Lazy import
    # ...
```

This is important for testing -- when patching these imports, you must
patch at the source module, not the importing module. See the
[Testing Patterns](#testing-patterns) section.

### Authentication

Authentication is handled by middleware in `radar/web/__init__.py`. Auth is
only required when binding to a non-localhost address:

- Localhost (`127.0.0.1`, `localhost`, `::1`): no auth required.
- Non-localhost: requires `web.auth_token` in config or `RADAR_WEB_AUTH_TOKEN`
  env var.
- Static files, `/login`, and `/health` are exempt from auth.

---

## Testing Patterns

### Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_web_routes.py -v

# Run a specific test
python -m pytest tests/test_web_routes.py::TestChatRoutes::test_api_ask -v
```

### Key Fixtures (from `tests/conftest.py`)

**`isolated_data_dir`** -- Creates a temporary data directory and sets
`RADAR_DATA_DIR` to point to it. Use this in any test that reads/writes
Radar data:

```python
def test_something(isolated_data_dir):
    # isolated_data_dir is a Path to the temp directory
    # All radar data operations use this directory
    config_file = isolated_data_dir / "some_file"
    config_file.write_text("test")
```

Under the hood it:
1. Creates `tmp_path / "radar_data"` and sets `RADAR_DATA_DIR`.
2. Resets `radar.config._config = None` and calls `radar.config.reset_data_paths()`.
3. Cleans up automatically via `monkeypatch` and `tmp_path`.

**`isolated_config`** -- Convenience fixture that returns a `Config` object
with isolated data directory already set up:

```python
def test_config_stuff(isolated_config):
    assert isolated_config.llm.provider == "ollama"
```

**`conversations_dir`** and **`personalities_dir`** -- Return specific
subdirectories inside `isolated_data_dir`.

**`mock_llm`** -- A `MockLLMResponder` that patches `httpx.post` so the
real `chat()` tool loop executes with scripted responses:

```python
def test_agent_with_mock_llm(isolated_data_dir, mock_llm):
    # Script the LLM responses
    mock_llm.add_response(content="Hello! Let me check that for you.")
    mock_llm.add_response(
        tool_calls=[{
            "function": {"name": "weather", "arguments": {"location": "Seattle"}}
        }]
    )
    mock_llm.add_response(content="The weather in Seattle is sunny.")

    from radar.agent import ask
    result = ask("What is the weather?")
    assert "Seattle" in result
```

### MockLLMResponder Details

The `MockLLMResponder` class (in `tests/mock_llm.py`) replaces `httpx.post`
at the HTTP layer so that `radar/llm.py`'s tool call loop still runs, but
with scripted responses:

```python
class MockLLMResponder:
    def add_response(self, content="", tool_calls=None):
        """Queue a response. Consumed in order when mock_post is called."""

    def mock_post(self, url, **kwargs):
        """Drop-in replacement for httpx.post."""

    @property
    def last_call(self):
        """Return the most recent call kwargs."""

    def get_sent_messages(self, call_index=-1):
        """Extract the messages list from a recorded call's JSON payload."""
```

This is useful for integration tests that need to verify the full agent
loop without a real LLM.

### Patching Guidelines

**Patch at the source module, not the importing module.** Routes use lazy
imports inside function bodies:

```python
# In radar/web/routes/chat.py:
@router.post("/api/ask")
async def api_ask(...):
    from radar.agent import ask   # <-- lazy import
    result = ask(message)
```

The correct way to patch:

```python
# CORRECT - patch at the source module
@patch("radar.agent.ask", return_value="test response")
def test_api_ask(mock_ask, client):
    resp = client.post("/api/ask", data={"message": "hello"})
    assert "test response" in resp.text

# WRONG - this won't work because the import happens inside the function
@patch("radar.web.routes.chat.ask", return_value="test response")
def test_api_ask(mock_ask, client):
    ...
```

**Exception: `loader.py`'s `create_plugin`.** The `create_plugin` method does
`from radar.config import get_config` inside the function body. Patch
`radar.config.get_config` (the source module), not
`radar.plugins.loader.get_config`.

### Web Route Testing

Use `starlette.testclient.TestClient` with mocked dependencies:

```python
from unittest.mock import patch, MagicMock
from starlette.testclient import TestClient
from radar.web import app


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def mock_common_deps():
    """Mock common dependencies used across most routes."""
    cfg = MagicMock()
    cfg.llm.provider = "ollama"
    cfg.llm.model = "test-model"
    cfg.web.host = "127.0.0.1"
    cfg.web.port = 8420
    cfg.web.auth_token = ""
    # ... configure other fields as needed ...

    with (
        patch("radar.web.get_common_context") as mock_ctx,
        patch("radar.config.load_config", return_value=cfg),
        patch("radar.config.get_config", return_value=cfg),
        patch("radar.scheduler.get_status", return_value={
            "running": False, "last_heartbeat": None,
            "next_heartbeat": None, "pending_events": 0,
            "quiet_hours": False, "interval_minutes": 15,
            "quiet_hours_start": "23:00", "quiet_hours_end": "07:00",
        }),
    ):
        def _ctx(request, active_page):
            return {
                "request": request,
                "active_page": active_page,
                "model": "test-model",
                "llm_provider": "ollama",
                "llm_url": "localhost:11434",
                "ntfy_configured": False,
                "heartbeat_status": "stopped",
                "heartbeat_label": "Scheduler Stopped",
            }
        mock_ctx.side_effect = _ctx
        yield
```

Then test individual endpoints:

```python
@patch("radar.memory.get_recent_conversations", return_value=[])
def test_history_page(mock_convs, client):
    resp = client.get("/history")
    assert resp.status_code == 200
```

### Plugin Sandbox Gotchas

**TestRunner sandbox** (`radar/plugins/runner.py`): Only safe builtins are
available. Standard exception classes like `ValueError` and `TypeError` are
NOT available. To test exceptions in plugin code, use operations that trigger
built-in errors:

```python
# DON'T -- ValueError is not available in the sandbox
def my_tool(x):
    if x < 0:
        raise ValueError("must be positive")

# DO -- use an operation that triggers a built-in error
def my_tool(x):
    if x < 0:
        return "Error: must be positive"
```

**Dynamic tool sandbox** (`register_dynamic_tool` in `radar/tools/__init__.py`):
The restricted builtins block `import` and `open` at **call time**, not at
definition time. Registration succeeds; execution fails. When testing, verify
both phases separately:

```python
# Test 1: Registration succeeds
result = register_dynamic_tool(name="bad_tool", ...)
assert result is True

# Test 2: Execution fails because 'open' is not in safe_builtins
from radar.tools import execute_tool
result = execute_tool("bad_tool", {"path": "/etc/passwd"})
assert "Error" in result
```

### Plugin Testing: Multi-Tool and Local Trust

**Multi-tool registration:** Create a plugin directory with a manifest listing
multiple tools, then call `_register_plugin()`. Verify all tools are registered
and callable via `execute_tool()`:

```python
def test_multi_tool_registration(isolated_data_dir):
    from radar.plugins.loader import PluginLoader
    from radar.tools import execute_tool, get_plugin_tool_names

    loader = PluginLoader(isolated_data_dir / "plugins")
    # ... create plugin dir with manifest + tool.py ...
    loader._register_plugin("my_plugin")

    # Both tools should be registered
    assert get_plugin_tool_names("my_plugin") == {"tool_a", "tool_b"}

    # Both should be callable
    result = execute_tool("tool_a", {"arg": "test"})
    assert "Error" not in result
```

**Local trust plugins:** Test with `importlib`-loaded modules. Verify they
can use imports and full Python features:

```python
def test_local_trust_has_full_python(isolated_data_dir):
    # Create manifest with trust_level: local
    # Create tool.py that imports subprocess or json
    # Register and verify the tool works with full Python access
    ...
```

**Plugin-to-tools tracking:** After registering a multi-tool plugin, verify
`_plugin_tools` tracks all tool names. After unregistering, verify they are
all removed:

```python
def test_unregister_removes_all_tools(isolated_data_dir):
    from radar.tools import get_plugin_tool_names

    loader = PluginLoader(isolated_data_dir / "plugins")
    loader._register_plugin("my_plugin")
    assert len(get_plugin_tool_names("my_plugin")) == 2

    loader._unregister_plugin("my_plugin")
    assert len(get_plugin_tool_names("my_plugin")) == 0
```

### CLI Testing

Use `click.testing.CliRunner` with mocked lazy imports:

```python
from click.testing import CliRunner
from radar.cli import cli

def test_status_command():
    runner = CliRunner()
    with patch("radar.scheduler.get_status", return_value={...}):
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
```

---

## Security Considerations

### Path Blocklist (`radar/security.py`)

File tools (`read_file`, `write_file`, `list_directory`) call
`check_path_security()` before accessing any path.

**Blocked for read and write:**
- `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config/gcloud`, `~/.kube`
- `~/.password-store`, `~/.local/share/keyrings`
- `~/.netrc`, `~/.npmrc`, `~/.pypirc`, `~/.docker/config.json`
- `~/.bash_history`, `~/.zsh_history`, `~/.python_history`
- `~/.env`, `~/.git-credentials`
- `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`

**Blocked for write only** (readable but not writable):
- `~/.bashrc`, `~/.zshrc`, `~/.profile`, `~/.bash_profile`, `~/.zprofile`
- `~/.config/autostart`, `~/.local/share/applications`
- `~/.crontab`

When adding new tools that access the filesystem, always call
`check_path_security(path, operation)` first.

### Exec Safety (`radar/security.py`)

The `exec` tool validates commands via `check_command_security()`. Three modes
are available (`tools.exec_mode` in config):

- `safe_only` -- Only allow known safe commands (`ls`, `cat`, `grep`, etc.)
- `block_dangerous` -- Block known dangerous patterns, allow everything else
  (default)
- `allow_all` -- No restrictions (dangerous)

Dangerous patterns include: `rm -rf`, `sudo`, `curl`, `wget`, `crontab`,
`chmod 777`, `dd if=`, fork bombs, reverse shells, and more.

### Plugin Code Validation (`radar/plugins/validator.py`)

All plugin code passes through AST-based validation before execution:

- No dangerous imports (`os`, `subprocess`, `sys`, `socket`, etc.)
- No dangerous calls (`eval`, `exec`, `open`, `__import__`, etc.)
- No dangerous attribute access (`__code__`, `__globals__`, `__builtins__`)
- Must define at least one function

### Plugin Execution Sandbox

Plugin code executes with restricted builtins that exclude `import`, `open`,
`eval`, `exec`, and exception classes. This applies to:

- `register_dynamic_tool()` in `radar/tools/__init__.py`
- `TestRunner._create_safe_namespace()` in `radar/plugins/runner.py`
- `_load_plugin_scripts()` in `radar/plugins/loader.py`

### Web Authentication

When binding to non-localhost, the web UI requires token authentication:

```yaml
web:
  host: "0.0.0.0"
  auth_token: "your-secret-token"
```

Generate a token:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

The auth middleware in `radar/web/__init__.py` checks cookies, `Authorization`
headers, and query parameters. Token comparison uses `secrets.compare_digest()`
to prevent timing attacks.

### Checklist for New Tools

When adding a new tool, verify:

1. **File access** -- Does it read/write files? Call `check_path_security()`.
2. **Command execution** -- Does it run shell commands? Call
   `check_command_security()` or use the `exec` tool.
3. **Network calls** -- Does it make HTTP requests? Set reasonable timeouts.
   Don't expose credentials in error messages.
4. **User input** -- Does it handle user-provided paths or commands? Validate
   and sanitize.
5. **Error messages** -- Don't leak sensitive information in error strings.
   The LLM (and potentially the user) sees whatever string you return.

For the full security assessment, see `docs/security.md`.

---

## Design Philosophy

### Tools Return Strings

Every tool returns a plain string. No structured data, no special result
objects. The LLM receives the string and decides what to do with it.

This keeps the interface simple and universal. Tools that need to return
structured data can format it as markdown tables or key-value pairs.

### Wrap CLIs, Don't Import Libraries

When integrating with an external service that has a CLI tool, prefer
wrapping the CLI via subprocess over pulling in a library:

```python
# PREFERRED: Wrap the gh CLI
import subprocess
result = subprocess.run(
    ["gh", "pr", "list", "--json", "title,url"],
    capture_output=True, text=True, timeout=30,
)
return result.stdout

# AVOID: Import a GitHub library
from github import Github
g = Github(token)
# ... 50 lines of API code ...
```

The CLI already handles authentication, pagination, error handling, and
output formatting. We just need to parse its output.

### Minimal System Prompt

Every token in the system prompt is a token the LLM has to process on every
request. Keep it tight -- the default personality is under 500 tokens. Tool
descriptions in the JSON Schema are the right place for tool-specific
instructions.

### Heartbeat-First

Radar's primary mode is proactive. The scheduler wakes it up periodically
to check for things that need attention. Interactive chat is secondary. This
means the core agent loop is designed for both modes -- heartbeat messages
are just user messages sent through the same `agent.run()` path.

### Local-First

All data stays on the user's machine. No cloud APIs (beyond the user's own
Ollama instance), no telemetry, no external dependencies. The only network
calls are to services the user explicitly configures (Ollama, ntfy, Open-Meteo,
GitHub CLI).

### Plugin Trust Model

Plugins use a two-tier trust model:

- **Sandbox** -- LLM-generated plugins get restricted builtins with no imports,
  no filesystem, no network. AST validation blocks dangerous patterns. This is
  the default and the only level the LLM can create.

- **Local** -- Human-authored plugins get full Python via `importlib`. No AST
  validation, no sandbox restrictions. The human reviewing the code is the
  security gate.

Local trust can never be auto-approved because the `auto_approve` and
`auto_approve_if_tests_pass` config options only apply to sandbox plugins.
This is enforced in `PluginLoader.approve_plugin()`.

### No Over-Engineering

Keep solutions simple. The tool call loop is ~50 lines. Config is dataclasses
with `from_dict()`. Conversation storage is JSONL (one file per conversation).
Don't add abstractions until you need them at least three times.
