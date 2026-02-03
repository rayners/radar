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
