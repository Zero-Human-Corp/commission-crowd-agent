"""CLI entrypoint for Commission Crowd Agent.

Provides operator-facing commands for running workflows and checking status.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from .config import load_settings
from .domain import Lead
from .workflow_runner import WorkflowRunner

app = typer.Typer(help="Commission Crowd Agent CLI")
console = Console()


@app.command()
def status() -> None:
    """Show configuration readiness."""
    settings = load_settings()
    table = Table(title="CCA Configuration Status")
    table.add_column("Service", style="cyan")
    table.add_column("Ready", style="green")
    table.add_row("Ollama", "✅" if settings.ollama_ready else "❌")
    table.add_row("Telegram", "✅" if settings.telegram_ready else "❌")
    table.add_row("Google", "✅" if settings.google_ready else "❌")
    table.add_row("SMTP", "✅" if settings.smtp_ready else "❌")
    console.print(table)


@app.command()
def run_dry(
    client: str = typer.Option(default="DemoClient", help="Client name"),
) -> None:
    """Run a dry workflow with placeholder data."""
    runner = WorkflowRunner(dry_run=True)
    leads = [
        Lead(
            lead_id="L001",
            client_name=client,
            full_name="Alice Smith",
            company="Acme Corp",
            email="alice@acme.com",
        ),
        Lead(
            lead_id="L002",
            client_name=client,
            full_name="Bob Jones",
            company="Globex",
            email="bob@globex.com",
        ),
    ]
    result = runner.run_research_and_draft(client_name=client, leads=leads)
    console.print(result.summary())
    for lead in leads:
        console.print(f"{lead.lead_id}: {lead.status.value} | Score: {lead.personalization_score}")


def main() -> None:
    app()
