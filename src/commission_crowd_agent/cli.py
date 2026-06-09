"""CLI entrypoint for Commission Crowd Agent.

Provides operator-facing commands for the Hermes hooks architecture.
"""

from __future__ import annotations

from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .adapters import GoogleSheetsAdapter, NotifierAdapter, ScoringAdapter
from .approval_gate import ApprovalGate
from .config import CcaSettings, load_settings
from .domain import Lead
from .lead_ingestion import LeadIngester
from .lead_scoring import LeadScorer
from .operator_source import OperatorSourceIngester
from .secrets import (
    MissingEnvFileError,
    load_shared_env,
)
from .supervisor_relay import (
    SupervisorRelay,
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
    table.add_row("CommissionCrowd", "✅" if settings.commissioncrowd_ready else "❌")
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
    notify: bool = typer.Option(default=False, help="Send Telegram summary to operator after run"),
) -> None:
    """Fetch new leads, research, draft, score, and queue operator approvals.

    In live mode (dry_run=False) the scoring adapter runs real research and
    deterministic scoring.  Each lead then gets an approval record written to
    the approvals tab.  Writing to approvals requires --write.
    """
    settings = load_settings()
    adapter = _build_sheets_adapter(settings, dry_run=not write) if write else None
    notifier = _build_notifier(settings, dry_run=not notify)
    scoring = (
        ScoringAdapter(
            base_url=settings.ollama_base_url,
            api_key=settings.ollama_api_key,
            model=settings.ollama_model,
        )
        if not dry_run
        else None
    )
    runner = WorkflowRunner(
        dry_run=dry_run,
        sheets_adapter=adapter,
        notifier=notifier,
        scoring_adapter=scoring if scoring else None,
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

    # Operator approval gate: create approval requests for each lead
    if adapter is not None and not adapter.dry_run:
        gate = ApprovalGate(sheets_adapter=adapter, notifier=notifier)
        for lead in leads:
            try:
                req = gate.create_and_write_approval(
                    entity_type="lead",
                    entity_id=lead.lead_id,
                    entity_name=lead.company or lead.full_name,
                    requested_action=(
                        f"Draft outreach ready for {lead.company or lead.full_name} "
                        f"(score={lead.personalization_score})"
                    ),
                    approval_action="outreach_draft",
                    risk_level="low" if (lead.personalization_score or 0) >= 6 else "medium",
                    notes=(f"Research notes: {lead.research_notes[:200]}")
                    if lead.research_notes
                    else "",
                )
                console.print(
                    f"[yellow]Approval queued: {lead.lead_id} → {req.approval_id}[/yellow]"
                )
            except RuntimeError as exc:
                console.print(f"[red]Approval failed for {lead.lead_id}: {exc}[/red]")
        console.print("[green]Workflow ledgers written to Google Sheets[/green]")
    else:
        console.print("[dim]Skipping approval gate: --write not passed[/dim]")


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

    if write:
        header_check = gate.validate_header()
        if not header_check["ok"]:
            console.print(f"[red]❌ {header_check['error']}[/red]")
            raise typer.Exit(1)

    req = gate.create_approval(
        entity_type="opportunity",
        entity_id="STUB-OPP-001",
        requested_action="Approve draft outreach to StubCorp (Stub Alice)",
        risk_level="low",
        dry_run=not write,
    )

    if notify:
        gate.notify_operator(req, dry_run=not notify)

    status_icon = "✅" if req.status == "approved" else "⏳" if req.status == "pending" else "❌"
    console.print(f"{status_icon} approval-stub-smoke")
    console.print(f"   Approval ID: {req.approval_id}")
    console.print(f"   Entity: {req.entity_type} — {req.entity_id}")
    console.print(f"   Dry run (sheets): {adapter.dry_run}")
    if not adapter.dry_run:
        console.print("   [green]Approval row appended to 'approvals' tab[/green]")
    else:
        console.print("   [dim](No Sheet row written because --write was not passed)[/dim]")
    if notify:
        console.print("   [blue]Notification sent[/blue]")
    else:
        console.print("   [dim](Notification skipped; pass --notify to send)[/dim]")


@app.command(name="approval-check")
def approval_check(
    approval_id: str = typer.Argument(..., help="Approval ID to inspect"),
) -> None:
    """Read a single approval record from the Sheet and print status safely."""
    settings = load_settings()
    adapter = _build_sheets_adapter(settings, dry_run=False)
    gate = ApprovalGate(sheets_adapter=adapter)

    record = gate.read_approval_record(approval_id)
    if not record:
        console.print(f"[red]❌ Approval {approval_id} not found[/red]")
        raise typer.Exit(1)

    status = record.get("status", "unknown")
    icon = "✅" if status == "approved" else "⏳" if status == "pending" else "❌"
    console.print(f"{icon} Approval {approval_id}")
    console.print(f"   Entity: {record.get('entity_type', '—')} — {record.get('entity_id', '—')}")
    console.print(f"   Entity Name: {record.get('entity_name') or '—'}")
    console.print(f"   Approval Action: {record.get('approval_action') or '—'}")
    console.print(f"   Requested Action: {record.get('requested_action', '—')}")
    console.print(f"   Risk: {record.get('risk_level', '—')}")
    console.print(f"   Status: {status}")
    console.print(f"   Operator decision: {record.get('operator_decision') or '—'}")
    console.print(f"   Decided at: {record.get('decided_at_utc') or '—'}")
    console.print(f"   Source URL: {record.get('source_url') or '—'}")
    console.print(f"   Notes: {record.get('notes') or '—'}")
    if status == "approved":
        console.print("   [green]Downstream action: ALLOWED[/green]")
    else:
        console.print("   [yellow]Downstream action: BLOCKED[/yellow]")


@app.command(name="downstream-stub-smoke")
def downstream_stub_smoke(
    approval_id: str = typer.Option(..., help="Approval ID required for downstream action"),
    dry_run: bool = typer.Option(default=True, help="Simulate only; do not perform real actions"),
) -> None:
    """Simulate a downstream action guarded by approval status.

    If the approval status is not 'approved', the action is blocked.
    Defaults to dry-run even when the approval is approved.
    """
    settings = load_settings()
    adapter = _build_sheets_adapter(settings, dry_run=False)
    gate = ApprovalGate(sheets_adapter=adapter)

    is_ok = gate.is_approved(approval_id)
    if not is_ok:
        console.print(f"[red]❌ BLOCKED — approval {approval_id} is not approved[/red]")
        raise typer.Exit(1)

    if dry_run:
        console.print(f"[green]✅ ALLOWED (dry-run) — approval {approval_id} is approved[/green]")
        console.print("   [dim]No real action taken (dry-run)[/dim]")
    else:
        console.print(f"[yellow]⚠ ALLOWED (live) — approval {approval_id} is approved[/yellow]")
        console.print("   [red]Live downstream actions are not yet implemented[/red]")


@app.command(name="ingest-leads-readonly")
def ingest_leads_readonly(
    source: str = typer.Argument(..., help="Source: path/to/candidates.json or 'search:<query>'"),
    limit: int = typer.Option(default=3, help="Max candidates to ingest (max 5)"),
    write: bool = typer.Option(
        default=False, help="Actually write discovered leads to Google Sheets"
    ),
    notify: bool = typer.Option(default=False, help="Send Telegram notification after writing"),
) -> None:
    """Ingest candidate leads from a public source and optionally write/notify.

    Defaults to dry-run.  Pass --write to persist leads to the 'leads' tab.
    Creates pending approval requests for every written candidate.
    Never sends outreach.
    """
    if limit > 5:
        console.print("[red]❌ limit must be ≤ 5 for this mission[/red]")
        raise typer.Exit(1)

    settings = load_settings()
    sheets_adapter = _build_sheets_adapter(settings, dry_run=not write)
    approval_gate = ApprovalGate(sheets_adapter=sheets_adapter)
    ingester = LeadIngester(
        sheets_adapter=sheets_adapter,
        approval_gate=approval_gate,
    )

    # Discovery
    if source.startswith("search:"):
        query = source[len("search:") :]
        candidates = ingester.discover_from_search(query, limit=limit)
    else:
        from pathlib import Path

        candidates = ingester.discover_from_json(Path(source))[:limit]

    console.print(f"[blue]🔍 Discovered {len(candidates)} candidates[/blue]")
    for c in candidates:
        console.print(f"   • {c.company} — {c.full_name or 'no contact'} ({c.source})")

    # Write
    write_result = ingester.write_candidates(candidates, dry_run=not write)
    if write_result.get("dry_run"):
        console.print("[dim]   (Dry-run — no Sheet rows written)[/dim]")
    else:
        ok = write_result.get("ok")
        written = write_result.get("written", 0)
        icon = "✅" if ok else "❌"
        console.print(f"   [{icon}] Written {written}/{len(candidates)} leads")
        if write_result.get("errors"):
            for err in write_result["errors"]:
                console.print(f"   [red]Error: {err}[/red]")

    # Approvals
    approval_results = ingester.create_approval_requests(candidates, dry_run=not write)
    for res in approval_results:
        console.print(
            f"   ⏳ Approval {res['approval_id']} for {res['company']} (dry_run={res['dry_run']})"
        )

    # Notify
    if notify and candidates and write:
        text = (
            "📥 *Lead Ingestion Complete*\n"
            f"Discovered: {len(candidates)}\n"
            f"Written: {write_result.get('written', 0)}\n"
            f"Approvals: {len(approval_results)}\n"
            "Mode: live"
        )
        notifier = _build_notifier(settings, dry_run=False)
        notifier.send_message(text=text)
        console.print("   [blue]Notification sent[/blue]")
    elif notify:
        console.print("   [dim](Notify requires both --write and real candidates)[/dim]")
    else:
        console.print("   [dim](Notification skipped; pass --notify to send)[/dim]")

    console.print("[green]✅ ingest-leads-readonly complete[/green]")


@app.command(name="ingest-operator-sources")
def ingest_operator_sources(
    source_file: str = typer.Option(
        default="",
        help="Path to operator_sources JSON (e.g. config/operator_sources.json)",
    ),
    source_url: str = typer.Option(
        default="",
        help="One-off public URL to ingest (overrides file if both given)",
    ),
    limit: int = typer.Option(default=3, help="Max candidates to ingest (max 5)"),
    write: bool = typer.Option(
        default=False, help="Actually write discovered leads to Google Sheets"
    ),
    notify: bool = typer.Option(default=False, help="Send Telegram notification after writing"),
) -> None:
    """Ingest from operator-provided public sources. Dry-run by default.

    Pass --source-file to load from JSON, or --source-url for a one-off URL.
    Pass --write to persist leads and create pending approvals.
    No scraping; no outreach; never sends emails.
    """
    if limit > 5:
        console.print("[red]❌ limit must be ≤ 5[/red]")
        raise typer.Exit(1)

    settings = load_settings()
    sheets_adapter = _build_sheets_adapter(settings, dry_run=not write)
    approval_gate = ApprovalGate(sheets_adapter=sheets_adapter)
    lead_ingester = LeadIngester(
        sheets_adapter=sheets_adapter,
        approval_gate=approval_gate,
    )
    operator_ingester = OperatorSourceIngester(lead_ingester=lead_ingester)

    # Resolve sources
    sources: list[Any] = []
    if source_url:
        try:
            sources = [OperatorSourceIngester.parse_single_url(source_url)]
            console.print(f"[blue]🔗 CLI source URL: {source_url[:60]}...[/blue]")
        except ValueError as exc:
            console.print(f"[red]❌ Invalid source URL: {exc}[/red]")
            raise typer.Exit(1) from exc
    elif source_file:
        from pathlib import Path

        path = Path(source_file)
        if not path.exists():
            console.print(f"[yellow]⚠ Source file not found: {source_file}[/yellow]")
            console.print("   (No sources provided — exiting safely)")
            raise typer.Exit(0)
        try:
            sources = OperatorSourceIngester.load_source_file(path)
        except (ValueError, OSError) as exc:
            console.print(f"[red]❌ Failed to load source file: {exc}[/red]")
            raise typer.Exit(1) from exc
        console.print(f"[blue]📁 Loaded {len(sources)} source(s) from {source_file}[/blue]")
    else:
        console.print("[yellow]⚠ No sources provided[/yellow]")
        console.print("   Pass --source-file or --source-url")
        console.print("   (Nothing to do — exiting safely)")
        raise typer.Exit(0)

    # Ingest
    result = operator_ingester.ingest_sources(sources, limit=limit, dry_run=not write)

    # Summary
    dry_icon = "[DRY]" if result.get("dry_run") else "[LIVE]"
    console.print(f"{dry_icon} ingest-operator-sources")
    console.print(f"   Candidates: {result.get('candidates', 0)}")
    console.print(f"   Written: {result.get('written', 0)}")
    console.print(f"   Approvals: {result.get('approvals', 0)}")
    console.print(f"   Skipped placeholder sources: {result.get('skipped', 0)}")

    if result.get("source_reports"):
        console.print("   Per-source breakdown:")
        for sr in result["source_reports"]:
            status_icon = "✅" if sr.get("status") in ("success", "fallback") else "❌"
            console.print(
                f"      {status_icon} {sr.get('name')}: "
                f"extracted={sr.get('extracted', 0)}, "
                f"duplicates={sr.get('duplicates_skipped', 0)}, "
                f"placeholders={sr.get('placeholders_blocked', 0)}, "
                f"written={sr.get('written', 0)}, "
                f"limit={sr.get('per_source_limit', 0)}"
            )
            if sr.get("error"):
                console.print(f"         [red]Error: {sr['error'][:80]}[/red]")

    if result.get("sources") and not result.get("source_reports"):
        for s in result["sources"]:
            console.print(f"   • {s.get('name')} ({s.get('source_type')})")
    console.print(f"   {result.get('message', '')}")

    # Notify
    if notify and result.get("candidates") and write:
        per_source_lines = []
        for sr in result.get("source_reports", []):
            per_source_lines.append(
                f"- {sr.get('name')}: "
                f"extracted={sr.get('extracted', 0)}, "
                f"written={sr.get('written', 0)}"
            )
        text = (
            "📥 *Operator Source Ingestion*\n"
            f"Candidates: {result.get('candidates', 0)}\n"
            f"Written: {result.get('written', 0)}\n"
            f"Approvals: {result.get('approvals', 0)}\n"
            f"Mode: live\n"
            f"Sources:\n" + "\n".join(per_source_lines)
        )
        notifier = _build_notifier(settings, dry_run=False)
        notifier.send_message(text=text)
        console.print("   [blue]Notification sent[/blue]")
    elif notify:
        console.print("   [dim](Notify requires --write and at least one candidate)[/dim]")
    else:
        console.print("   [dim](Notification skipped; pass --notify to send)[/dim]")

    console.print("[green]✅ ingest-operator-sources complete[/green]")


@app.command(name="score-leads-dry-run")
def score_leads_dry_run(
    lead_id: str = typer.Option(default="", help="Score specific lead by ID"),
    limit: int = typer.Option(default=3, help="Max leads to score"),
    write: bool = typer.Option(
        default=False, help="Write score/opportunity records to Google Sheets"
    ),
    notify: bool = typer.Option(default=False, help="Send Telegram notification"),
) -> None:
    """Score existing leads and optionally write opportunities + approvals.

    Default is dry-run.  Pass --write to persist scored opportunities.
    Creates pending deeper-research approvals for above-threshold leads.
    Never sends outreach.
    """
    settings = load_settings()
    sheets_adapter = _build_sheets_adapter(settings, dry_run=not write)
    approval_gate = ApprovalGate(sheets_adapter=sheets_adapter)
    scorer = LeadScorer()

    # Read leads
    read_result = sheets_adapter.read_last_rows("leads", count=50)
    if not read_result.get("ok"):
        console.print(f"[red]❌ Failed to read leads: {read_result.get('error')}[/red]")
        raise typer.Exit(1)

    rows = read_result.get("rows", [])
    if lead_id:
        # Filter to specific lead
        rows = [r for r in rows if r and r[0] == lead_id]
        if not rows:
            console.print(f"[red]❌ Lead {lead_id} not found[/red]")
            raise typer.Exit(1)

    # Score
    scores = scorer.score_leads(rows[:limit])
    console.print(f"[blue]🔍 Scored {len(scores)} leads[/blue]")
    for s in scores:
        icon = "🟢" if s.fit_score >= 70 else "🟡" if s.fit_score >= 40 else "🔴"
        console.print(
            f"   {icon} {s.company_name or s.lead_id}: fit_score={s.fit_score} "
            f"confidence={s.confidence}"
        )
        console.print(f"      reasons: {', '.join(s.reasons)}")
        if s.missing_data:
            console.print(f"      missing: {', '.join(s.missing_data)}")

    # Write opportunities
    write_result = scorer.write_opportunities(
        scores, sheets_adapter=sheets_adapter, dry_run=not write
    )
    if write_result.get("dry_run"):
        skipped = write_result.get("skipped", 0)
        below = write_result.get("below_threshold", 0)
        console.print(f"[dim]   (Dry-run — {skipped} already exist, {below} below threshold)[/dim]")
    else:
        ok = write_result.get("ok")
        written = write_result.get("written", 0)
        skipped = write_result.get("skipped", 0)
        below = write_result.get("below_threshold", 0)
        icon = "✅" if ok else "❌"
        console.print(f"[{icon}] Written {written}/{len(scores)} opportunities")
        console.print(f"   Skipped {skipped} existing, {below} below threshold")
        for sid in write_result.get("skipped_ids", []):
            console.print(f"   [dim]   Skipped existing {sid}[/dim]")
        if below:
            for bid in write_result.get("below_threshold_ids", []):
                console.print(f"   [dim]   ⬇️ Below threshold {bid}[/dim]")

    # Approval requests for deeper research
    approval_results: list[dict[str, Any]] = []
    if scores:
        approval_results = scorer.request_deeper_research_approvals(
            scores, approval_gate=approval_gate, sheets_adapter=sheets_adapter, dry_run=not write
        )
        for res in approval_results:
            if res.get("skipped"):
                console.print(
                    f"   🔄 Approval {res['approval_id']} already exists for {res['company']} "
                    f"(status={res['status']}) — skipped"
                )
            else:
                console.print(
                    f"   ⏳ Approval {res['approval_id']} for {res['company']} "
                    f"(fit={res['fit_score']}, dry_run={res['dry_run']})"
                )

    # Notify
    if notify and write and scores:
        text = (
            "📊 *Lead Scoring Complete*\n"
            f"Scored: {len(scores)}\n"
            f"Written: {write_result.get('written', 0)}\n"
            f"Approvals: {len(approval_results)}\n"
            "No outreach performed"
        )
        notifier = _build_notifier(settings, dry_run=False)
        notifier.send_message(text=text)
        console.print("   [blue]Notification sent[/blue]")
    elif notify:
        console.print("   [dim](Notify requires --write, real scores)[/dim]")
    else:
        console.print("   [dim](Notification skipped; pass --notify to send)[/dim]")

    console.print("[green]✅ score-leads-dry-run complete[/green]")


@app.command(name="research-approved-lead")
def research_approved_lead(
    lead_id: str = typer.Option(..., help="Lead ID to research"),
    approval_id: str = typer.Option(..., help="Approval ID that must be approved"),
    write: bool = typer.Option(default=False, help="Write research findings to Google Sheets"),
    notify: bool = typer.Option(default=False, help="Send Telegram notification"),
) -> None:
    """Run deeper research for one approved lead.

    Requires an approved approval ID.
    Default is dry-run.
    Creates a pending approval for outreach-draft creation.
    Never creates outreach drafts in this command.
    """
    from .approval_gate import ApprovalGate
    from .deeper_research import DeeperResearchService

    settings = load_settings()
    sheets_adapter = _build_sheets_adapter(settings, dry_run=not write)
    approval_gate = ApprovalGate(sheets_adapter=sheets_adapter)
    service = DeeperResearchService()

    # Verify approval is approved
    check = approval_gate.read_approval_record(approval_id)
    status = check.get("status", "missing")
    if status != "approved":
        console.print(f"[red]❌ BLOCKED — approval {approval_id} is {status}, not approved[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✅ Approval {approval_id} is approved — proceeding[/green]")

    # Fetch lead
    read_result = sheets_adapter.read_last_rows("leads", count=50)
    if not read_result.get("ok"):
        console.print("[red]❌ Failed to read leads[/red]")
        raise typer.Exit(1)
    rows = read_result.get("rows", [])
    lead_row: list[str] = []
    for row in rows:
        if row and row[0] == lead_id:
            lead_row = row
            break
    if not lead_row:
        console.print(f"[red]❌ Lead {lead_id} not found[/red]")
        raise typer.Exit(1)

    company_name = lead_row[4] if len(lead_row) > 4 else ""
    source_url = lead_row[3] if len(lead_row) > 3 else ""
    contact_email = lead_row[6] if len(lead_row) > 6 else ""
    notes = lead_row[14] if len(lead_row) > 14 else ""

    console.print(f"[blue]🔍 Researching {company_name} (lead_id={lead_id})[/blue]")
    result = service.research_one_lead(
        lead_id=lead_id,
        company_name=company_name,
        source_url=source_url,
        contact_email=contact_email,
        notes=notes,
    )

    for f in result.findings:
        verified_icon = "✅" if f.verified else "❓"
        console.print(f"   {verified_icon} [{f.source_label}] {f.finding[:80]}...")

    console.print(f"   Confidence: {result.confidence}")
    if result.missing_data:
        console.print(f"   Missing: {', '.join(result.missing_data)}")
    console.print(f"   Recommended next action: {result.recommended_next_action}")

    # Write findings
    write_result = service.write_research_result(
        result, sheets_adapter=sheets_adapter, dry_run=not write
    )
    if write_result.get("dry_run"):
        console.print("[dim]   (Dry-run — research result not written)[/dim]")
    elif write_result.get("ok"):
        console.print("[green]   ✅ Research result written[/green]")
    else:
        console.print(f"[red]   ❌ Write failed: {write_result.get('error')}[/red]")

    # Request outreach-draft approval
    approval_result = service.request_outreach_draft_approval(
        result, approval_gate=approval_gate, sheets_adapter=sheets_adapter, dry_run=not write
    )
    if approval_result.get("approval_id") == "BLOCKED":
        console.print(
            "[yellow]   ⛔ Outreach-draft approval BLOCKED — "
            "placeholder/ fixture lead detected[/yellow]"
        )
    elif approval_result.get("dry_run"):
        console.print("[dim]   (Dry-run — outreach-draft approval not created)[/dim]")
    elif approval_result.get("ok"):
        console.print(
            "[green]   ⏳ Outreach-draft approval created: "
            f"{approval_result.get('approval_id')}[/green]"
        )
    else:
        console.print("[red]   ❌ Approval creation failed[/red]")

    # Notify
    if notify and write:
        text = (
            "🔬 *Deeper Research Complete*\n"
            f"Company: {company_name}\n"
            f"Confidence: {result.confidence}\n"
            f"Missing: {', '.join(result.missing_data) if result.missing_data else 'none'}\n"
            f"Outreach-draft approval: {approval_result.get('approval_id', '—')}\n"
            "No outreach performed"
        )
        notifier = _build_notifier(settings, dry_run=False)
        notifier.send_message(text=text)
        console.print("   [blue]Notification sent[/blue]")
    elif notify:
        console.print("   [dim](Notify requires --write)[/dim]")
    else:
        console.print("   [dim](Notification skipped)[/dim]")

    console.print("[green]✅ research-approved-lead complete[/green]")


@app.command(name="supervisor-status")
def supervisor_status() -> None:
    """Show Supervisor Relay configuration summary (no secrets)."""
    settings = load_settings()
    relay = SupervisorRelay(settings=settings, dry_run=True)
    console.print(relay.safe_repr())
    if settings.supervisor_mode != "local":
        console.print(
            "[yellow]⚠️ Supervisor Relay is NOT in local mode. "
            f"SUPERVISOR_MODE={settings.supervisor_mode!r}[/yellow]"
        )


@app.command(name="supervisor-check")
def supervisor_check(
    action: str = typer.Argument(..., help="Recommended action to check against human-only gate"),
) -> None:
    """Check whether a recommended action would be blocked.

    Useful for dry-run audits before asking a local model.
    """
    settings = load_settings()
    relay = SupervisorRelay(settings=settings, dry_run=True)
    result = relay.check_blocked(action)
    if result["blocked"]:
        console.print(f"[red]⛔ BLOCKED[/red]: {action}\n   [dim]{result['block_reason']}[/dim]")
    else:
        console.print(f"[green]✅ ALLOWED[/green]: {action}")


@app.command(name="supervisor-smoke")
def supervisor_smoke(
    model: str = typer.Option(default="", help="Override model to use (default: primary)"),
) -> None:
    """Smoke-test Supervisor Relay in dry-run mode.

    Loads settings, routes a safe prompt to the configured primary
    supervisor, and validates the JSON response.
    """
    settings = load_settings()
    if settings.supervisor_mode != "local":
        console.print(
            f"[red]❌ Supervisor Relay disabled (mode={settings.supervisor_mode!r})[/red]"
        )
        raise typer.Exit(1)
    console.print(f"[blue]Running supervisor smoke test — mode={settings.supervisor_mode!r}[/blue]")
    console.print(
        f"   Primary: {settings.supervisor_primary_model}\n"
        f"   Code review: {settings.supervisor_code_review_model}\n"
        f"   Reasoning fallback: {settings.supervisor_reasoning_fallback_model}\n"
        f"   Draft review: {settings.supervisor_draft_review_model}"
    )
    # Dry-run — no real inference, just validate wiring
    relay = SupervisorRelay(settings=settings, dry_run=True)
    result = relay.primary_check("Ping test.")
    console.print(f"[green]✅ Supervisor dry-run response: {result.model_dump_json()}[/green]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
