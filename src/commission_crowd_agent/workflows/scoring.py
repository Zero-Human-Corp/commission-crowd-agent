"""Scoring workflow stage.

Re-evaluates or scores existing leads.
"""

from __future__ import annotations

from ..adapters import ScoringAdapter
from ..domain import Lead


def score_batch(leads: list[Lead], scorer: ScoringAdapter, dry_run: bool = True) -> list[Lead]:
    """Score a batch of leads."""
    for lead in leads:
        lead.personalization_score = scorer.score(lead) if not dry_run else 7
    return leads
