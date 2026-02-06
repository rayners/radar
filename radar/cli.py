"""CLI interface for Radar."""

import os
import signal
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from radar import __version__
from radar.config import get_config, get_data_paths
from radar.memory import get_recent_conversations

console = Console()


def _is_daemon_running() -> tuple[bool, int | None]:
    """Check if daemon is running, returns (running, pid)."""
    pid_file = get_data_paths().pid_file
    if not pid_file.exists():
        return False, None

    try:
        pid = int(pid_file.read_text().strip())
        # Check if process exists
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, PermissionError):
        # PID file is stale
        pid_file.unlink(missing_ok=True)
        return False, None


@click.group()
@click.version_option(version=__version__)
def cli():
    """Radar - A local AI assistant with Ollama tool calling."""
    pass


@cli.command()
@click.argument("question", nargs=-1, required=True)
@click.option("--personality", "-P", help="Use a specific personality for this request")
def ask(question: tuple[str, ...], personality: str | None):
    """Ask a one-shot question and get a response."""
    from radar.agent import ask as agent_ask

    user_input = " ".join(question)

    try:
        with console.status("[bold blue]Thinking...", spinner="dots"):
            response = agent_ask(user_input, personality=personality)

        if response:
            console.print(Markdown(response))
        else:
            console.print("[yellow]No response received[/yellow]")

    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command()
@click.option("--continue", "-c", "continue_id", help="Continue a previous conversation by ID")
@click.option("--personality", "-P", help="Use a specific personality for this session")
def chat(continue_id: str | None, personality: str | None):
    """Start an interactive chat session."""
    from radar.agent import run

    conversation_id = continue_id
    is_interactive = sys.stdin.isatty()

    if is_interactive:
        console.print(
            Panel.fit(
                "[bold blue]Radar[/bold blue] - Interactive Chat\n"
                "[dim]Type 'exit' or 'quit' to end, 'clear' to start new conversation[/dim]",
                border_style="blue",
            )
        )

        if conversation_id:
            console.print(f"[dim]Continuing conversation: {conversation_id[:8]}...[/dim]\n")
        else:
            console.print()

    while True:
        try:
            if is_interactive:
                user_input = console.input("[bold green]You:[/bold green] ").strip()
            else:
                line = sys.stdin.readline()
                if not line:  # EOF reached
                    break
                user_input = line.strip()
        except (KeyboardInterrupt, EOFError):
            if is_interactive:
                console.print("\n[dim]Goodbye![/dim]")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            if is_interactive:
                console.print("[dim]Goodbye![/dim]")
            break

        if user_input.lower() == "clear":
            conversation_id = None
            if is_interactive:
                console.print("[dim]Starting new conversation[/dim]\n")
            continue

        try:
            if is_interactive:
                with console.status("[bold blue]Thinking...", spinner="dots"):
                    response, conversation_id = run(user_input, conversation_id, personality=personality)
            else:
                response, conversation_id = run(user_input, conversation_id, personality=personality)

            if is_interactive:
                console.print()
            if response:
                if is_interactive:
                    console.print("[bold blue]Radar:[/bold blue]")
                console.print(Markdown(response))
            else:
                console.print("[yellow]No response received[/yellow]")
            if is_interactive:
                console.print()

        except RuntimeError as e:
            console.print(f"\n[red]Error: {e}[/red]\n")


@cli.command()
def config():
    """Show current configuration."""
    cfg = get_config()

    console.print(Panel.fit("[bold]Radar Configuration[/bold]", border_style="blue"))
    console.print()
    console.print("[bold]LLM:[/bold]")
    console.print(f"  Provider: {cfg.llm.provider}")
    console.print(f"  Base URL: {cfg.llm.base_url}")
    console.print(f"  Model: {cfg.llm.model}")
    console.print(f"  API Key: {'[dim](set)[/dim]' if cfg.llm.api_key else '[dim](not set)[/dim]'}")
    console.print()
    console.print("[bold]Embedding:[/bold]")
    console.print(f"  Provider: {cfg.embedding.provider}")
    if cfg.embedding.provider != "none":
        console.print(f"  Model: {cfg.embedding.model}")
        if cfg.embedding.base_url:
            console.print(f"  Base URL: {cfg.embedding.base_url}")
    console.print()
    console.print("[bold]Notifications:[/bold]")
    console.print(f"  URL: {cfg.notifications.url}")
    console.print(f"  Topic: {cfg.notifications.topic or '[dim](not set)[/dim]'}")
    console.print()
    console.print("[bold]Tools:[/bold]")
    console.print(f"  Max file size: {cfg.tools.max_file_size} bytes")
    console.print(f"  Exec timeout: {cfg.tools.exec_timeout}s")
    console.print()
    console.print(f"[bold]Max tool iterations:[/bold] {cfg.max_tool_iterations}")


@cli.command()
@click.option("--limit", "-n", default=5, help="Number of conversations to show")
def history(limit: int):
    """Show recent conversations."""
    conversations = get_recent_conversations(limit)

    if not conversations:
        console.print("[dim]No conversations yet[/dim]")
        return

    console.print(Panel.fit("[bold]Recent Conversations[/bold]", border_style="blue"))
    console.print()

    for conv in conversations:
        preview = conv["preview"] or "[dim](empty)[/dim]"
        if len(preview) > 60:
            preview = preview[:60] + "..."
        console.print(f"[bold]{conv['id'][:8]}[/bold] [{conv['created_at']}]")
        console.print(f"  {preview}")
        console.print()


@cli.command()
@click.option("--host", "-h", default=None, help="Host to bind to (default: from config or 127.0.0.1)")
@click.option("--port", "-p", default=None, type=int, help="Port to bind to (default: from config or 8420)")
def start(host: str | None, port: int | None):
    """Start Radar daemon (scheduler + web server)."""
    from radar.scheduler import start_scheduler
    from radar.watchers import start_watchers
    from radar.web import run_server

    config = get_config()

    # Use CLI args if provided, otherwise fall back to config
    # Also update the config so middleware can check the actual host
    if host:
        config.web.host = host
    else:
        host = config.web.host

    if port:
        config.web.port = port
    else:
        port = config.web.port

    # Security warning for non-localhost binding
    is_localhost = host in ("127.0.0.1", "localhost", "::1")
    if not is_localhost:
        if not config.web.auth_token:
            console.print(Panel.fit(
                "[bold red]Security Warning[/bold red]\n\n"
                f"Binding to [bold]{host}[/bold] exposes the web UI to the network.\n"
                "No auth_token is configured - access will be blocked.\n\n"
                "Add to radar.yaml:\n"
                "[dim]web:\n"
                "  auth_token: \"your-secret-token\"[/dim]\n\n"
                "Or set: [dim]RADAR_WEB_AUTH_TOKEN=your-token[/dim]",
                border_style="red",
            ))
        else:
            console.print(f"[yellow]Note: Web UI exposed on {host} (auth required)[/yellow]")

    running, pid = _is_daemon_running()
    if running:
        console.print(f"[yellow]Radar daemon already running (PID {pid})[/yellow]")
        raise SystemExit(1)

    # Write PID file
    pid_file = get_data_paths().pid_file
    pid_file.write_text(str(os.getpid()))

    console.print(Panel.fit(
        f"[bold blue]Radar[/bold blue] - Starting Daemon\n"
        f"[dim]Web UI: http://{host}:{port}[/dim]",
        border_style="blue",
    ))

    try:
        # Initialize logging
        from radar.logging import setup_logging
        setup_logging()

        # Start scheduler
        config = get_config()
        console.print(f"[dim]Starting scheduler (heartbeat every {config.heartbeat.interval_minutes} min)[/dim]")
        start_scheduler()

        # Start file watchers
        if config.watch_paths:
            console.print(f"[dim]Starting file watchers ({len(config.watch_paths)} paths)[/dim]")
            start_watchers(config.watch_paths)

        # Run web server (blocking)
        console.print(f"[green]Daemon started[/green]\n")
        run_server(host=host, port=port)
    except KeyboardInterrupt:
        console.print("\n[dim]Shutting down...[/dim]")
    finally:
        from radar.scheduler import stop_scheduler
        from radar.watchers import stop_watchers
        stop_scheduler()
        stop_watchers()
        pid_file.unlink(missing_ok=True)


@cli.command()
def stop():
    """Stop Radar daemon."""
    running, pid = _is_daemon_running()
    if not running:
        console.print("[yellow]Radar daemon is not running[/yellow]")
        raise SystemExit(1)

    console.print(f"[dim]Stopping daemon (PID {pid})...[/dim]")
    try:
        os.kill(pid, signal.SIGTERM)
        console.print("[green]Daemon stopped[/green]")
    except ProcessLookupError:
        console.print("[yellow]Process not found, removing stale PID file[/yellow]")
    finally:
        get_data_paths().pid_file.unlink(missing_ok=True)


@cli.command()
def status():
    """Show daemon status."""
    from radar.scheduler import get_status

    running, pid = _is_daemon_running()

    console.print(Panel.fit("[bold]Radar Status[/bold]", border_style="blue"))
    console.print()

    if running:
        console.print(f"[green]Daemon running[/green] (PID {pid})")
    else:
        console.print("[yellow]Daemon not running[/yellow]")
        return

    # Get scheduler status
    try:
        sched_status = get_status()
        console.print()
        console.print("[bold]Scheduler:[/bold]")
        console.print(f"  Running: {sched_status['running']}")
        console.print(f"  Last heartbeat: {sched_status['last_heartbeat'] or 'Never'}")
        console.print(f"  Next heartbeat: {sched_status['next_heartbeat'] or 'N/A'}")
        console.print(f"  Pending events: {sched_status['pending_events']}")
        console.print(f"  Quiet hours: {'Yes' if sched_status['quiet_hours'] else 'No'}")
    except Exception as e:
        console.print(f"[dim]Could not get scheduler status: {e}[/dim]")


@cli.command()
def heartbeat():
    """Trigger a manual heartbeat."""
    from radar.scheduler import trigger_heartbeat

    running, _ = _is_daemon_running()
    if not running:
        console.print("[yellow]Daemon not running. Starting one-shot heartbeat...[/yellow]")

    with console.status("[bold blue]Running heartbeat...", spinner="dots"):
        result = trigger_heartbeat()

    console.print(f"[green]{result}[/green]")


# ===== Personality Commands =====


@cli.group()
def personality():
    """Manage personality files."""
    pass


@personality.command("list")
def personality_list():
    """List available personalities."""
    from radar.agent import get_personalities_dir, DEFAULT_PERSONALITY

    # Ensure default exists
    personalities_dir = get_personalities_dir()
    default_file = personalities_dir / "default.md"
    if not default_file.exists():
        default_file.write_text(DEFAULT_PERSONALITY)

    # Get current active personality
    cfg = get_config()
    active = cfg.personality

    console.print(Panel.fit("[bold]Available Personalities[/bold]", border_style="blue"))
    console.print()

    # List all .md files in personalities directory
    personality_files = sorted(personalities_dir.glob("*.md"))

    if not personality_files:
        console.print("[dim]No personalities found[/dim]")
        return

    for pfile in personality_files:
        name = pfile.stem
        is_active = name == active or str(pfile) == active
        marker = "[green]* [/green]" if is_active else "  "
        # Get first non-empty, non-heading line as description
        content = pfile.read_text()
        description = ""
        for line in content.split("\n"):
            line = line.strip()
            if line and not line.startswith("#"):
                description = line[:60]
                if len(line) > 60:
                    description += "..."
                break
        console.print(f"{marker}[bold]{name}[/bold]")
        if description:
            console.print(f"    [dim]{description}[/dim]")


@personality.command("show")
@click.argument("name", default="")
def personality_show(name: str):
    """Display a personality file."""
    from radar.agent import get_personalities_dir, load_personality

    cfg = get_config()
    name = name or cfg.personality

    content = load_personality(name)
    console.print(Panel.fit(f"[bold]Personality: {name}[/bold]", border_style="blue"))
    console.print()
    console.print(Markdown(content))


@personality.command("edit")
@click.argument("name", default="")
def personality_edit(name: str):
    """Open a personality file in $EDITOR."""
    import subprocess

    from radar.agent import get_personalities_dir, DEFAULT_PERSONALITY

    cfg = get_config()
    name = name or cfg.personality

    personalities_dir = get_personalities_dir()
    personality_file = personalities_dir / f"{name}.md"

    # Create if it doesn't exist
    if not personality_file.exists():
        if name == "default":
            personality_file.write_text(DEFAULT_PERSONALITY)
        else:
            console.print(f"[yellow]Personality '{name}' does not exist. Creating from template...[/yellow]")
            personality_file.write_text(DEFAULT_PERSONALITY.replace("# Default", f"# {name.title()}"))

    # Get editor
    editor = os.environ.get("EDITOR", "nano")

    console.print(f"[dim]Opening {personality_file} in {editor}...[/dim]")
    subprocess.run([editor, str(personality_file)])


@personality.command("create")
@click.argument("name")
def personality_create(name: str):
    """Create a new personality from template."""
    from radar.agent import get_personalities_dir, DEFAULT_PERSONALITY

    personalities_dir = get_personalities_dir()
    personality_file = personalities_dir / f"{name}.md"

    if personality_file.exists():
        console.print(f"[red]Personality '{name}' already exists[/red]")
        raise SystemExit(1)

    # Create from template with customized name
    content = DEFAULT_PERSONALITY.replace("# Default", f"# {name.title()}")
    content = content.replace("A practical, local-first AI assistant.", f"A custom personality for {name}.")
    personality_file.write_text(content)

    console.print(f"[green]Created personality: {name}[/green]")
    console.print(f"[dim]File: {personality_file}[/dim]")
    console.print()
    console.print("Edit with: [bold]radar personality edit {name}[/bold]")
    console.print("Use with:  [bold]radar personality use {name}[/bold]")


@personality.command("use")
@click.argument("name")
def personality_use(name: str):
    """Set the active personality."""
    from radar.agent import get_personalities_dir, load_personality
    from radar.config import get_config_path

    # Verify personality exists
    personalities_dir = get_personalities_dir()
    personality_file = personalities_dir / f"{name}.md"
    path = Path(name).expanduser()

    if not personality_file.exists() and not path.exists():
        console.print(f"[red]Personality '{name}' not found[/red]")
        console.print()
        console.print("Available personalities:")
        for pfile in sorted(personalities_dir.glob("*.md")):
            console.print(f"  - {pfile.stem}")
        raise SystemExit(1)

    # Update config file
    config_path = get_config_path()
    if config_path:
        import yaml

        with open(config_path) as f:
            config_data = yaml.safe_load(f) or {}

        config_data["personality"] = name

        with open(config_path, "w") as f:
            yaml.dump(config_data, f, default_flow_style=False)

        console.print(f"[green]Active personality set to: {name}[/green]")
        console.print(f"[dim]Updated: {config_path}[/dim]")
    else:
        console.print(f"[yellow]No config file found. Set via environment:[/yellow]")
        console.print(f"  export RADAR_PERSONALITY={name}")


if __name__ == "__main__":
    cli()
