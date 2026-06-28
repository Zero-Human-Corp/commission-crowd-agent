"""Opportunity state registry — reconcile all CommissionCrowd sources.

Combines My Opportunities, Messages, Favourites, Find Opportunities, CRM,
approvals, and API data into one canonical registry keyed by opportunity ID.

Precedence (highest first):
1. My Opportunities authenticated account state
2. Explicit platform invitation linked to an opportunity
3. Favourite Opportunities authenticated account state
4. Find Opportunities authenticated page state
5. Existing CRM and approval history
6. CommissionCrowd API data

All writes are idempotent and fail closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
UTC = timezone.utc
from typing import Any

from .canonical import CanonicalOpportunity

# ── Lifecycle states ──────────────────────────────────────────────────
LIFECYCLE_DISCOVERED = "discovered"
LIFECYCLE_INVITED = "invited"
LIFECYCLE_FAVOURITED = "favourited"
LIFECYCLE_UNDER_REVIEW = "under_review"
LIFECYCLE_APPLICATION_DRAFT_PENDING = "application_draft_pending"
LIFECYCLE_APPLICATION_APPROVED = "application_approved"
LIFECYCLE_APPLICATION_SUBMITTED = "application_submitted"
LIFECYCLE_APPLICATION_REJECTED = "application_rejected"
LIFECYCLE_PRINCIPAL_ACCEPTED = "principal_accepted"
LIFECYCLE_ACTIVE = "active"
LIFECYCLE_PAUSED = "paused"
LIFECYCLE_CLOSED = "closed"
LIFECYCLE_WITHDRAWN = "withdrawn"
LIFECYCLE_EXPIRED = "expired"
LIFECYCLE_UNKNOWN = "unknown"

TERMINAL_STATES: set[str] = {
    LIFECYCLE_APPLICATION_REJECTED,
    LIFECYCLE_CLOSED,
    LIFECYCLE_WITHDRAWN,
    LIFECYCLE_EXPIRED,
    LIFECYCLE_ACTIVE,
    LIFECYCLE_PRINCIPAL_ACCEPTED,
    LIFECYCLE_APPLICATION_SUBMITTED,
    LIFECYCLE_APPLICATION_APPROVED,
}

# ── Source flags ──────────────────────────────────────────────────────
SOURCE_MY_OPPORTUNITIES = "in_my_opportunities"
SOURCE_MESSAGES = "in_messages"
SOURCE_HAS_INVITATION = "has_invitation"
SOURCE_FAVOURITES = "in_favourites"
SOURCE_FIND = "in_find_opportunities"
SOURCE_API = "returned_by_api"


@dataclass
class OpportunityStateRecord:
    """Canonical state record for a single opportunity across all sources."""

    opportunity_id: str
    title: str = ""
    principal_name: str = ""
    lifecycle_state: str = LIFECYCLE_UNKNOWN
    source_flags: set[str] = field(default_factory=set)
    commission_percent: float | None = None
    commission_text: str = ""
    residual_terms: bool = False
    territory: str = ""
    category: str = ""
    sales_motion: str = ""
    source_url: str = ""
    invitation_confidence: str = ""
    invitation_message_id: str = ""
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    data_quality_flags: list[str] = field(default_factory=list)
    requires_operator_review: bool = False
    conflicts: list[str] = field(default_factory=list)
    provenance: list[dict[str, str]] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    query_overlap_count: int = 1
    opportunity_id_missing: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def is_terminal(self) -> bool:
        return self.lifecycle_state in TERMINAL_STATES

    def is_eligible_for_application(self) -> bool:
        """Return True only if this opportunity is genuinely new."""
        if self.is_terminal():
            return False
        if SOURCE_MY_OPPORTUNITIES in self.source_flags:
            return False
        return self.lifecycle_state not in {
            LIFECYCLE_APPLICATION_SUBMITTED,
            LIFECYCLE_APPLICATION_APPROVED,
            LIFECYCLE_ACTIVE,
            LIFECYCLE_PRINCIPAL_ACCEPTED,
        }

    def add_provenance(self, source: str, route: str, retrieved_at: str = "") -> None:
        self.provenance.append(
            {
                "source": source,
                "route": route,
                "retrieved_at": retrieved_at or datetime.now(UTC).isoformat(),
            }
        )
        self.updated_at = datetime.now(UTC).isoformat()

    def record_hash(self) -> str:
        """Deterministic hash of the canonical state for lineage."""
        payload = {
            "opportunity_id": self.opportunity_id,
            "lifecycle_state": self.lifecycle_state,
            "source_flags": sorted(self.source_flags),
            "score": self.score,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def to_canonical_opportunity(self) -> CanonicalOpportunity | None:
        """Convert to CanonicalOpportunity for downstream pipeline use."""
        try:
            return CanonicalOpportunity(
                source="commissioncrowd",
                source_opportunity_id=self.opportunity_id,
                title=self.title,
                company_name=self.principal_name or None,
                commission_text=self.commission_text,
                commission_percent=self.commission_percent,
                residual_terms=self.residual_terms,
                territory=self.territory,
                category=self.category,
                data_quality_flags=self.data_quality_flags,
            )
        except Exception:
            return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "opportunity_id": self.opportunity_id,
            "title": self.title,
            "principal_name": self.principal_name,
            "lifecycle_state": self.lifecycle_state,
            "source_flags": sorted(self.source_flags),
            "commission_percent": self.commission_percent,
            "commission_text": self.commission_text,
            "residual_terms": self.residual_terms,
            "territory": self.territory,
            "category": self.category,
            "sales_motion": self.sales_motion,
            "source_url": self.source_url,
            "invitation_confidence": self.invitation_confidence,
            "invitation_message_id": self.invitation_message_id,
            "score": self.score,
            "reasons": self.reasons,
            "data_quality_flags": self.data_quality_flags,
            "requires_operator_review": self.requires_operator_review,
            "conflicts": self.conflicts,
            "provenance": self.provenance,
            "search_queries": self.search_queries,
            "query_overlap_count": self.query_overlap_count,
            "opportunity_id_missing": self.opportunity_id_missing,
            "record_hash": self.record_hash(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class OpportunityStateRegistry:
    """In-memory registry that reconciles all opportunity sources."""

    def __init__(self) -> None:
        self._records: dict[str, OpportunityStateRecord] = {}

    # ── Ingestion methods ───────────────────────────────────────────────

    def ingest_my_opportunities(
        self,
        items: list[dict[str, Any]],
    ) -> None:
        """Highest-precedence source: operator's account state."""
        for item in items:
            opp_id = str(item.get("opportunity_id", ""))
            if not opp_id:
                continue
            rec = self._get_or_create(opp_id)
            rec.title = item.get("title", rec.title)
            rec.principal_name = item.get("principal_name", rec.principal_name)
            rec.lifecycle_state = item.get("status", item.get("lifecycle_state", LIFECYCLE_ACTIVE))
            rec.commission_percent = item.get("commission_percent", rec.commission_percent)
            rec.commission_text = item.get("commission_text", rec.commission_text)
            rec.source_url = item.get("source_url", rec.source_url)
            rec.source_flags.add(SOURCE_MY_OPPORTUNITIES)
            rec.add_provenance(
                "my_opportunities",
                item.get("route", ""),
                item.get("retrieved_at", ""),
            )

    def ingest_messages(
        self,
        messages: list[dict[str, Any]],
    ) -> None:
        """Extract invitation classifications and link to opportunities."""
        for msg in messages:
            opp_id = str(msg.get("linked_opportunity_id", ""))
            if not opp_id:
                continue
            rec = self._get_or_create(opp_id)
            rec.source_flags.add(SOURCE_MESSAGES)
            classification = msg.get("classification", "uncertain")
            if classification in ("explicit_invitation", "likely_invitation"):
                rec.source_flags.add(SOURCE_HAS_INVITATION)
                rec.invitation_confidence = classification
                rec.invitation_message_id = str(msg.get("message_id", ""))
                if rec.lifecycle_state == LIFECYCLE_UNKNOWN:
                    rec.lifecycle_state = LIFECYCLE_INVITED
            rec.add_provenance(
                "messages",
                msg.get("route", ""),
                msg.get("retrieved_at", ""),
            )

    def ingest_favourites(
        self,
        items: list[dict[str, Any]],
    ) -> None:
        """Ingest Favourite Opportunities, respecting My Opportunities precedence."""
        for item in items:
            opp_id = str(item.get("opportunity_id", ""))
            if not opp_id:
                continue
            rec = self._get_or_create(opp_id)
            rec.title = item.get("title", rec.title)
            rec.principal_name = item.get("principal_name", rec.principal_name)
            rec.commission_percent = item.get("commission_percent", rec.commission_percent)
            rec.commission_text = item.get("commission_text", rec.commission_text)
            rec.source_flags.add(SOURCE_FAVOURITES)
            # Only override lifecycle if not already set by My Opportunities
            if SOURCE_MY_OPPORTUNITIES not in rec.source_flags and rec.lifecycle_state in {
                LIFECYCLE_UNKNOWN,
                LIFECYCLE_DISCOVERED,
            }:
                rec.lifecycle_state = LIFECYCLE_FAVOURITED
            rec.add_provenance(
                "favourites",
                item.get("route", ""),
                item.get("retrieved_at", ""),
            )

    def ingest_find_opportunities(
        self,
        items: list[dict[str, Any]],
    ) -> None:
        """Ingest search results, lowest precedence for lifecycle state."""
        for item in items:
            opp_id = str(item.get("opportunity_id", ""))
            if not opp_id:
                continue
            rec = self._get_or_create(opp_id)
            # Do not overwrite fields already set by My Opportunities
            has_account_data = SOURCE_MY_OPPORTUNITIES in rec.source_flags
            if not has_account_data:
                rec.title = item.get("title", rec.title) or rec.title
                rec.principal_name = (
                    item.get("principal_name", rec.principal_name) or rec.principal_name
                )
            rec.commission_percent = (
                item.get("commission_percent", rec.commission_percent) or rec.commission_percent
            )
            rec.commission_text = (
                item.get("commission_text", rec.commission_text) or rec.commission_text
            )
            rec.territory = item.get("territory", rec.territory) or rec.territory
            rec.category = item.get("category", rec.category) or rec.category
            rec.source_url = item.get("source_url", rec.source_url) or rec.source_url
            rec.source_flags.add(SOURCE_FIND)
            if rec.lifecycle_state == LIFECYCLE_UNKNOWN:
                rec.lifecycle_state = LIFECYCLE_DISCOVERED
            # Merge multi-query provenance
            query = item.get("search_query", "")
            if query and query not in rec.search_queries:
                rec.search_queries.append(query)
                rec.query_overlap_count = len(rec.search_queries)
            rec.opportunity_id_missing = False
            rec.add_provenance(
                "find_opportunities",
                item.get("route", ""),
                item.get("retrieved_at", ""),
            )

    def ingest_api_data(
        self,
        opportunities: list[CanonicalOpportunity],
    ) -> None:
        """Enrich with API data — never overrides account-specific state."""
        for opp in opportunities:
            opp_id = opp.source_opportunity_id
            rec = self._get_or_create(opp_id)
            has_account_data = SOURCE_MY_OPPORTUNITIES in rec.source_flags
            if not has_account_data:
                rec.title = opp.title or rec.title
                rec.principal_name = opp.company_name or rec.principal_name
            rec.commission_percent = opp.commission_percent or rec.commission_percent
            rec.commission_text = opp.commission_text or rec.commission_text
            rec.residual_terms = opp.residual_terms or rec.residual_terms
            rec.territory = opp.territory or rec.territory
            rec.category = opp.category or rec.category
            rec.source_url = opp.source_url or rec.source_url
            rec.data_quality_flags = opp.data_quality_flags or rec.data_quality_flags
            rec.source_flags.add(SOURCE_API)
            rec.add_provenance("api", "list_opportunities")

    # ── Reconciliation ──────────────────────────────────────────────────

    def reconcile(self) -> dict[str, Any]:
        """Cross-check all records for conflicts and eligibility."""
        summary: dict[str, Any] = {
            "total": len(self._records),
            "eligible": 0,
            "ineligible": 0,
            "invitations": 0,
            "favourites": 0,
            "find_results": 0,
            "conflicts": [],
        }
        for rec in self._records.values():
            if rec.is_eligible_for_application():
                summary["eligible"] += 1
            else:
                summary["ineligible"] += 1
            if SOURCE_HAS_INVITATION in rec.source_flags:
                summary["invitations"] += 1
            if SOURCE_FAVOURITES in rec.source_flags:
                summary["favourites"] += 1
            if SOURCE_FIND in rec.source_flags:
                summary["find_results"] += 1

            # Detect conflicts
            if SOURCE_MY_OPPORTUNITIES in rec.source_flags and SOURCE_FIND in rec.source_flags:
                rec.conflicts.append("my_opportunities_vs_find_opportunities")
            if rec.lifecycle_state == LIFECYCLE_ACTIVE and rec.is_eligible_for_application():
                rec.conflicts.append("active_but_marked_eligible")
                rec.requires_operator_review = True

        return summary

    def get_eligible(self) -> list[OpportunityStateRecord]:
        """Return net-new candidates ready for qualification."""
        return [r for r in self._records.values() if r.is_eligible_for_application()]

    def get_by_id(self, opportunity_id: str) -> OpportunityStateRecord | None:
        return self._records.get(opportunity_id)

    def to_list(self) -> list[OpportunityStateRecord]:
        return list(self._records.values())

    def to_dict_list(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._records.values()]

    def _get_or_create(self, opportunity_id: str) -> OpportunityStateRecord:
        if opportunity_id not in self._records:
            self._records[opportunity_id] = OpportunityStateRecord(opportunity_id=opportunity_id)
        return self._records[opportunity_id]
