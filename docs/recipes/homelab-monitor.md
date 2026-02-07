# Homelab Monitor ("System Watchdog")

Periodic health checks on your system: disk usage, memory, Docker containers, and load average. Only notifies you when something is wrong, with escalating priority for critical issues.

## Prerequisites

- **Radar daemon running** (`radar start` or `radar service install`)
- **ntfy configured** for push notifications
- **`exec_mode: block_dangerous`** in `radar.yaml` (default) — allows diagnostic commands like `df`, `free`, `docker ps`
- **Docker installed** (optional, for container monitoring)

## Personality File

Save this to `~/.local/share/radar/personalities/klinger.md`:

```markdown
---
model: qwen3:latest
tools:
  include:
    - exec
    - recall
    - remember
    - notify
---

# Klinger

Meticulous attention to detail and dramatic escalation when things go wrong.

## Instructions

You are Klinger — organized, detail-oriented, and never afraid to sound the alarm when the situation calls for it. You keep meticulous records and notice when something is out of place.

When running a system health check, follow this sequence:

1. **Disk Usage** — Run `df -h --output=target,pcent,avail -x tmpfs -x devtmpfs` to check all real filesystems.
2. **Memory** — Run `free -h` to check RAM and swap usage.
3. **Load Average** — Run `uptime` to check system load.
4. **Docker Containers** — Run `docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.RunningFor}}'` to check container status. If docker is not available, skip this step.
5. **Evaluate & Report** — Only notify if something is wrong.

### Threshold Rules

Apply these thresholds when evaluating results:

- **Disk**: warn at 85% used, critical at 95% used
- **Memory**: warn if less than 500MB available, critical if less than 200MB
- **Swap**: warn if any swap is in use (indicates memory pressure)
- **Load**: warn if 1-minute load average exceeds the CPU count (check with `nproc`), critical if it exceeds 2x CPU count
- **Docker**: warn if any container is "unhealthy" or has restarted in the last hour

### Notification Rules

- **Everything OK**: Do NOT send a notification. Silence is golden.
- **Warning-level issues**: Send a notification with priority "default" and title "System Check: Warning".
- **Critical issues**: Send a notification with priority "high" and title "System Check: Critical".
- **Multiple issues**: Combine into a single notification. Use the highest severity for priority.

### Deduplication

Before notifying, recall what you last reported about system health. If the same issue was already reported and hasn't changed significantly (e.g., disk went from 87% to 88%), do NOT re-alert. Only re-alert if:
- A warning escalated to critical (e.g., disk went from 87% to 96%)
- A new issue appeared that wasn't in the last report
- The previous alert was more than 6 hours ago

After sending a notification, remember what you reported so you can deduplicate next time.

### Output Format

Keep notifications concise. Example:

```
Disk: /home at 91% (warning)
Docker: postgres-db restarted 3 times in last hour
Load: 8.2 on 4 cores (2x threshold)
```

Current time: {{ current_time }}
Today is {{ day_of_week }}, {{ current_date }}.
```

## Configuration

Add to your `radar.yaml`:

```yaml
# Personality
personality: klinger

# Exec mode must allow diagnostic commands
tools:
  exec_mode: block_dangerous    # This is the default

# Notification settings
notifications:
  url: https://ntfy.sh
  topic: your-topic-here

# Heartbeat — the monitor runs on this interval
heartbeat:
  interval_minutes: 15
  quiet_hours_start: "23:00"
  quiet_hours_end: "07:00"
```

## Setup Steps

1. **Create the personality file:**
   ```bash
   radar personality create klinger
   # Then paste the personality content above
   ```

2. **Set it as active:**
   ```bash
   radar personality use klinger
   ```

3. **Create the scheduled task:**
   ```bash
   radar ask "Schedule an interval task called 'system_check' every 15 minutes with the message: Run a system health check. Check disk usage, memory, load average, and Docker container status. Only notify me if something exceeds thresholds or a new issue appeared."
   ```

   For less frequent checks (hourly):
   ```bash
   radar ask "Schedule an interval task called 'system_check' every 60 minutes with the message: Run a system health check. Check disk, memory, load, and Docker. Only notify if something is wrong."
   ```

4. **Test it:**
   ```bash
   radar heartbeat
   ```

## How It Works

```
schedule_task fires every N minutes
  |
  v
exec("df -h ...")       -> Disk usage
exec("free -h")         -> Memory stats
exec("uptime")          -> Load average
exec("docker ps ...")   -> Container status
  |
  v
LLM evaluates against thresholds
  |
  v
recall("last system health report")   -> Previous alert (for dedup)
  |
  +--> Everything OK? -> Do nothing (silent)
  |
  +--> Issue found?
        |
        v
        remember("System health report: disk /home at 91%, ...")
        notify(message=report, title="System Check: Warning", priority="default")
          or
        notify(message=report, title="System Check: Critical", priority="high")
```

## Allowed Commands

These diagnostic commands are safe in `block_dangerous` mode (not on the blocked list):

| Command | What it checks |
|---------|----------------|
| `df -h` | Disk usage by filesystem |
| `free -h` | RAM and swap usage |
| `uptime` | Load average and uptime |
| `docker ps` | Running container status |
| `docker ps -a` | All containers including stopped |
| `docker logs --tail 20 <name>` | Recent container logs |
| `nproc` | CPU count (for load threshold) |
| `systemctl --user status radar` | Radar service health |
| `du -sh /path` | Directory size |

Commands that are **blocked** (won't work in `block_dangerous` mode):

| Blocked | Why |
|---------|-----|
| `curl`, `wget` | Network exfiltration risk |
| `sudo` | Privilege escalation |
| `kill`, `killall` | Process termination |
| `rm -rf` | Destructive operations |
| `ssh` | Remote access |

## Customization

### Monitor remote hosts
The default setup only monitors the local machine. To monitor remote hosts, you'd need SSH access — which is blocked in `block_dangerous` mode for security. Options:
- Run a separate Radar instance on each host
- Set `exec_mode: allow_all` (not recommended unless you trust the LLM completely)
- Create a plugin that uses a monitoring API instead of shell commands

### Different thresholds
Edit the personality file to adjust the threshold numbers. For example, on a system with lots of RAM:

```markdown
- **Memory**: warn if less than 2GB available, critical if less than 500MB
```

### Monitor specific Docker containers
Add to the personality:

```markdown
Pay special attention to these containers: postgres, redis, nginx. If any of these are not running, treat it as critical.
```

### Add Docker log monitoring
For deeper container inspection, add to the personality:

```markdown
6. **Docker Logs** — For any unhealthy or recently restarted container, run `docker logs --tail 30 <container_name>` and look for error patterns (exceptions, connection refused, out of memory).
```

### Silence during maintenance
To temporarily suppress alerts:
```bash
radar ask "Remember: system maintenance in progress until 2025-01-15 18:00. Suppress system health alerts until then."
```

The personality's dedup logic using `recall` will pick this up and skip notifications.

### Combine with the Daily Briefing
If you're also using the Daily Briefing recipe, you can include a system health summary in the morning notification. Add to the Colonel Potter personality:

```markdown
5. **System Health** — Run `df -h` and `free -h`. Only mention if disk is above 80% or memory is low.
```

## Troubleshooting

**`exec` tool returns "Error: Command not in safe list":**
- You're in `safe_only` mode. Change to `block_dangerous` in `radar.yaml`:
  ```yaml
  tools:
    exec_mode: block_dangerous
  ```

**Docker commands fail:**
- Ensure your user is in the `docker` group: `groups | grep docker`
- Or use rootless Docker

**Too many alerts (alert fatigue):**
- Increase the check interval: change `interval_minutes` to 60
- Raise the thresholds in the personality
- Add stronger dedup instructions: "Only re-alert if 12 hours have passed"

**Alerts not arriving:**
- Check `radar status` — is the daemon running?
- Check `~/.local/share/radar/radar.log` for heartbeat errors
- Try a manual test: `radar ask "Check disk usage with df -h and tell me the result"`
