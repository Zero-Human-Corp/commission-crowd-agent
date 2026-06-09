"""Outreach dispatch workflow stage.

Sends approved emails and updates lead status.
"""

from __future__ import annotations

from datetime import datetime

from ..adapters import OutreachAdapter, SourceAdapter
from ..domain import Lead, LeadStatus


def send_approved_outreach(
    client_name: str,
    source: SourceAdapter,
    outreach: OutreachAdapter,
    dry_run: bool = True,
) -> list[Lead]:
    """Send emails for approved leads and mark sent."""
    if dry_run:
        leads = [
            Lead(
                lead_id="L001",
                client_name=client_name,
                full_name="Alice",
                email="a@a.com",
                status=LeadStatus.DRAFT_READY,
                approved=True,
            ),
            Lead(
                lead_id="L002",
                client_name=client_name,
                full_name="Bob",
                email="b@b.com",
                status=LeadStatus.DRAFT_READY,
                approved=True,
            ),
        ]
    else:
        leads = source.fetch_new_leads(client_name=client_name, limit=100)
        leads = [lead for lead in leads if lead.approved and lead.status == LeadStatus.DRAFT_READY]

    for lead in leads:
        if not lead.approved or lead.status != LeadStatus.DRAFT_READY:
            continue
        if not dry_run:
            outreach.send_email(lead=lead)
        lead.status = LeadStatus.SENT
        lead.sent_timestamp = datetime.utcnow()
        if not dry_run:
            source.update_lead(lead)

    return leads
