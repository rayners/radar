# Radar Future Work

A comprehensive list of improvement opportunities and features for future development.

This consolidates ideas from `PROJECT.md` (Phases 3-4) and the former `phase3-ideas.md`.

---

## 1. Testing & Quality (Critical Gap)

Currently only `tests/test_feedback.py` exists (~16 tests). Major gaps:

- [ ] **Core agent tests** - context building, tool execution loop, message storage
- [ ] **LLM integration tests** - mock Ollama/OpenAI, tool call parsing, error handling
- [ ] **Tool framework tests** - registration, execution, parameter validation
- [ ] **Security tests** - path blocklist, command validation, edge cases
- [ ] **Memory tests** - JSONL operations, concurrent access, semantic search
- [ ] **Config tests** - YAML loading, env var overrides, validation errors
- [ ] **Scheduler tests** - heartbeat ticks, quiet hours, event queuing
- [ ] **Plugin tests** - code validation, sandboxed execution, version rollback
- [ ] **Web route tests** - FastAPI endpoints, HTMX responses
- [ ] **Integration test harness** - full conversation flow with mock LLM

---

## 2. Web UI Incomplete Features

### Dashboard Improvements
- [ ] Real `tool_calls_today` counter (currently hardcoded to 0)
- [ ] `/api/activity` endpoint for dashboard refresh
- [ ] Live activity feed with real data
- [ ] Uptime/health metrics display

### Config Page
- [ ] `POST /api/config` endpoint to save changes
- [ ] Config validation before save
- [ ] Config hot-reload without daemon restart

### Tasks Page
- [ ] Custom scheduled task CRUD (currently `tasks = []`)
- [ ] `/tasks/add` modal for creating tasks
- [ ] `/api/tasks/{id}/run` for manual execution
- [ ] `/api/heartbeat/trigger` for manual heartbeat
- [ ] Cron expression support for task scheduling

### History Page
- [ ] `/api/history` with filter/pagination
- [ ] Conversation search (full-text + semantic)
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
- [ ] **IMAP email monitor** - summarize inbox, flag important, extract action items
- [ ] **Webhook receiver** - generic endpoint for GitHub, Stripe, Zapier, n8n
- [ ] **CalDAV calendar** - upcoming events, proactive reminders, daily briefing
- [ ] **Notes vault integration** - Obsidian wiki links, tags, semantic search

### Output Actions
- [ ] **SMTP email sender** - compose and send emails (with confirmation)
- [ ] **Task manager integration** - Todoist, Things, Apple Reminders
- [ ] **Home Assistant** - smart home control via REST API
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
- [ ] **Browser automation** - Playwright for web form filling, scraping

### Pipelines (Multi-tool Workflows)
- [ ] **PDF/comic metadata extraction** - extract info → search APIs → update metadata
- [ ] **Finance transaction categorization** - import → categorize → report

---

## 4. Architecture Improvements

### Error Handling & Resilience
- [ ] Exponential backoff + jitter for API calls
- [ ] Circuit breaker for flaky services
- [ ] Retry logic for LLM/embedding calls
- [ ] Detailed error logging with context
- [ ] Health check endpoint (`/health`)

### Configuration
- [ ] Pydantic validation for config schema
- [ ] Config hot-reload via file watcher
- [ ] Configuration migration for version upgrades
- [ ] Config documentation generator

### Memory & Storage
- [ ] Migrate conversations to SQLite (consistency + indexing)
- [ ] Conversation archival with retention policy
- [ ] Hybrid search (semantic + BM25/FTS5)
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
- [ ] Per-profile tool permissions (allowlist/blocklist)

### Integrations Architecture
- [ ] Common interface: `poll()` for pull-based, `handle_event()` for push-based
- [ ] Events flow into same queue as file watchers
- [ ] Config under `integrations:` key in radar.yaml
- [ ] Separate secrets file for credentials
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
- [ ] Daily/weekly usage summaries

### Context Management
- [ ] Entity extraction and knowledge graphs
- [ ] Auto-summarization for long conversations
- [ ] Memory decay with confidence scores
- [ ] Context window optimization
- [ ] "What did we discuss about X last week?" queries

### Multi-Model Support
- [ ] Vision model support for image-based PDF pages
- [ ] Multiple model routing (fast model for triage, larger for complex tasks)
- [ ] Per-task model selection
- [ ] MCP server support (integrate with other tools)

---

## 6. Scheduler & Automation

### Chat-based Scheduled Tasks
Natural language task scheduling via chat:
- [ ] Database table for scheduled tasks (time, message, repeat pattern, last_run)
- [ ] Tools: `schedule_task`, `list_scheduled_tasks`, `cancel_task`
- [ ] Heartbeat checks for due tasks and injects them as events
- [ ] Example: "Send me the weather every morning at 7am"

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

- [ ] Mock Ollama server for testing
- [ ] Conversation recording + playback
- [ ] Development mode with hot reload
- [ ] CLI tool scaffolding command
- [ ] Architecture decision records (ADRs)
- [ ] Contributing guide
- [ ] Integration test harness without real accounts

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

- [ ] Split `routes.py` (1000+ lines) into domain modules
- [ ] Split `config.py` (400+ lines) - separate concerns
- [ ] Split `plugins.py` (500+ lines) - validation, loading, testing
- [ ] Consistent error handling patterns
- [ ] API versioning strategy
- [ ] Structured error responses (RFC 7807)

---

## Open Questions

- How to handle rate limits on external APIs?
- Should integrations have their own heartbeat intervals?
- How to test integrations without real accounts?
- OAuth flow for services that require it?
- Plugin sandboxing - how much isolation?
- Multi-user support or single-user only?

---

## Priority Suggestions

**High Priority (Foundational):**
1. Test coverage for core components
2. Config save functionality in web UI
3. Task scheduling in web UI
4. Error handling improvements

**Medium Priority (Usability):**
1. Conversation search/export
2. Token/cost tracking
3. Additional notification channels
4. Tool confirmation modes
5. RSS feed reader (simple, high value)
6. Webhooks (enables many services via Zapier/n8n)

**Lower Priority (Nice to Have):**
1. Theme support
2. Mobile app
3. Voice input
4. Knowledge graphs
5. Multi-user support

---

## Notes

- Project is at "Phase 2 (Daemon + Web Dashboard)"
- Local-first design is core principle - maintain offline capability
- Security-conscious approach should continue for new features
- Remote Ollama already supported via `RADAR_LLM_BASE_URL`
