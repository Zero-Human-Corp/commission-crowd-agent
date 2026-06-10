"""Canonical opportunity model — single source of truth for CommissionCrowd data.

Unifies the disparate representations across the codebase:
- CommissionCrowd API raw dict
- BrowserBasedProspector sample dict
- LeadScorer list[str] row input
- CRM pipeline dict
- Approval gate entity bindings

Design goals:
- Every opportunity flowing through the MVP uses this model.
- Null/missing fields stay null; no synthetic injection.
- commission_percent is parsed deterministically from text.
- data_quality_flags surface missing/incomplete data for scoring.
- to_crm_dict() and to_approval_binding() produce shapes expected by downstream code.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class CanonicalOpportunity(BaseModel):
    """Unified opportunity representation used across the entire pipeline."""

    # ── Identity ──────────────────────────────────────────────────────────
    source: str = "commissioncrowd"
    source_opportunity_id: str = Field(..., description="Platform-specific ID (e.g. '30130')")
    ref: str = ""
    title: str = ""
    slug: str = ""

    # ── Company / Principal ───────────────────────────────────────────────
    company_name: str | None = None
    company_id: int | None = None
    description: str = ""
    short_summary: str = ""
    usp: str = ""

    # ── Commercial terms ──────────────────────────────────────────────────
    commission_text: str = ""
    commission_percent: float | None = None
    residual_terms: bool = False
    deal_value_usd: int | None = None
    payment_terms: str = ""

    # ── Territory & market ──────────────────────────────────────────────
    territory: str = ""
    territory_details: str = ""
    global_territory: bool = False
    countries: list[int] = Field(default_factory=list)
    world_regions: list[int] = Field(default_factory=list)

    # ── Category / Industry ─────────────────────────────────────────────
    category: str = ""  # Primary industry name (resolved from code list if known)
    industries: list[int] = Field(default_factory=list)
    target_industries: list[int] = Field(default_factory=list)
    products: list[int] = Field(default_factory=list)

    # ── Contact ─────────────────────────────────────────────────────────
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None

    # ── Engagement & viability signals ──────────────────────────────────
    active: bool = True
    view_count: int = 0
    application_count: int = 0
    agent_count: int = 0
    invitation_count: int = 0
    completeness: int = 0  # 0–100 profile completeness score from platform

    # ── Provenance ──────────────────────────────────────────────────────
    raw_provenance: dict[str, Any] = Field(default_factory=dict)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data_quality_flags: list[str] = Field(default_factory=list)

    # ── Computed helpers (not stored, derived) ──────────────────────────
    @property
    def has_email(self) -> bool:
        return bool(self.contact_email)

    @property
    def has_phone(self) -> bool:
        return bool(self.contact_phone)

    @property
    def display_name(self) -> str:
        return self.title or self.ref or self.source_opportunity_id

    @property
    def source_url(self) -> str:
        """Best-effort public URL based on slug."""
        if self.slug:
            return f"https://www.commissioncrowd.com/opportunities/{self.slug}"
        return ""

    def payload_hash(self, action_type: str, target: str, body: str) -> str:
        """Deterministic SHA-256 over the action binding."""
        payload = json.dumps(
            {
                "action_type": action_type,
                "opportunity_id": self.source_opportunity_id,
                "target": target,
                "body": body,
            },
            sort_keys=True,
            ensure_ascii=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_crm_dict(self) -> dict[str, Any]:
        """Shape expected by CRMPipeline.add_lead / opportunities tab."""
        return {
            "source": self.source,
            "source_id": self.source_opportunity_id,
            "ref": self.ref,
            "title": self.title,
            "company_name": self.company_name or "",
            "contact_name": self.contact_name or "",
            "contact_email": self.contact_email or "",
            "territory": self.territory or self.territory_details,
            "category": self.category,
            "commission_text": self.commission_text,
            "commission_percent": (
                str(self.commission_percent) if self.commission_percent is not None else ""
            ),
            "residual_terms": "yes" if self.residual_terms else "no",
            "active": "yes" if self.active else "no",
            "url": self.source_url,
            "quality_flags": " | ".join(self.data_quality_flags),
            "fetched_at": self.fetched_at.isoformat(),
        }

    def to_approval_binding(self, action_type: str, target: str, body: str) -> dict[str, Any]:
        """Shape consumed by ApprovalGate.create_and_write_approval."""
        return {
            "entity_type": "opportunity",
            "entity_id": self.source_opportunity_id,
            "entity_name": self.display_name,
            "requested_action": action_type,
            "source_url": self.source_url,
            "notes": (
                f"Commission: {self.commission_text or 'unknown'} | "
                f"Territory: {self.territory or 'unknown'} | "
                f"Flags: {', '.join(self.data_quality_flags)}"
            ),
            "payload_hash": self.payload_hash(action_type, target, body),
        }

    @classmethod
    def from_commissioncrowd_api(cls, raw: dict[str, Any]) -> CanonicalOpportunity:
        """Deterministic adapter from CommissionCrowd REST API dict."""
        # ── Parse commission percent from multiple possible sources ───────
        pct = _parse_commission_percent(raw)
        residual = _detect_residual(raw.get("commission", ""))
        deal_val = _parse_deal_value(raw.get("commission", ""))

        # ── Derive quality flags early ────────────────────────────────────
        flags: list[str] = []
        if not raw.get("email"):
            flags.append("missing_contact_email")
        if not raw.get("phone"):
            flags.append("missing_contact_phone")
        if not raw.get("commission"):
            flags.append("missing_commission_text")
        if pct is None:
            flags.append("unclear_commission_rate")
        if not raw.get("territory_details") and not raw.get("global_territory"):
            flags.append("unclear_territory")

        # ── Build the canonical instance ──────────────────────────────────
        return cls(
            source="commissioncrowd",
            source_opportunity_id=str(raw.get("id", "")),
            ref=raw.get("ref", ""),
            title=raw.get("name", ""),
            slug=raw.get("latest_slug", ""),
            company_name=_safe_company_name(raw),
            company_id=raw.get("company"),
            description=_strip_html(raw.get("description", "")),
            short_summary=_strip_html(raw.get("short_summary", "")),
            usp=_strip_html(raw.get("usp", "")),
            commission_text=raw.get("commission", ""),
            commission_percent=pct,
            residual_terms=residual,
            deal_value_usd=deal_val,
            payment_terms=raw.get("payment_terms", ""),
            territory=raw.get("territory_details", ""),
            territory_details=raw.get("territory_details", ""),
            global_territory=bool(raw.get("global_territory")),
            countries=_as_int_list(raw.get("countries")),
            world_regions=_as_int_list(raw.get("world_regions")),
            category="",  # resolved later via lookup if needed
            industries=_as_int_list(raw.get("industries")),
            target_industries=_as_int_list(raw.get("target_industries")),
            products=_as_int_list(raw.get("products")),
            contact_name="",  # CommissionCrowd listings don't expose contact name
            contact_email=raw.get("email") or None,
            contact_phone=raw.get("phone") or None,
            active=bool(raw.get("active", True)),
            view_count=int(raw.get("view_count", 0) or 0),
            application_count=int(raw.get("application_count", 0) or 0),
            agent_count=int(raw.get("agent_count", 0) or 0),
            invitation_count=int(raw.get("invitation_count", 0) or 0),
            completeness=int(raw.get("completeness", 0) or 0),
            raw_provenance=raw,
            fetched_at=datetime.now(UTC),
            data_quality_flags=flags,
        )

    @classmethod
    def sample_opportunities(
        cls,
        *,
        mode: str = "sample",
        limit: int = 4,
    ) -> list[CanonicalOpportunity]:
        """Explicit sample fixture. Only invoked when mode == 'sample'.

        These use the SAME canonical model so tests, dry-run, and live
        pipelines share one shape.
        """
        if mode != "sample":
            raise ValueError(f"sample_opportunities called with mode={mode!r}; use 'sample'")

        # Note: names changed from legacy samples (SecureFlow, IntellectAI, etc.)
        # to generic identifiers so synthetic contamination tests can reject them.
        samples: list[dict[str, Any]] = [
            {
                "source_opportunity_id": "SAMPLE-1001",
                "ref": "SAMPLE-001",
                "title": "SAMPLE Cybersecurity SaaS — North America",
                "slug": "sample-cybersecurity-na",
                "commission_text": "20% recurring on annual contracts ($5,000–$25,000 ACV)",
                "commission_percent": 20.0,
                "residual_terms": True,
                "territory": "North America",
                "territory_details": "North America",
                "category": "SaaS / Cybersecurity",
                "active": True,
                "contact_email": "sample@example.com",
            },
            {
                "source_opportunity_id": "SAMPLE-1002",
                "ref": "SAMPLE-002",
                "title": "SAMPLE AI CRM — UK & Ireland",
                "slug": "sample-ai-crm-uk",
                "commission_text": "25% on first-year revenue",
                "commission_percent": 25.0,
                "residual_terms": False,
                "territory": "UK & Ireland",
                "territory_details": "UK & Ireland",
                "category": "AI / CRM",
                "active": True,
                "contact_email": "sample@example.com",
            },
        ]
        return [cls(source="sample", **s) for s in samples[:limit]]


# ────────────────────────── Helper functions ──────────────────────────


def _parse_commission_percent(raw: dict[str, Any]) -> float | None:
    """Extract a numeric commission percentage from raw API data.

    Priority:
    1. ``commission_pc`` (string like "20.00")
    2. ``name`` / ``title`` text
    3. ``commission`` free-text description
    Returns None if no clear percentage found.
    """
    # 1. Direct field
    pc = raw.get("commission_pc")
    if pc is not None:
        try:
            return float(str(pc).strip())
        except ValueError:
            pass

    # 2. Title text
    for field in ("name", "title"):
        val = raw.get(field, "")
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", str(val))
        if m:
            return float(m.group(1))

    # 3. Commission description text
    comm = str(raw.get("commission", ""))
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", comm)
    if m:
        return float(m.group(1))

    # 4. Phrases like "up to 20 %"
    m = re.search(r"up\s+to\s+(\d+(?:\.\d+)?)", comm, re.IGNORECASE)
    if m:
        return float(m.group(1))

    # 5. "X percent" or "Xpc"
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:percent|pc)\b", comm, re.IGNORECASE)
    if m:
        return float(m.group(1))

    return None


def _detect_residual(text: str) -> bool:
    """True if commission text mentions residual, lifetime, or recurring."""
    if not text:
        return False
    t = text.lower()
    return any(word in t for word in ("residual", "lifetime", "recurring", "ongoing", "monthly"))


def _parse_deal_value(text: str) -> int | None:
    """Extract an upper-bound USD deal value from commission text."""
    if not text:
        return None
    # Range: "$5,000–$25,000" -> 25000
    m = re.search(r"\$[\d,]+\s*[-–]\s*\$?([\d,]+)", text)
    if m:
        return int(m.group(1).replace(",", ""))
    # Single: "$25,000 ACV"
    m = re.search(r"\$([\d,]+)\s+(?:ACV|deal|sale)", text, re.IGNORECASE)
    if m:
        return int(m.group(1).replace(",", ""))
    return None


def _safe_company_name(raw: dict[str, Any]) -> str | None:
    """Extract company name from nested structures if present."""
    # API returns `company` as an integer FK. We can't resolve it without
    # a company lookup. Return None to avoid fabrication.
    comp = raw.get("company")
    if isinstance(comp, dict):
        return comp.get("name") or comp.get("title") or None
    return None


def _strip_html(text: str | None) -> str:
    """Minimal HTML tag stripper for CommissionCrowd descriptions."""
    if not text:
        return ""
    # Replace common tags with whitespace
    cleaned = re.sub(r"<[^>]+>", " ", str(text))
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _as_int_list(value: Any) -> list[int]:
    """Coerce API list-of-int response to Python list[int]."""
    if isinstance(value, list):
        return [int(x) for x in value if isinstance(x, (int, str)) and str(x).isdigit()]
    return []
