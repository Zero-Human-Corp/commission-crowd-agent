"""Research-to-draft workflow stage.

Fetches new leads, runs research agent, writer agent, and scorer agent.
"""

from __future__ import annotations

from ..adapters import ScoringAdapter, SourceAdapter
from ..domain import Lead, LeadStatus


def run_research_cycle(
    client_name: str,
    source: SourceAdapter,
    scorer: ScoringAdapter,
    limit: int = 30,
    dry_run: bool = True,
) -> list[Lead]:
    """Fetch new leads, research, draft, score, and update status."""
    if dry_run:
        leads = [
            Lead(
                lead_id="L001",
                client_name=client_name,
                full_name="Alice Smith",
                company="Acme Corp",
                email="alice@acme.com",
            ),
            Lead(
                lead_id="L002",
                client_name=client_name,
                full_name="Bob Jones",
                company="Globex",
                email="bob@globex.com",
            ),
        ]
    else:
        leads = source.fetch_new_leads(client_name=client_name, limit=limit)

    for lead in leads:
        if lead.status != LeadStatus.NEW:
            continue
        lead.research_notes = (
            scorer.research(lead) if not dry_run else f"[DRY] Research on {lead.company}"
        )
        subject, body = (
            scorer.write_email(lead) if not dry_run else (f"[DRY] Subject for {lead.full_name}", "")
        )
        lead.email_subject = subject
        lead.email_body = body
        lead.personalization_score = scorer.score(lead) if not dry_run else 7
        lead.status = LeadStatus.DRAFT_READY
        if not dry_run:
            source.update_lead(lead)

    return leads
