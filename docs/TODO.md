# Radar Future Work

A comprehensive list of improvement opportunities and features for future development.

This consolidates ideas from `PROJECT.md` (Phases 3-4) and the former `phase3-ideas.md`.

---

## 1. Testing & Quality (Critical Gap)

Test files: `test_feedback.py` (16 tests), `test_scheduled_tasks.py` (49 tests), `test_web_routes.py` (86 tests), `test_tool_discovery.py` (16 tests), `test_tool_framework.py` (31 tests), `test_personality_frontmatter.py` (36 tests), `test_security.py` (87 tests), `test_config.py` (43 tests), `test_memory.py` (45 tests), `test_llm.py` (42 tests), `test_agent.py` (32 tests), `test_calendar.py` (45 tests), `test_cli_daemon.py` (20 tests), `test_plugins.py` (169 tests), `test_scheduler.py` (42 tests), `test_hooks.py` (96 tests), `test_integration.py` (7 tests), `test_skills.py` (33 tests), `test_personality_directory.py` (23 tests), `test_url_monitors.py` (50 tests), `test_summaries.py` (41 tests), `test_documents.py` (43 tests), `test_retry.py` (21 tests), `test_hot_reload.py` (21 tests) — **1094 total**.

- [x] **Core agent tests** - personality loading, system prompt building, Jinja2 template rendering, plugin prompt variables, run/ask orchestration (32 tests)
- [x] **LLM integration tests** - mock Ollama/OpenAI, tool call parsing, rate limit fallback, retry with backoff, format conversion (42 tests)
- [x] **Tool framework tests** - registration, execution, parameter validation (31 tests)
- [x] **Security tests** - path blocklist, command validation, write-only blocks, edge cases (87 tests)
- [x] **Memory tests** - JSONL operations, display formatting, conversation listing, tool call counting, activity feed, enriched history (45 tests)
- [x] **Config tests** - YAML loading, env var overrides, deprecated field migration, DataPaths, RetryConfig (43 tests)
- [x] **Scheduler tests** - heartbeat ticks, quiet hours, event queuing (42 tests)
- [x] **Plugin tests** - code validation, sandboxed execution, version rollback, manifest capabilities, widgets, personality bundling, helper scripts, multi-tool registration, local trust, plugin install CLI, prompt variables (169 tests across all 5 modules)
- [x] **Web route tests** - FastAPI endpoints, HTMX responses, config save, activity API, history API (86 tests across all 11 route modules)
- [x] **Integration test harness** - full conversation flow with mock LLM (7 tests)

---

## 2. Web UI Incomplete Features

### Dashboard Improvements
- [x] Real `tool_calls_today` counter — scans JSONL conversations for tool calls with today's timestamp
- [x] `/api/activity` endpoint for dashboard refresh — returns HTML fragment for HTMX
- [x] Live activity feed with real data — unified timeline of chats and tool calls
- [ ] Uptime/health metrics display

### Config Page
- [x] `POST /api/config` endpoint to save changes — dot-notation form fields, deep-merge, YAML write
- [x] Config validation before save — provider enums, numeric ranges
- [x] Config hot-reload without daemon restart — calls `reload_config()` after save

### Tasks Page
- [x] Custom scheduled task CRUD
- [x] `/tasks/add` modal for creating tasks
- [x] `/api/tasks/{id}/run` for manual execution
- [x] `/api/heartbeat/trigger` for manual heartbeat
- [ ] Cron expression support for task scheduling

### History Page
- [x] `/api/history` with filter/pagination — HTMX endpoint with type filter, search, offset/limit pagination
- [x] Conversation search (full-text) — case-insensitive substring search across message content
- [ ] Conversation search (semantic) — embedding-based search
- [ ] Export conversations as markdown/JSON
- [ ] Conversation archival/deletion

### General UI
- [ ] Theme support (light mode, custom schemes, high contrast)
- [ ] Keyboard shortcuts for power users (vim-style navigation)
- [ ] Bulk operations (delete multiple memories, etc.)

---

## 3. New Tools to Add

### Input Sources
- [ ] **RSS/Atom feed reader** - monitor blogs, releases, news; filter by keywords
- [ ] **IMAP email monitor** - read-only inbox access for summarization, bill tracking, inbox watch, package tracking (see `docs/scenarios.md` for prompt injection mitigations)
- [ ] **Webhook receiver** - generic endpoint for GitHub, Stripe, Zapier, n8n
- [x] **CalDAV calendar** - khal CLI wrapper with JSON output, caching, heartbeat reminders (45 tests)
- [ ] **Notes vault integration** - Obsidian wiki links, tags, semantic search

### Output Actions
- [ ] **SMTP email sender** - compose and send emails (with confirmation)
- [ ] **Task manager integration** - Todoist, Things, Apple Reminders
- [ ] **Home Assistant** - smart home control via REST API (unlocks: weather-triggered actions, climate, security — see `docs/scenarios.md`)
- [ ] **Messaging** - Slack, Discord, Matrix posting
- [ ] **Git operations** - auto-commit, branch creation, PR opening

### APIs to Query
- [ ] **Package tracking** - USPS, FedEx, UPS status
- [ ] **Financial APIs** - stock quotes, crypto prices, transaction alerts
- [ ] **News APIs** - structured news summaries
- [ ] **Translation** - multi-language support

### Utility Tools
- [ ] **Screenshot capture** - take and analyze screenshots
- [ ] **Clipboard access** - read/write system clipboard
- [ ] **System info** - CPU, memory, disk usage
- [ ] **Process management** - list/kill processes
- [ ] **Browser automation** - Playwright for web form filling, scraping (unlocks: appointments, forms, price monitoring — see `docs/scenarios.md`)
- [x] **Web page diff/monitor** - fetch a URL periodically, diff against previous fetch, report changes (unlocks: changelog tracking, price drops, government notices) — `monitor_url`, `list_url_monitors`, `check_url`, `remove_monitor` tools + heartbeat integration (50 tests)
- [ ] **Jinja2 template tester** - validate personality template syntax and preview rendered output from CLI

### Pipelines (Multi-tool Workflows)
- [ ] **PDF/comic metadata extraction** - extract info → search APIs → update metadata
- [ ] **Finance transaction categorization** - import → categorize → report

---

## 4. Architecture Improvements

### Error Handling & Resilience
- [x] Exponential backoff + jitter for API calls — `radar/retry.py` with `compute_delay()` using full jitter
- [ ] Circuit breaker for flaky services
- [x] Retry logic for LLM/embedding calls — inline retry loops in `radar/llm.py` and `radar/semantic.py`, configurable via `RetryConfig`
- [x] Detailed error logging with context — `log_retry()` logs provider, model, attempt, delay, and error type
- [x] Health check endpoint (`/health`) — basic + `?check_services=true` for LLM/embedding/DB pings

### Configuration
- [ ] Pydantic validation for config schema
- [x] Config hot-reload via file watcher — mtime check at each heartbeat reloads config, hooks, and external tools
- [ ] Configuration migration for version upgrades
- [ ] Config documentation generator

### Memory & Storage
- [ ] Migrate conversations to SQLite (consistency + indexing)
- [ ] Conversation archival with retention policy
- [x] Hybrid search (semantic + BM25/FTS5) — document indexing with FTS5 + cosine similarity and reciprocal rank fusion
- [ ] Write locks for concurrent access safety
- [ ] Search filters (date range, source, sentiment)

### Tool System
- [ ] Formal `Tool` base class with lifecycle hooks
- [ ] Validate all tools at startup
- [ ] Tool metadata (version, author, permissions)
- [ ] Unify plugin + built-in tool registration
- [ ] Tool testing framework with mock LLM

### Security Enhancements
- [ ] Centralized `ToolSecurityContext`
- [ ] Rate limiting per tool
- [ ] Audit trail of tool executions (immutable log)
- [ ] Proper path parsing for security checks
- [ ] Tool "dry run" mode with simulated results
- [x] Per-profile tool permissions (allowlist/blocklist) — personality front matter `tools.include`/`tools.exclude`

### Integrations Architecture
- [ ] Common interface: `poll()` for pull-based, `handle_event()` for push-based
- [ ] Events flow into same queue as file watchers
- [ ] Config under `integrations:` key in radar.yaml
- [ ] Separate secrets file for credentials (`~/.config/radar/secrets.yaml` or OS keyring) — prerequisite for IMAP and browser auth
- [ ] OAuth flow support for services that require it

---

## 5. LLM & Agent Enhancements

### Multi-step Planning
- [ ] Break tasks into steps, show plan before execution
- [ ] Allow user to edit/approve plan
- [ ] Progress tracking for multi-step tasks
- [ ] Resumable tasks after interruption

### Tool Chaining
- [ ] Pipe output of one tool to input of another
- [ ] Conditional tool execution
- [ ] Parallel tool execution where safe
- [ ] Define common chains in config

### Confirmation Modes
- [ ] Per-tool confirmation settings (always/destructive/never)
- [ ] Preview mode for file writes
- [ ] Undo capability for reversible actions
- [ ] Global default with per-tool overrides

### Cost & Token Tracking
- [ ] Token counting per request
- [ ] Cost estimation for API calls
- [ ] Budget alerts and limits
- [ ] Usage dashboard in web UI
- [x] Daily/weekly usage summaries — conversation summaries with heartbeat-driven auto-generation

### Context Management
- [ ] Entity extraction and knowledge graphs
- [x] Auto-summarization for long conversations — periodic conversation digests (daily/weekly/monthly) via heartbeat
- [ ] Memory decay with confidence scores
- [ ] Context window optimization
- [x] "What did we discuss about X last week?" queries — summaries stored in semantic memory, accessible via `recall`

### Multi-Model Support
- [ ] Vision model support for image-based PDF pages
- [ ] Multiple model routing (fast model for triage, larger for complex tasks)
- [x] Per-task model selection — personality front matter `model`/`fallback_model` overrides
- [ ] MCP server support (integrate with other tools)

---

## 6. Scheduler & Automation

### Chat-based Scheduled Tasks
Natural language task scheduling via chat:
- [x] Database table for scheduled tasks (time, message, repeat pattern, last_run)
- [x] Tools: `schedule_task`, `list_scheduled_tasks`, `cancel_task`
- [x] Heartbeat checks for due tasks and injects them as events
- [x] Example: "Send me the weather every morning at 7am"

**Tradeoffs vs crontab:**
| Aspect | Crontab | Heartbeat |
|--------|---------|-----------|
| Reliability | System-level, always runs | Depends on radar daemon |
| Configuration | Separate from radar | Unified in radar.yaml |
| Context | Each run is isolated | Persistent conversation |
| Docker | Requires cron in container | Works out of the box |

### Other Scheduler Improvements
- [ ] Persistent event queue (survives crashes)
- [ ] Event priority levels (critical/normal/low)
- [ ] Config-based scheduled tasks (radar.yaml `scheduled_tasks:` section)
- [ ] Heartbeat retry on failure
- [ ] Metrics (duration, event count, success rate)
- [ ] Task dependencies (run A after B completes)
- [ ] Per-integration heartbeat intervals

---

## 7. Observability & Logging

- [ ] Structured JSON logging with consistent schema
- [ ] Request ID propagation for tracing
- [ ] Prometheus metrics endpoint (`/metrics`)
- [ ] Grafana dashboard template
- [ ] Log aggregation friendly format
- [ ] Performance benchmarks for critical paths
- [ ] Log levels configurable per module

---

## 8. Developer Experience

- [x] Mock Ollama server for testing — `MockLLMResponder` in `tests/mock_llm.py` with `mock_llm` fixture
- [ ] Conversation recording + playback
- [ ] Development mode with hot reload
- [ ] CLI tool scaffolding command
- [ ] Architecture decision records (ADRs)
- [ ] Contributing guide
- [x] Integration test harness without real accounts — `tests/test_integration.py` with MockLLMResponder

---

## 9. User Experience

- [ ] Multiple profiles (work/personal contexts with separate memories, prompts, permissions)
- [ ] Conversation export (markdown, JSON)
- [ ] Memory import/export and backup/restore
- [ ] Mobile app or PWA
- [ ] Voice input/output
- [ ] Desktop notifications (beyond ntfy)
- [ ] Quick profile switching

---

## 10. Code Quality & Refactoring

- [x] Split `routes.py` into domain modules (9 modules under `radar/web/routes/` using APIRouter)
- [x] Split `config.py` into `radar/config/` package (paths, schema, loader)
- [x] Split `plugins.py` into `radar/plugins/` package (models, validator, runner, versions, loader)
- [ ] Consistent error handling patterns
- [ ] API versioning strategy
- [ ] Structured error responses (RFC 7807)

---

## 11. Extensibility & Plugin Architecture

Reducing friction for adding new tools and plugins.

### Tool Registration & Discovery
- [x] **Tool auto-discovery** — `_discover_tools()` uses `pkgutil.iter_modules` to auto-import all tool modules. Adding a tool is just "create the file."
- [ ] **Tool config support** — Let tools declare config fields (stored under `tools.<name>:` in `radar.yaml`). Currently tools that need settings (e.g., API keys, preferences) have no standard pattern.
- [ ] **Tool dependency validation** — Tools can declare required Python packages; checked at startup with clear error messages for missing deps.
- [x] **`static_tools` list maintenance** — `_static_tools` set is now derived automatically from the registry during discovery. `is_dynamic_tool()` no longer uses a hardcoded list.

### Plugin Capabilities & Extensibility
- [x] **Plugin manifest capabilities** — `capabilities` field supports `["tool", "widget", "personality", "prompt_variables"]` with backward-compatible defaults
- [x] **Dashboard widgets** — Plugins with `widget` capability render Jinja2 templates on the dashboard with auto-refresh
- [x] **Personality bundling** — Plugins can bundle personality `.md` files in `personalities/` subdirectory
- [x] **Helper script modules** — Plugins can include validated helper scripts in `scripts/` subdirectory
- [x] **Prompt variables** — Plugins with `prompt_variables` capability contribute dynamic values to personality templates via Jinja2 `{{ variable }}` syntax

### Plugin Distribution & Trust
- [x] **Multi-tool plugins** — Single plugin can register multiple tools via `tools` list in manifest. Backward compatible with single-tool `schema.yaml` fallback.
- [x] **Trust levels** — `sandbox` (restricted, LLM-generated) vs `local` (full Python via importlib, human-reviewed). LLM always forced to sandbox; local trust never auto-approved.
- [x] **CLI plugin install** — `radar plugin install <dir>`, `radar plugin list`, `radar plugin approve <name>` for installing and managing plugins from the command line.
- [x] **Plugin-to-tools tracking** — `_plugin_tools` dict maps plugin names to their registered tool names for clean multi-tool unregistration.
- [ ] **Remote plugin repository** — install plugins from git URLs or an HTTP registry (`radar plugin install https://...`)
- [ ] **Plugin dependency declarations** — plugins declare dependencies on other plugins or Python packages

### Personality Template Engine
- [ ] **Conditional template sections** — Jinja2 `{% if %}`/`{% for %}` blocks in personality files (e.g., day-specific instructions, context-aware behavior)
- [ ] **Template includes** — `{% include "fragment.md" %}` for reusable personality components across multiple personalities
- [ ] **Built-in prompt variable expansion** — more built-in variables beyond time: `active_personality`, `tool_count`, `memory_count`, `uptime`
- [ ] **Template syntax validation** — warn on Jinja2 syntax errors in personality files at load time instead of silently failing

### Plugin Lifecycle
- [ ] **Plugin loading at startup** — Load all enabled plugins when daemon starts, not on first tool call. Currently a plugin created via chat isn't available until the tool registry is next queried.
- [ ] **Plugin scaffolding CLI** — `radar plugin create <name>` to generate boilerplate file with `@tool` decorator, test cases, and manifest.
- [ ] **Plugin persistent state** — Simple key-value store per plugin for cross-invocation state (e.g., a counter, last-run timestamp, cached data).
- [x] **Plugin hook system** — Nine-point hook system (`pre_tool_call`, `post_tool_call`, `filter_tools`, `pre_agent_run`, `post_agent_run`, `pre_memory_store`, `post_memory_search`, `pre_heartbeat`, `post_heartbeat`) with config-driven rules in `radar.yaml` and plugin `hook` capability. Supports blocking, observing, filtering, and transforming at tool, agent, memory, and heartbeat boundaries. (96 tests in `test_hooks.py`)
- [ ] **Plugin event hooks** — Plugins can register for events like `on_conversation_start`, `on_tool_error` to participate in the system lifecycle without being explicitly called by the LLM. (Note: `on_heartbeat` is now covered by the `pre_heartbeat`/`post_heartbeat` hook points.)
- [ ] **Prompt variable caching** — optional TTL-based caching for expensive prompt variable functions (e.g., API calls), with cache-bust on demand

### Developer Experience
- [ ] **Tool testing harness** — Run a tool's test cases from CLI (`radar tool test <name>`) without needing the full agent loop.
- [ ] **Plugin hot-reload** — When a plugin file changes on disk, reload it without restarting the daemon.
- [ ] **Better error context for plugins** — Include the full input/output and stack trace in error logs, not just the exception message.

---

## 12. Scenarios & Recipes

Ready-to-use configurations that demonstrate Radar's autonomous capabilities. See `docs/scenarios.md` for the full scenario inventory and capability gap analysis.

### Validated Recipes (`docs/recipes/`)
- [x] **Daily Briefing** — Morning notification with calendar, weather, GitHub, deadlines (`docs/recipes/daily-briefing.md`, personality: Colonel Potter)
- [x] **Homelab Monitor** — System health checks with threshold alerting and dedup (`docs/recipes/homelab-monitor.md`, personality: Klinger)
- [x] **Research Monitor** — Scheduled web searches with memory-based dedup (`docs/recipes/research-monitor.md`, personality: Father Mulcahy)

### Scenarios Needing Validation
- [ ] **Meeting prep assistant** — recall person context + GitHub activity before calendar events
- [ ] **Bill tracker from PDFs** — file watcher on Downloads + pdf_extract + schedule reminders
- [x] **Writing/journaling coach** — daily evening summary of conversations + journaling reminders (conversation summaries + heartbeat integration)

### Capability Gaps (ranked by scenario unlock count)
| # | Gap | Scenarios unlocked | Difficulty |
|---|-----|--------------------|------------|
| 1 | IMAP email (read-only) | Briefings, bill tracking, inbox watch, package tracking | Medium |
| 2 | Browser automation (Playwright) | Appointments, forms, price monitoring, article reading | High |
| ~~3~~ | ~~Web page diff/monitor~~ | ~~Changelog tracking, price drops, government notices~~ | ~~Low~~ (done) |
| 4 | Home Assistant API | Smart home, climate, security | Medium |
| 5 | Secure credential store | Foundation for email + browser auth | Low-Medium |

---

## Open Questions

- How to handle rate limits on external APIs?
- Should integrations have their own heartbeat intervals?
- How to test integrations without real accounts? *(partially answered — `MockLLMResponder` exists for LLM, but no mock for external services like GitHub/calendar)*
- OAuth flow for services that require it?
- ~~Plugin sandboxing - how much isolation?~~ *(answered — sandbox vs local trust levels, restricted builtins for sandbox)*
- Multi-user support or single-user only?
- Should personality templates support Jinja2 control flow (`{% if %}`, `{% for %}`) or just variable substitution?
- Plugin prompt variables vs built-in prompt variables — where's the boundary? Should things like hostname be built-in?

---

## Priority Suggestions

**High Priority (Foundational):**
1. ~~Test coverage~~ (done — 1094 tests)
2. ~~Config save in web UI~~ (done)
3. ~~Tool auto-discovery~~ (done)
4. Error handling improvements (still relevant)
5. ~~Conversation search/history~~ (done — `/api/history` with filter, search, pagination)
6. End-to-end validation of recipe scenarios (daily briefing, homelab, research)

**Medium Priority (Usability):**
1. IMAP email (read-only) — highest scenario unlock count, enables briefing + bill tracking + inbox watch
2. ~~Web page diff/monitor tool~~ (done — 50 tests)
3. Plugin scaffolding CLI (`radar plugin create`)
4. Template syntax validation for personality files
5. Token/cost tracking
6. RSS feed reader
7. Plugin event hooks (`on_heartbeat`, etc.)
8. Conversation export (markdown, JSON)

**Lower Priority (Nice to Have):**
1. Browser automation (Playwright) — high impact but complex to build safely
2. Home Assistant API
3. Remote plugin repository
4. Conditional personality templates
5. Theme support
6. Knowledge graphs
7. Multi-user support

---

## Notes

- Project is at "Phase 2 (Daemon + Web Dashboard)" — though the plugin system, Jinja2 templating, and trust-level architecture have pushed well into Phase 3 territory in practice
- Local-first design is core principle - maintain offline capability
- Security-conscious approach should continue for new features
- Remote Ollama already supported via `RADAR_LLM_BASE_URL`
