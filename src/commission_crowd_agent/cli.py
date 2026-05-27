"""CLI entrypoint for Commission Crowd Agent.

Provides operator-facing commands for the Hermes hooks architecture.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from .adapters import GoogleSheetsAdapter, NotifierAdapter
from .approval_gate import ApprovalGate
from .config import CcaSettings, load_settings
from .domain import Lead
from .secrets import (
    MissingEnvFileError,
    load_shared_env,
)
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


def _build_preflight_table() -> Table:
    """Return a preflight readiness table with shared-env checks.

    Never prints secret values.
    """
    settings = load_settings()
    table = Table(title="CCA Preflight Checklist")
    table.add_column("Check", style="cyan")
    table.add_column("Result", style="green")

    # Shared env file existence
    try:
        load_shared_env()
        table.add_row("Shared env file", "✅ present")
    except MissingEnvFileError:
        table.add_row("Shared env file", "⚠️ missing (OK if using .env)")

    # Token presence (value never shown)
    notifier = NotifierAdapter(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
    )
    if notifier.token_present():
        table.add_row("Telegram token", "✅ configured")
    else:
        table.add_row("Telegram token", "❌ not configured")

    # Service readiness
    table.add_row("Ollama", "✅ ready" if settings.ollama_ready else "❌ missing")
    table.add_row("Telegram", "✅ ready" if settings.telegram_ready else "❌ missing")
    table.add_row("Google", "✅ ready" if settings.google_ready else "❌ missing")
    table.add_row("SMTP", "✅ ready" if settings.smtp_ready else "❌ missing")

    return table


@app.command()
def status() -> None:
    """Show configuration readiness."""
    console.print(_build_settings_table())


@app.command()
def preflight() -> None:
    """Show preflight checks including shared secrets readiness."""
    console.print(_build_preflight_table())


@app.command(name="notify-test")
def notify_test(
    chat_id: str = typer.Option(
        default="", help="Target Telegram chat ID (or default from config)"
    ),
    text: str = typer.Option(default="Hello from CCA notifier test", help="Message text to send"),
    dry_run: bool = typer.Option(default=True, help="Simulate send without calling Telegram API"),
    send: bool = typer.Option(default=False, help="Actually send the message (requires chat_id)"),
) -> None:
    """Test Telegram notifier adapter safely.

    Default is dry-run. Use --send only when you explicitly want a real message.
    """
    settings = load_settings()
    notifier = NotifierAdapter(
        bot_token=settings.telegram_bot_token,
        chat_id=chat_id or settings.telegram_chat_id,
        dry_run=dry_run and not send,
    )

    if not notifier.token_present():
        console.print("[red]❌ Telegram token not configured[/red]")
        raise typer.Exit(1)

    if send and not (chat_id or settings.telegram_chat_id):
        console.print(
            "[red]❌ chat_id is required for real send. "
            "Pass --chat-id or set TELEGRAM_CHAT_ID.[/red]"
        )
        raise typer.Exit(1)

    result = notifier.send_message(text=text)
    status_icon = "✅" if result["ok"] else "❌"
    console.print(f"{status_icon} Telegram notifier test")
    console.print(f"   Dry run: {notifier.dry_run}")
    console.print(f"   Status: {result['status']}")
    if result["error"]:
        console.print(f"   Error: {result['error']}")
    if result["message_id"] is not None:
        console.print(f"   Message ID: {result['message_id']}")


# --- Google Sheets CLI commands ---


@app.command(name="workflow-stub-smoke")
def workflow_stub_smoke(
    write: bool = typer.Option(
        default=False, help="Actually write at most 3 stub rows to Google Sheets"
    ),
    notify: bool = typer.Option(default=False, help="Send Telegram start/success notifications"),
) -> None:
    """Run a stub workflow and optionally write at most 3 rows (runs, leads, opportunities).

    Pass --write for a real append. Default is dry-run safe.
    All rows are tagged source=stub and workflow=stub_smoke_test.
    Pass --notify to send Telegram lifecycle notifications.
    """
    settings = load_settings()
    adapter = _build_sheets_adapter(settings, dry_run=not write)
    notifier = _build_notifier(settings, dry_run=not notify)

    runner = WorkflowRunner(
        dry_run=True,  # stub mode: no real AI/scraper calls
        sheets_adapter=adapter,
        notifier=notifier,
    )
    leads = [
        Lead(
            lead_id="STUB-L001",
            client_name="StubClient",
            full_name="Stub Alice",
            company="StubCorp",
            email="alice@stubcorp.com",
        ),
    ]
    run = runner.run_research_and_draft(client_name="StubClient", leads=leads)

    status_icon = "✅" if run.status == "completed" else "❌"
    console.print(f"{status_icon} workflow-stub-smoke")
    console.print(f"   Dry run: {adapter.dry_run}")
    console.print(f"   Run ID: {run.run_id}")
    console.print(f"   Leads: {len(leads)}")
    if not adapter.dry_run:
        console.print("   [green]Rows appended to runs, leads, opportunities[/green]")
    else:
        console.print("   [dim](No rows written because --write was not passed)[/dim]")
    if notify:
        console.print("   [blue]Notifications sent[/blue]")
    else:
        console.print("   [dim](Notifications skipped; pass --notify to send)[/dim]")


def _build_notifier(settings: CcaSettings, dry_run: bool = False) -> NotifierAdapter:
    """Build a NotifierAdapter with credentials from settings.

    Real sends are gated by dry_run=False; set dry_run=True for safe simulation.
    """
    return NotifierAdapter(
        bot_token=settings.telegram_bot_token,
        chat_id=settings.telegram_chat_id,
        dry_run=dry_run,
    )


def _build_sheets_adapter(settings: CcaSettings, dry_run: bool = False) -> GoogleSheetsAdapter:
    """Build a GoogleSheetsAdapter with service-account credentials if available."""
    return GoogleSheetsAdapter(
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        dry_run=dry_run,
        credentials_path=settings.google_application_credentials_path,
        service_account_json=settings.google_service_account_json,
    )


@app.command(name="sheets-status")
def sheets_status(
    live: bool = typer.Option(default=False, help="Perform a real read-only health check"),
) -> None:
    """Check Google Sheets adapter readiness (dry-run safe by default)."""
    settings = load_settings()
    adapter = _build_sheets_adapter(settings, dry_run=not live)
    result = adapter.health_check()
    status_icon = "✅" if result["ok"] else "❌"
    console.print(f"{status_icon} Google Sheets status")
    ssid_state = "configured" if settings.google_sheets_spreadsheet_id else "missing"
    creds_state = "ready" if settings.google_ready else "missing"
    console.print(f"   Spreadsheet ID: {ssid_state}")
    console.print(f"   Google credentials: {creds_state}")
    console.print(f"   Dry run: {adapter.dry_run}")
    if result["error"]:
        console.print(f"   Error: {result['error']}")


@app.command(name="sheets-ensure-schema")
def sheets_ensure_schema(
    dry_run: bool = typer.Option(default=True, help="Simulate without writing"),
    write: bool = typer.Option(default=False, help="Actually create tabs (requires scope)"),
) -> None:
    """Ensure all schema tabs exist. Defaults to dry-run."""
    settings = load_settings()
    adapter = _build_sheets_adapter(settings, dry_run=dry_run and not write)
    result = adapter.ensure_schema()
    status_icon = "✅" if result["ok"] else "❌"
    console.print(f"{status_icon} sheets-ensure-schema")
    console.print(f"   Dry run: {adapter.dry_run}")
    console.print(f"   Tabs expected: {len(adapter.SCHEMA)}")
    if result["error"]:
        console.print(f"   Note: {result['error']}")


@app.command(name="sheets-append-sample-lead")
def sheets_append_sample_lead(
    dry_run: bool = typer.Option(default=True, help="Simulate without writing"),
    write: bool = typer.Option(default=False, help="Actually append the row"),
) -> None:
    """Append a sample lead row to the leads tab. Defaults to dry-run."""
    settings = load_settings()
    adapter = _build_sheets_adapter(settings, dry_run=dry_run and not write)
    sample = [
        "L-SAMPLE-001",
        "manual_test",
        "Sample Name",
        "Sample Corp",
        "https://example.com",
        "sample@example.com",
        "new",
        "2026-05-26T00:00:00Z",
        "Created by sheets-append-sample-lead CLI command",
    ]
    result = adapter.append_row("leads", sample)
    status_icon = "✅" if result["ok"] else "❌"
    console.print(f"{status_icon} sheets-append-sample-lead")
    console.print(f"   Dry run: {adapter.dry_run}")
    console.print(f"   Tab: {result['tab']}")
    console.print(f"   Rows changed: {result['rows_changed']}")
    if result["error"]:
        console.print(f"   Error: {result['error']}")


@app.command(name="run-research-cycle")
def run_research_cycle(
    client: str = typer.Option(default="DemoClient", help="Client name"),
    dry_run: bool = typer.Option(default=False, help="Run with stub data, no external calls"),
    write: bool = typer.Option(
        default=False, help="Write run/leads/opportunities rows to Google Sheets"
    ),
) -> None:
    """Fetch new leads, research, draft, and score."""
    settings = load_settings()
    adapter = _build_sheets_adapter(settings, dry_run=not write) if write else None
    runner = WorkflowRunner(
        dry_run=dry_run,
        sheets_adapter=adapter,
    )
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
    if adapter is not None and not adapter.dry_run:
        console.print("[green]Workflow ledgers written to Google Sheets[/green]")


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


@app.command(name="approval-stub-smoke")
def approval_stub_smoke(
    write: bool = typer.Option(
        default=False, help="Actually append one pending approval row to Google Sheets"
    ),
    notify: bool = typer.Option(default=False, help="Send Telegram approval notification"),
) -> None:
    """Create a stub approval request and optionally write/notify.

    Defaults to dry-run. Pass --write for a real Sheet row, --notify for a
    Telegram notification. Stops after creating the request; no downstream
    action is executed.
    """
    settings = load_settings()
    adapter = _build_sheets_adapter(settings, dry_run=not write)
    notifier = _build_notifier(settings, dry_run=not notify)
    gate = ApprovalGate(sheets_adapter=adapter, notifier=notifier)

    req = gate.create_approval(
        opportunity_id="STUB-OPP-001",
        draft_text="Approve draft outreach to StubCorp (Stub Alice)",
        dry_run=not write,
    )

    if notify:
        gate.notify_operator(req, dry_run=not notify)

    status_icon = "✅" if req.approval_status == "pending" else "❌"
    console.print(f"{status_icon} approval-stub-smoke")
    console.print(f"   Approval ID: {req.approval_id}")
    console.print(f"   Opportunity: {req.opportunity_id}")
    console.print(f"   Dry run (sheets): {adapter.dry_run}")
    if not adapter.dry_run:
        console.print("   [green]Approval row appended to 'approvals' tab[/green]")
    else:
        console.print("   [dim](No Sheet row written because --write was not passed)[/dim]")
    if notify:
        console.print("   [blue]Notification sent[/blue]")
    else:
        console.print("   [dim](Notification skipped; pass --notify to send)[/dim]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
