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
from radar.config import get_config
from radar.memory import get_recent_conversations

console = Console()


def _get_pid_file() -> Path:
    """Get the path to the PID file."""
    data_dir = Path.home() / ".local" / "share" / "radar"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "radar.pid"


def _is_daemon_running() -> tuple[bool, int | None]:
    """Check if daemon is running, returns (running, pid)."""
    pid_file = _get_pid_file()
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
def ask(question: tuple[str, ...]):
    """Ask a one-shot question and get a response."""
    from radar.agent import ask as agent_ask

    user_input = " ".join(question)

    try:
        with console.status("[bold blue]Thinking...", spinner="dots"):
            response = agent_ask(user_input)

        if response:
            console.print(Markdown(response))
        else:
            console.print("[yellow]No response received[/yellow]")

    except RuntimeError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise SystemExit(1)


@cli.command()
@click.option("--continue", "-c", "continue_id", help="Continue a previous conversation by ID")
def chat(continue_id: str | None):
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
                    response, conversation_id = run(user_input, conversation_id)
            else:
                response, conversation_id = run(user_input, conversation_id)

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
    console.print("[bold]Ollama:[/bold]")
    console.print(f"  Base URL: {cfg.ollama.base_url}")
    console.print(f"  Model: {cfg.ollama.model}")
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
    from radar.web.routes import run_server

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
    pid_file = _get_pid_file()
    pid_file.write_text(str(os.getpid()))

    console.print(Panel.fit(
        f"[bold blue]Radar[/bold blue] - Starting Daemon\n"
        f"[dim]Web UI: http://{host}:{port}[/dim]",
        border_style="blue",
    ))

    try:
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
        _get_pid_file().unlink(missing_ok=True)


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


if __name__ == "__main__":
    cli()
