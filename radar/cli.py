"""CLI interface for Radar."""

import sys

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from radar import __version__
from radar.config import get_config
from radar.memory import get_recent_conversations

console = Console()


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


if __name__ == "__main__":
    cli()
