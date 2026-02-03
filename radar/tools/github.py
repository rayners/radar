"""GitHub tool using gh CLI."""

import json
import subprocess
from datetime import datetime, timezone

from radar.semantic import is_embedding_available, search_memories, store_memory
from radar.tools import tool


def _get_remembered_org() -> str | None:
    """Search semantic memory for stored GitHub organization preference."""
    if not is_embedding_available():
        return None

    try:
        memories = search_memories("github organization default org", limit=3)
        for memory in memories:
            content = memory["content"].lower()
            if "github" in content and "organization" in content:
                if memory["similarity"] > 0.5:
                    # Try to extract org name
                    raw = memory["content"]
                    for marker in ["organization is ", "org is "]:
                        if marker in raw.lower():
                            idx = raw.lower().find(marker) + len(marker)
                            return raw[idx:].strip().rstrip(".")
        return None
    except Exception:
        return None


def _run_gh(args: list[str]) -> tuple[str, bool]:
    """Run a gh CLI command.

    Args:
        args: Command arguments (without 'gh' prefix)

    Returns:
        Tuple of (output, success)
    """
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip()
            return error, False
        return result.stdout, True
    except FileNotFoundError:
        return "Error: gh CLI not installed. Install from https://cli.github.com/", False
    except subprocess.TimeoutExpired:
        return "Error: Command timed out", False
    except Exception as e:
        return f"Error: {e}", False


def _format_relative_time(iso_time: str) -> str:
    """Format ISO time as relative time string."""
    try:
        dt = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt

        if delta.days > 7:
            weeks = delta.days // 7
            return f"{weeks} week{'s' if weeks > 1 else ''} ago"
        elif delta.days > 0:
            return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return "just now"
    except Exception:
        return iso_time


def _list_prs(org: str | None, repo: str | None) -> str:
    """List PRs authored by, assigned to, or requesting review from user."""
    lines = ["**Pull Requests**", ""]

    # For repo-specific queries, use gh pr list; for global, use gh search prs
    if repo:
        # Repo-specific: use gh pr list
        for label, search in [
            ("Review Requested", "review-requested:@me"),
            ("Assigned", "assignee:@me"),
            ("Authored", "author:@me"),
        ]:
            args = ["pr", "list", "--repo", repo, "--search", search, "--json", "number,title,createdAt,url", "--limit", "10"]
            output, success = _run_gh(args)
            if success:
                try:
                    prs = json.loads(output)
                    if prs:
                        lines.append(f"**{label}:**")
                        for pr in prs:
                            num = pr.get("number")
                            title = pr.get("title", "")
                            created = _format_relative_time(pr.get("createdAt", ""))
                            lines.append(f"- #{num} {title} ({repo}) - opened {created}")
                        lines.append("")
                except json.JSONDecodeError:
                    pass
    else:
        # Global search: use gh search prs
        for label, flag in [
            ("Review Requested", "--review-requested=@me"),
            ("Assigned", "--assignee=@me"),
            ("Authored", "--author=@me"),
        ]:
            args = ["search", "prs", flag, "--state=open", "--json", "number,title,repository,createdAt", "--limit", "10"]
            output, success = _run_gh(args)
            if success:
                try:
                    prs = json.loads(output)
                    if org:
                        prs = [pr for pr in prs if org.lower() in pr.get("repository", {}).get("nameWithOwner", "").lower()]

                    if prs:
                        lines.append(f"**{label}:**")
                        for pr in prs:
                            num = pr.get("number")
                            title = pr.get("title", "")
                            repo_name = pr.get("repository", {}).get("nameWithOwner", "")
                            created = _format_relative_time(pr.get("createdAt", ""))
                            lines.append(f"- #{num} {title} ({repo_name}) - opened {created}")
                        lines.append("")
                except json.JSONDecodeError:
                    pass

    if len(lines) == 2:  # Only header
        lines.append("No PRs found.")

    return "\n".join(lines)


def _list_issues(org: str | None, repo: str | None) -> str:
    """List issues assigned to user or mentioning them."""
    lines = ["**Issues**", ""]

    if repo:
        # Repo-specific: use gh issue list
        for label, search in [
            ("Assigned", "assignee:@me"),
            ("Mentioned", "mentions:@me"),
        ]:
            args = ["issue", "list", "--repo", repo, "--search", search, "--json", "number,title,createdAt,url", "--limit", "10"]
            output, success = _run_gh(args)
            if success:
                try:
                    issues = json.loads(output)
                    if issues:
                        lines.append(f"**{label}:**")
                        for issue in issues:
                            num = issue.get("number")
                            title = issue.get("title", "")
                            created = _format_relative_time(issue.get("createdAt", ""))
                            lines.append(f"- #{num} {title} ({repo}) - opened {created}")
                        lines.append("")
                except json.JSONDecodeError:
                    pass
    else:
        # Global search: use gh search issues
        for label, flag in [
            ("Assigned", "--assignee=@me"),
            ("Mentioned", "--mentions=@me"),
        ]:
            args = ["search", "issues", flag, "--state=open", "--json", "number,title,repository,createdAt", "--limit", "10"]
            output, success = _run_gh(args)
            if success:
                try:
                    issues = json.loads(output)
                    if org:
                        issues = [issue for issue in issues if org.lower() in issue.get("repository", {}).get("nameWithOwner", "").lower()]

                    if issues:
                        lines.append(f"**{label}:**")
                        for issue in issues:
                            num = issue.get("number")
                            title = issue.get("title", "")
                            repo_name = issue.get("repository", {}).get("nameWithOwner", "")
                            created = _format_relative_time(issue.get("createdAt", ""))
                            lines.append(f"- #{num} {title} ({repo_name}) - opened {created}")
                        lines.append("")
                except json.JSONDecodeError:
                    pass

    if len(lines) == 2:  # Only header
        lines.append("No issues found.")

    return "\n".join(lines)


def _get_notifications() -> str:
    """Get unread notifications."""
    output, success = _run_gh(["api", "notifications", "--jq", ".[] | {reason, subject, repository: .repository.full_name, updated_at}"])

    if not success:
        return f"Error fetching notifications: {output}"

    if not output.strip():
        return "**Notifications**\n\nNo unread notifications."

    lines = ["**Notifications**", ""]

    try:
        # Parse line-by-line JSON objects
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            notif = json.loads(line)
            reason = notif.get("reason", "unknown")
            subject = notif.get("subject", {})
            title = subject.get("title", "")
            notif_type = subject.get("type", "")
            repo = notif.get("repository", "")
            updated = _format_relative_time(notif.get("updated_at", ""))

            lines.append(f"- [{notif_type}] {title} ({repo}) - {reason}, {updated}")
    except json.JSONDecodeError:
        # Fallback to raw output
        lines.append(output)

    return "\n".join(lines)


def _get_status(repo: str | None) -> str:
    """Get PR status and recent CI runs."""
    lines = ["**Status**", ""]

    # PR status in current repo
    if repo:
        args = ["pr", "status", "--repo", repo]
    else:
        args = ["pr", "status"]

    output, success = _run_gh(args)
    if success:
        lines.append("**PR Status:**")
        lines.append(output.strip())
        lines.append("")

    # Recent workflow runs
    if repo:
        args = ["run", "list", "--repo", repo, "--limit", "5"]
    else:
        args = ["run", "list", "--limit", "5"]

    output, success = _run_gh(args)
    if success and output.strip():
        lines.append("**Recent CI Runs:**")
        lines.append(output.strip())

    return "\n".join(lines)


@tool(
    name="github",
    description="Query GitHub for PRs, issues, notifications, and CI status. Requires gh CLI to be installed and authenticated.",
    parameters={
        "operation": {
            "type": "string",
            "description": "One of: prs, issues, notifications, status",
        },
        "org": {
            "type": "string",
            "description": "Filter by organization (optional, uses remembered org if saved)",
            "optional": True,
        },
        "save_org": {
            "type": "boolean",
            "description": "Remember this org as default filter (default: false)",
            "optional": True,
        },
        "repo": {
            "type": "string",
            "description": "Specific repository (owner/repo format, optional)",
            "optional": True,
        },
    },
)
def github(
    operation: str,
    org: str | None = None,
    save_org: bool = False,
    repo: str | None = None,
) -> str:
    """Query GitHub for PRs, issues, notifications.

    Args:
        operation: One of 'prs', 'issues', 'notifications', 'status'
        org: Organization to filter by
        save_org: Whether to save org as default
        repo: Specific repo (owner/repo)

    Returns:
        Formatted GitHub information
    """
    # Check for gh CLI
    output, success = _run_gh(["--version"])
    if not success:
        return output  # Error message about gh not being installed

    # If no org provided, check memory
    if not org:
        org = _get_remembered_org()

    # Save org if requested
    if save_org and org and is_embedding_available():
        try:
            store_memory(f"My default GitHub organization is {org}", source="github")
        except Exception:
            pass

    # Execute operation
    operation = operation.lower().strip()

    if operation == "prs":
        return _list_prs(org, repo)
    elif operation == "issues":
        return _list_issues(org, repo)
    elif operation == "notifications":
        return _get_notifications()
    elif operation == "status":
        return _get_status(repo)
    else:
        return f"Unknown operation: {operation}. Use one of: prs, issues, notifications, status"
