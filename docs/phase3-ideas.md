# Phase 3: Integrations (Brainstorming)

Ideas for expanding Radar's input sources and output actions.

## Input Sources

Things Radar can monitor and react to.

### RSS/Atom Feeds
- Monitor blogs, news sites, release feeds
- Filter by keywords, summarize new items
- Example: "Notify me when there's a new Python release"

### IMAP Email
- Monitor inbox for specific senders/subjects
- Summarize incoming mail, extract action items
- Example: "When I get an email from $boss, summarize it and notify me"

### Webhooks
- Receive POST requests from external services
- Generic endpoint that queues events for heartbeat
- Enables: GitHub (PR reviews, issues), Stripe (payments), Zapier, etc.

### CalDAV Calendar
- Connect to calendar server (Google, iCloud, self-hosted)
- Proactive reminders: "You have a meeting in 15 minutes"
- Daily briefing: "Today you have 3 meetings..."

### Notes Vault (Obsidian, etc.)
- Beyond file watcher - understand wiki links, tags
- "Summarize notes tagged #project-x"
- "What did I write about $topic last week?"

## Output Actions

Things Radar can do in response to events.

### SMTP Email
- Send emails on user's behalf
- Requires confirmation for safety
- Example: "Draft and send a reply to this email"

### Task Managers (Todoist, Things, Reminders)
- Create tasks from conversations or events
- Example: "Add 'review PR' to my todo list"

### Home Assistant
- Control smart home devices
- Example: "Turn off the lights when I say goodnight"

### Messaging (Slack, Discord, Matrix)
- Post to channels or DMs
- Example: "Post the deploy status to #engineering"

### Git Operations
- Auto-commit changes, create branches, open PRs
- Example: "Commit these changes with a good message"

## APIs to Query

External data to include in context.

### Weather
- Include in heartbeat/daily briefing
- "It's going to rain this afternoon, bring an umbrella"

### Package Tracking
- Monitor deliveries from major carriers
- "Your package is out for delivery today"

### GitHub/GitLab
- PR reviews assigned to you
- Issue mentions
- CI/CD status

### Financial (Plaid, bank APIs)
- Transaction alerts
- "Unusual charge detected on your card"

## Implementation Priority

Suggested order based on effort vs. value:

1. **Webhooks** - Generic, enables many services via Zapier/n8n/etc.
2. **RSS Feeds** - Simple polling, read-only, immediately useful
3. **CalDAV** - Proactive value, standard protocol
4. **SMTP** - Pairs well with IMAP for email workflows
5. **Home Assistant** - Fun, tangible, existing REST API

## Architecture Considerations

- Each integration = separate module in `radar/integrations/`
- Common interface: `poll()` for pull-based, `handle_event()` for push-based
- Events flow into the same queue as file watchers
- Config in `radar.yaml` under `integrations:` key
- Credentials: environment variables or separate secrets file

## Open Questions

- How to handle rate limits on external APIs?
- Should integrations have their own heartbeat intervals?
- How to test integrations without real accounts?
- OAuth flow for services that require it?
