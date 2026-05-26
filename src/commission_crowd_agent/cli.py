"""CLI entrypoint for Commission Crowd Agent.

Provides operator-facing commands for the Hermes hooks architecture.
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


def _build_settings_table() -> Table:
    settings = load_settings()
    table = Table(title="CCA Configuration Status")
    table.add_column("Service", style="cyan")
    table.add_column("Ready", style="green")
    table.add_row("Ollama", "✅" if settings.ollama_ready else "❌")
    table.add_row("Telegram", "✅" if settings.telegram_ready else "❌")
    table.add_row("Google", "✅" if settings.google_ready else "❌")
    table.add_row("SMTP", "✅" if settings.smtp_ready else "❌")
    return table


@app.command()
def status() -> None:
    """Show configuration readiness."""
    console.print(_build_settings_table())


@app.command(name="run-research-cycle")
def run_research_cycle(
    client: str = typer.Option(default="DemoClient", help="Client name"),
    dry_run: bool = typer.Option(default=False, help="Run with stub data, no external calls"),
) -> None:
    """Fetch new leads, research, draft, and score."""
    runner = WorkflowRunner(dry_run=dry_run)
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
    console.print(_build_settings_table())
    console.print(result.summary())
    for lead in leads:
        console.print(f"{lead.lead_id}: {lead.status.value} | Score: {lead.personalization_score}")


@app.command(name="score-opportunities")
def score_opportunities(
    client: str = typer.Option(default="DemoClient", help="Client name"),
    dry_run: bool = typer.Option(default=False, help="Run with stub data"),
) -> None:
    """Re-score existing leads."""
    if dry_run:
        console.print("[DRY] Scored 2 leads for", client)
    else:
        console.print("[LIVE] score-opportunities not yet wired to real adapter.")


@app.command(name="draft-outreach")
def draft_outreach(
    client: str = typer.Option(default="DemoClient", help="Client name"),
    dry_run: bool = typer.Option(default=False, help="Run with stub data"),
) -> None:
    """Generate email drafts for approved leads."""
    if dry_run:
        console.print("[DRY] Drafted 0 outreach emails for", client)
    else:
        console.print("[LIVE] draft-outreach not yet wired to real adapter.")


@app.command(name="request-approval")
def request_approval(
    client: str = typer.Option(default="DemoClient", help="Client name"),
    dry_run: bool = typer.Option(default=False, help="Run with stub data"),
) -> None:
    """Send operator a summary of leads awaiting approval."""
    if dry_run:
        console.print("[DRY] Approval request queued for", client)
    else:
        console.print("[LIVE] request-approval not yet wired to Telegram adapter.")


@app.command(name="send-approved-outreach")
def send_approved_outreach(
    client: str = typer.Option(default="DemoClient", help="Client name"),
    dry_run: bool = typer.Option(default=False, help="Run with stub data"),
) -> None:
    """Send emails for leads marked approved."""
    if dry_run:
        console.print("[DRY] Sent 0 approved emails for", client)
    else:
        console.print("[LIVE] send-approved-outreach not yet wired to SMTP adapter.")


@app.command(name="daily-summary")
def daily_summary(
    client: str = typer.Option(default="DemoClient", help="Client name"),
    dry_run: bool = typer.Option(default=False, help="Run with stub data"),
) -> None:
    """Report pipeline stats to operator."""
    if dry_run:
        console.print("[DRY] Daily summary for", client)
        console.print("New: 2 | Researching: 0 | Draft Ready: 0 | Sent: 0")
    else:
        console.print("[LIVE] daily-summary not yet wired to Source adapter.")


def main() -> None:
    app()
