"""Approval gate workflow stage.

Handles approval summary generation and status tracking.
"""

from __future__ import annotations

from ..domain import Lead


def summarise_approval_queue(leads: list[Lead]) -> dict[str, int]:
    """Return counts of leads by status."""
    counts: dict[str, int] = {}
    for lead in leads:
        counts[lead.status.value] = counts.get(lead.status.value, 0) + 1
    return counts
