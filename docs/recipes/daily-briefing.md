# Daily Briefing ("Chief of Staff")

A morning briefing delivered to your phone every day at 7am. Checks your calendar, weather, GitHub activity, and remembered deadlines, then compiles everything into a single push notification.

## Prerequisites

- **Radar daemon running** (`radar start` or `radar service install`)
- **ntfy configured** for push notifications (topic set in `radar.yaml` or via `RADAR_NTFY_TOPIC`)
- **khal configured** for calendar access (optional but recommended)
- **gh CLI** installed and authenticated (optional, for GitHub section)
- **Weather location saved** — tell Radar "My weather location is Seattle" once, or it will skip the weather section
- **Embedding model available** — needed for `recall` (remembering deadlines)

## Personality File

Save this to `~/.local/share/radar/personalities/colonel_potter.md`:

```markdown
---
model: qwen3:latest
tools:
  include:
    - calendar
    - weather
    - github
    - recall
    - notify
    - web_search
---

# Colonel Potter

Steady, thorough, starts the day with a clear-eyed assessment of the situation.

## Instructions

You are Colonel Potter — experienced, no-nonsense, and dependable. You give clear, organized briefings without wasting anyone's time. You care about your people and make sure nothing falls through the cracks.

When running a morning briefing, follow this sequence:

1. **Calendar** — Check today's events and tomorrow's events. Note any meetings, appointments, or deadlines.
2. **Weather** — Get the current weather and forecast. Mention anything notable (rain, extreme temperatures, storms).
3. **GitHub** — Check notifications and PRs needing review. Only include this section if there are actionable items.
4. **Deadlines** — Recall any remembered deadlines within the next 3 days. Include bill due dates, project deadlines, or reminders.
5. **Compile & Send** — Put it all together in a single notification.

Format the briefing as a concise summary. Use short lines, not paragraphs. Skip any section that returns no results — don't say "No GitHub notifications" if there are none; just leave it out.

Send the briefing via notify with the title "Morning Briefing" and default priority. If there's something urgent (meeting in the next hour, deadline today, severe weather), use priority "high".

If a tool fails (khal not installed, gh not authenticated, etc.), skip that section silently and continue with the rest.

Current time: {{ current_time }}
Today is {{ day_of_week }}, {{ current_date }}.
```

## Configuration

Add to your `radar.yaml`:

```yaml
# Set the active personality
personality: colonel_potter

# Notification settings
notifications:
  url: https://ntfy.sh       # Or your self-hosted instance
  topic: your-topic-here      # Your ntfy topic

# Heartbeat settings
heartbeat:
  interval_minutes: 15
  quiet_hours_start: "23:00"
  quiet_hours_end: "06:45"   # End before the briefing fires
```

## Setup Steps

1. **Create the personality file:**
   ```bash
   radar personality create colonel_potter
   # Then paste the personality content above, or:
   # Copy it directly to ~/.local/share/radar/personalities/colonel_potter.md
   ```

2. **Set it as active:**
   ```bash
   radar personality use colonel_potter
   ```

3. **Configure ntfy** in `radar.yaml` (see Configuration above).

4. **Start the daemon:**
   ```bash
   radar start
   ```

5. **Create the scheduled task** via chat or directly:
   ```bash
   radar ask "Schedule a daily task called 'morning_briefing' at 07:00 with the message: Run the morning briefing. Check my calendar for today and tomorrow. Get the weather. Check GitHub notifications and PRs needing my review. Recall any deadlines within 3 days. Compile everything into a concise briefing and send it via notify with the title Morning Briefing."
   ```

   Or interactively:
   ```bash
   radar chat
   > Schedule a daily task at 7am called "morning_briefing". The message should be:
   > "Run the morning briefing. Check today's and tomorrow's calendar. Get the weather.
   > Check GitHub notifications and PRs. Recall deadlines within 3 days. Send a compiled
   > briefing via notify with title 'Morning Briefing'."
   ```

6. **Test it:**
   ```bash
   radar heartbeat   # Trigger a manual heartbeat to test
   ```

## How It Works

The tool chain executes in sequence during a heartbeat:

```
schedule_task fires at 07:00
  |
  v
calendar(operation="today")        -> Today's events
calendar(operation="tomorrow")     -> Tomorrow's events
weather()                          -> Current conditions + forecast
github(operation="notifications")  -> Unread notifications
github(operation="prs")            -> PRs needing review
recall("deadlines due soon")       -> Remembered deadlines
  |
  v
LLM compiles results into briefing text
  |
  v
notify(message=briefing, title="Morning Briefing")
  |
  v
Push notification arrives on your phone
```

The heartbeat daemon checks for due scheduled tasks every `interval_minutes`. When the `morning_briefing` task is due, it injects the task message into the heartbeat event queue. The agent receives the message along with the personality instructions and executes the tool chain.

## Customization

### Change the briefing time
```bash
radar ask "Cancel the morning_briefing task"
radar ask "Schedule a daily task called 'morning_briefing' at 06:30 with the message: ..."
```

### Skip weekends
Use a weekly schedule instead of daily:
```bash
radar ask "Schedule a weekly task called 'morning_briefing' on mon,tue,wed,thu,fri at 07:00 with the message: ..."
```

### Add more sections
Edit the personality to include additional tool calls. For example, add web search for morning news:

```markdown
6. **News** — Search the web for top headlines relevant to my interests. Keep it to 2-3 items.
```

### Shorter briefing
Adjust the personality instructions to be more terse:

```markdown
Keep the entire briefing under 500 characters. Use abbreviations. Skip weather unless rain or extreme temperatures.
```

### Multiple notifications vs. one combined
The default sends one combined notification. If you prefer separate notifications per section, change the personality instructions:

```markdown
Send each section as a separate notification: one for calendar, one for weather, etc. Use the section name as the notification title.
```

## Troubleshooting

**No notification arrives:**
- Check `radar status` — is the daemon running?
- Check `radar.yaml` — is `notifications.topic` set?
- Try `radar ask "Send a test notification via notify"` to verify ntfy works
- Check `~/.local/share/radar/radar.log` for errors

**Calendar section missing:**
- Verify khal is installed: `khal printcalendars`
- The personality skips failed tools silently, so khal errors won't break the briefing

**GitHub section missing:**
- Verify gh is authenticated: `gh auth status`
- The personality only includes GitHub when there are actionable items

**Briefing is too long for a phone notification:**
- ntfy truncates long messages on some platforms
- Add to the personality: "Keep the briefing under 1000 characters"
- Or switch to ntfy's markdown mode if your client supports it

**LLM doesn't chain all tools:**
- Some models stop after 3-4 tool calls. If using `qwen3:latest`, this should work reliably
- Check `~/.local/share/radar/radar.log` for the heartbeat conversation
- Consider splitting into multiple scheduled tasks if the model can't handle 6-7 calls in sequence
