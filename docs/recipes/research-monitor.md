# Research Monitor ("Topic Curator")

Scheduled web searches on topics you care about, with memory-based deduplication so you only hear about genuinely new findings. Results are sent as push notification digests.

## Prerequisites

- **Radar daemon running** (`radar start` or `radar service install`)
- **ntfy configured** for push notifications
- **Web search configured** — DuckDuckGo works out of the box (default); Brave Search recommended for reliability
- **Embedding model available** — needed for `remember`/`recall` deduplication

## Personality File

Save this to `~/.local/share/radar/personalities/father_mulcahy.md`:

```markdown
---
model: qwen3:latest
tools:
  include:
    - web_search
    - recall
    - remember
    - notify
---

# Father Mulcahy

Thoughtful, well-read, keeps up with the wider world, delivers findings with gentle insight.

## Instructions

You are Father Mulcahy — well-informed, thoughtful, and quietly diligent. You read widely and share what matters. You have a gift for separating the signal from the noise and delivering the important bits with context.

When running a research digest, follow this process for each topic:

1. **Search** — Use web_search to find recent information on the assigned topic.
2. **Recall** — Check what you previously reported on this topic by recalling "research digest: <topic name>".
3. **Filter** — Compare search results against what you already reported. Remove:
   - Stories you already covered (same event, different article)
   - Minor updates to previously reported stories (unless significant new information)
   - Irrelevant or off-topic results
4. **Summarize** — For genuinely new findings, write a brief summary of each (1-2 sentences).
5. **Remember** — Store what you just reported: `remember("Research digest [topic]: [date]. Covered: [brief list of stories]")`. This is critical for deduplication in the next run.
6. **Notify** — Send a digest via notify. If nothing new was found, do NOT send a notification.

### Formatting

Format digests as concise bullet points:

```
Topic: Kubernetes Security

- CVE-2025-1234: Critical vulnerability in kubelet allows privilege escalation. Patches available for v1.28+.
- New Falco 0.38 release adds eBPF-based runtime detection for container escapes.
- CNCF published updated supply chain security guidelines for Helm charts.
```

### Notification Rules

- **New findings**: Send with title "Research: <topic>" and default priority.
- **Critical finding** (security CVE, breaking change, urgent news): Use priority "high".
- **Nothing new**: Do NOT send. Silence means "nothing to report."

Current time: {{ current_time }}
Today is {{ day_of_week }}, {{ current_date }}.
```

## Configuration

Add to your `radar.yaml`:

```yaml
# Personality
personality: father_mulcahy

# Search provider (Brave recommended for reliability)
search:
  provider: brave          # or duckduckgo (default, no key needed)
# Set RADAR_BRAVE_API_KEY if using Brave

# Notification settings
notifications:
  url: https://ntfy.sh
  topic: your-topic-here

# Heartbeat
heartbeat:
  interval_minutes: 15
  quiet_hours_start: "23:00"
  quiet_hours_end: "07:00"
```

## Setup Steps

1. **Create the personality file:**
   ```bash
   radar personality create father_mulcahy
   # Then paste the personality content above
   ```

2. **Set it as active:**
   ```bash
   radar personality use father_mulcahy
   ```

3. **Create scheduled tasks for each topic.** One task per topic gives you independent schedules:

   **Daily topic (e.g., security advisories):**
   ```bash
   radar ask "Schedule a daily task called 'research_k8s_security' at 08:00 with the message: Search for recent Kubernetes security advisories, CVEs, and vulnerability disclosures. Compare against what you previously reported and only include genuinely new findings. Send a digest via notify if anything new was found."
   ```

   **Weekly topic (e.g., language releases):**
   ```bash
   radar ask "Schedule a weekly task called 'research_rust_releases' on mon at 09:00 with the message: Search for Rust programming language news — new releases, major RFCs, ecosystem updates. Compare against previous reports and send a digest of new findings only."
   ```

   **Weekly general interest:**
   ```bash
   radar ask "Schedule a weekly task called 'research_ai_news' on fri at 10:00 with the message: Search for notable AI and machine learning news from this week. Focus on open source tools, model releases, and practical developments. Skip hype and speculation. Send a digest if anything noteworthy."
   ```

4. **Test it:**
   ```bash
   radar heartbeat
   ```

## How It Works

```
schedule_task fires (daily/weekly per topic)
  |
  v
web_search(query="Kubernetes security advisories 2025")
  |
  v
recall("research digest: kubernetes security")
  -> Returns: "Covered: CVE-2025-0001, Falco 0.37 release..."
  |
  v
LLM compares search results against recalled history
  -> Filters out already-reported items
  |
  v
New findings?
  |
  +--> No  -> Do nothing (silent)
  |
  +--> Yes -> remember("Research digest kubernetes security: 2025-01-15. Covered: ...")
             notify(message=digest, title="Research: Kubernetes Security")
```

The memory loop is the key innovation. Without `recall`/`remember`, you'd get raw search results every time. With it, Radar acts as a curator that knows what you already know.

## Example Topics

| Topic | Schedule | Search query hint |
|-------|----------|-------------------|
| Kubernetes security | Daily 8am | "Kubernetes CVE vulnerability advisory" |
| Rust releases | Weekly Mon 9am | "Rust programming language release RFC" |
| Python ecosystem | Weekly Wed 9am | "Python new release PEP notable package" |
| Local news | Daily 7:30am | "your city name local news" |
| Tech industry | Weekly Fri 10am | "notable technology news open source" |
| Home automation | Weekly Sat 9am | "Home Assistant release update integration" |
| Security advisories | Daily 8am | "CVE critical vulnerability disclosure" |

## Customization

### Multiple topics in one notification
Instead of one task per topic, you can create a single task that covers multiple topics:

```bash
radar ask "Schedule a daily task called 'research_digest' at 08:00 with the message: Search for news on these topics: (1) Kubernetes security, (2) Rust releases, (3) Python ecosystem. For each topic, compare against previous reports. Send a combined digest with sections per topic. Skip topics with no new findings."
```

### Adjust search depth
By default, `web_search` returns 5 results. For more thorough research, mention it in the task message:

```
...Search with num_results=10 to cast a wider net...
```

### Time-filtered searches
The web_search tool supports time ranges:

```
...Search for news from the last week using time_range="week"...
```

### Track specific projects
For project-specific monitoring (e.g., a GitHub repo's releases):

```bash
radar ask "Schedule a weekly task called 'track_ollama' on mon at 08:00 with the message: Search for Ollama releases, changelog updates, and notable new features. Check what was previously reported and only include new information."
```

### Combine with the Daily Briefing
Add a news section to the Colonel Potter morning briefing personality:

```markdown
6. **News** — Search for headlines on my key topics. Keep it to the 2-3 most notable items from the past 24 hours.
```

### Memory cleanup
Over time, the `remember` calls accumulate digests in semantic memory. This is generally fine — older memories have lower similarity scores and naturally fall out of recall results. If you want to clean up:

```bash
# Check how many research memories exist
radar ask "Recall all research digest entries"

# The LLM can see the volume and decide what to prune
radar ask "Forget research digest entries older than 30 days"
```

## Search Provider Notes

| Provider | Pros | Cons |
|----------|------|------|
| **DuckDuckGo** | Free, no API key | Rate limited, less reliable for programmatic use |
| **Brave Search** | 2,000 free queries/month, reliable | Needs API key |
| **SearXNG** | Self-hosted, no limits | Requires running your own instance |

For scheduled research tasks that run daily, Brave Search is recommended. DuckDuckGo may hit rate limits with multiple daily topics.

Configure Brave:
```yaml
search:
  provider: brave
```
```bash
export RADAR_BRAVE_API_KEY=your-key-here
```

## Troubleshooting

**Search returns no results:**
- Check search provider config: `radar config`
- Test manually: `radar ask "Search for Python news"`
- DuckDuckGo may be rate-limiting — try Brave

**Same stories keep appearing:**
- The `recall`/`remember` loop may not be working. Check embedding model: `radar status`
- Look at stored memories: `radar ask "Recall research digest entries"`
- The LLM may need stronger dedup instructions — edit the personality to be more specific

**Too many notifications:**
- Reduce to weekly schedule for less critical topics
- Add to personality: "Only report findings that are genuinely significant. Skip minor updates and incremental news."
- Combine multiple topics into one digest

**Memory growing too large:**
- This is generally not a problem — semantic search returns the most relevant memories regardless of total count
- If needed, periodically ask Radar to summarize and consolidate old digest entries
