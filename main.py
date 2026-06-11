#!/usr/bin/env python3
"""My Computer CLI."""

import json
import os

import click
import httpx
from rich.console import Console
from rich.table import Table

from sdk import MyComputerClient

console = Console()
DEFAULT_BASE_URL = os.getenv("MY_COMPUTER_URL", "http://localhost:8000")


def _resolve_client(
    base_url: str,
    user: str | None,
    api_key: str | None,
    token: str | None,
) -> MyComputerClient:
    client = MyComputerClient(base_url=base_url)
    if api_key:
        client.set_api_key(api_key)
    elif token:
        client.set_token(token)
    elif user:
        password = os.getenv("MY_COMPUTER_PASSWORD")
        if not password:
            raise click.ClickException(
                "Set MY_COMPUTER_PASSWORD env var or use --api-key / --token"
            )
        client.login(user, password)
    return client


@click.group()
@click.option("--base-url", default=DEFAULT_BASE_URL, envvar="MY_COMPUTER_URL")
@click.pass_context
def cli(ctx: click.Context, base_url: str) -> None:
    """My Computer – multi-agent AI orchestrator CLI."""
    ctx.ensure_object(dict)
    ctx.obj["base_url"] = base_url


@cli.command()
@click.option("--email", prompt=True)
@click.option("--username", prompt=True)
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
@click.option("--base-url", default=DEFAULT_BASE_URL)
def register(email: str, username: str, password: str, base_url: str) -> None:
    """Register a new user account."""
    client = MyComputerClient(base_url=base_url)
    tokens = client.register(email, username, password)
    console.print("[green]Registration successful[/green]")
    console.print(f"Access token: {tokens['access_token'][:20]}...")


@cli.command()
@click.option("--email", prompt=True)
@click.option("--password", prompt=True, hide_input=True)
@click.option("--base-url", default=DEFAULT_BASE_URL)
def login(email: str, password: str, base_url: str) -> None:
    """Login and print tokens."""
    client = MyComputerClient(base_url=base_url)
    tokens = client.login(email, password)
    console.print("[green]Login successful[/green]")
    console.print(json.dumps(tokens, indent=2))


@cli.command("run")
@click.argument("goal")
@click.option("--mode", default="ensemble", type=click.Choice(["ensemble", "single", "parallel"]))
@click.option("--user", default=None, help="User email for login (uses MY_COMPUTER_PASSWORD)")
@click.option("--api-key", default=None, envvar="MY_COMPUTER_API_KEY", help="API key (X-API-Key)")
@click.option("--token", default=None, envvar="MY_COMPUTER_TOKEN", help="Bearer access token")
@click.option("--json-output", is_flag=True, help="Output raw JSON")
@click.pass_context
def run_goal(
    ctx: click.Context,
    goal: str,
    mode: str,
    user: str | None,
    api_key: str | None,
    token: str | None,
    json_output: bool,
) -> None:
    """Run a goal through the orchestrator."""
    client = _resolve_client(ctx.obj["base_url"], user, api_key, token)
    result = client.run_goal(goal, mode=mode)
    if json_output:
        console.print_json(data=result)
    else:
        console.print(f"\n[bold]Status:[/bold] {result.get('status')}")
        console.print(f"[bold]Tokens:[/bold] {result.get('tokens_used', 0)}")
        synthesis = (result.get("result") or {}).get("synthesis", "")
        if synthesis:
            console.print(f"\n[bold]Synthesis:[/bold]\n{synthesis}")


@cli.command("timeline")
@click.option("--goal-id", default=None)
@click.option("--limit", default=20)
@click.option("--user", default=None)
@click.option("--api-key", default=None, envvar="MY_COMPUTER_API_KEY")
@click.option("--token", default=None, envvar="MY_COMPUTER_TOKEN")
@click.pass_context
def memory_timeline(
    ctx: click.Context,
    goal_id: str | None,
    limit: int,
    user: str | None,
    api_key: str | None,
    token: str | None,
) -> None:
    """Show episodic memory timeline."""
    client = _resolve_client(ctx.obj["base_url"], user, api_key, token)
    data = client.get_memory_timeline(goal_id=goal_id, limit=limit)

    table = Table(title="Memory Timeline")
    table.add_column("Time", style="dim")
    table.add_column("Step")
    table.add_column("Content")

    for item in data.get("items", []):
        table.add_row(
            item["created_at"][:19],
            item["step_type"],
            item["content"][:80] + ("..." if len(item["content"]) > 80 else ""),
        )
    console.print(table)


@cli.command()
@click.option("--base-url", default=DEFAULT_BASE_URL)
def health(base_url: str) -> None:
    """Check server health."""
    response = httpx.get(f"{base_url}/health", timeout=10)
    console.print_json(data=response.json())


@cli.command("api-key")
@click.argument("name")
@click.option("--user", default=None)
@click.option("--api-key", default=None, envvar="MY_COMPUTER_API_KEY")
@click.option("--token", default=None, envvar="MY_COMPUTER_TOKEN")
@click.pass_context
def create_api_key(
    ctx: click.Context,
    name: str,
    user: str | None,
    api_key: str | None,
    token: str | None,
) -> None:
    """Create a new API key."""
    client = _resolve_client(ctx.obj["base_url"], user, api_key, token)
    result = client.create_api_key(name)
    console.print("[green]API key created – save it now, it won't be shown again:[/green]")
    console.print(result["key"])


if __name__ == "__main__":
    cli()