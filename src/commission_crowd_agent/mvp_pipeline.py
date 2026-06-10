"""MVP pipeline — live data shadow and controlled-write runner.

Fetches real CommissionCrowd opportunities, converts to CanonicalOpportunity,
scores them, and either reports without writes (live-shadow) or writes
qualified records to CRM + approvals (controlled-write).

Execution modes:
- live-shadow:   real data, zero external writes (default)
- controlled-write: real data, CRM + approval writes only
- sample:        explicit sample fixtures, no live API calls

All modes print an execution summary before running.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.table import Table

from .canonical import CanonicalOpportunity
from .commissioncrowd_adapter import CommissionCrowdApiAdapter
from .config import load_settings

console = Console()


def _build_summary_table(mode: str, limit: int, min_commission: float) -> Table:
    table = Table(title="CCA MVP Execution Mode")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Mode", mode)
    table.add_row("Limit", str(limit))
    table.add_row("Min Commission %", str(min_commission))
    return table


def fetch_live_opportunities(*, limit: int = 5) -> list[CanonicalOpportunity]:
    """Fetch live opportunities from CommissionCrowd API and convert to canonical."""
    settings = load_settings()
    adapter = CommissionCrowdApiAdapter(
        api_key=settings.commissioncrowd_api_key,
        dry_run=False,
    )
    result = adapter.list_opportunities(page=1, limit=limit)
    if not result.get("ok"):
        raise RuntimeError(f"API fetch failed: {result.get('error')}")

    raw_items = result.get("data", {}).get("items", [])
    canonicals: list[CanonicalOpportunity] = []
    for raw in raw_items:
        try:
            canonicals.append(CanonicalOpportunity.from_commissioncrowd_api(raw))
        except Exception as exc:
            console.print(f"[yellow]⚠ Skipped invalid record: {exc}[/yellow]")
    return canonicals


def score_opportunities(
    opps: list[CanonicalOpportunity],
    *,
    min_commission_pct: float = 20.0,
    operator_territory: str = "",
) -> list[dict[str, Any]]:
    """Score each opportunity and produce evidence-based explanations.

    Scoring factors (all evidence-based, no LLM hallucination):
    1. Commission rate (0–30 pts)
    2. Territory fit (0–20 pts)
    3. Residual terms (0–15 pts)
    4. Data completeness (0–15 pts)
    5. Enablement / training (0–10 pts)
    6. Market signals (0–10 pts)
    """
    scored: list[dict[str, Any]] = []
    for opp in opps:
        score = 0
        reasons: list[str] = []
        flags = list(opp.data_quality_flags)
        missing: list[str] = []

        # 1. Commission rate
        pct = opp.commission_percent
        if pct is not None:
            if pct >= 25:
                score += 30
                reasons.append(f"High commission ({pct}%)")
            elif pct >= 20:
                score += 25
                reasons.append(f"Solid commission ({pct}%)")
            elif pct >= 15:
                score += 15
                reasons.append(f"Moderate commission ({pct}%)")
            else:
                score += 5
                reasons.append(f"Low commission ({pct}%)")
        else:
            missing.append("commission_percent")
            reasons.append("Commission rate unclear")

        # 2. Territory fit
        terr = (opp.territory or opp.territory_details or "").lower()
        if operator_territory and operator_territory.lower() in terr:
            score += 20
            reasons.append(f"Territory match: {opp.territory or opp.territory_details}")
        elif opp.global_territory:
            score += 15
            reasons.append("Global territory available")
        elif terr:
            score += 10
            reasons.append(f"Territory: {opp.territory or opp.territory_details}")
        else:
            missing.append("territory")
            reasons.append("Territory unspecified")

        # 3. Residual terms
        if opp.residual_terms:
            score += 15
            reasons.append("Residual/recurring commissions")
        elif "residual" in opp.commission_text.lower() or "lifetime" in opp.commission_text.lower():
            score += 15
            reasons.append("Residual/recurring commissions (text)")
            opp.residual_terms = True
        else:
            score += 0
            reasons.append("No residual terms")

        # 4. Data completeness
        completeness = opp.completeness
        if completeness >= 80:
            score += 15
            reasons.append(f"High profile completeness ({completeness}%)")
        elif completeness >= 50:
            score += 10
            reasons.append(f"Moderate completeness ({completeness}%)")
        else:
            score += 5
            reasons.append(f"Low completeness ({completeness}%)")

        # 5. Enablement / training
        training_text = (opp.raw_provenance.get("training_and_support", "") or "").lower()
        if training_text and len(training_text) > 50:
            score += 10
            reasons.append("Training/support provided")
        else:
            missing.append("training_and_support")

        # 6. Market signals (engagement)
        if opp.application_count >= 10 or opp.view_count >= 100:
            score += 10
            reasons.append("Strong market interest")
        elif opp.application_count >= 5 or opp.view_count >= 50:
            score += 5
            reasons.append("Moderate market interest")
        else:
            reasons.append("Limited market data")

        # Threshold gate
        passes_threshold = pct is not None and pct >= min_commission_pct

        # Clamp score
        score = min(100, max(0, score))

        # Determine recommended action
        if not passes_threshold:
            recommended = "reject_below_threshold"
        elif score >= 70:
            recommended = "draft_application"
        elif score >= 50:
            recommended = "operator_review"
        else:
            recommended = "research"

        scored.append(
            {
                "opportunity": opp,
                "score": score,
                "passes_threshold": passes_threshold,
                "reasons": reasons,
                "missing": missing,
                "flags": flags,
                "recommended": recommended,
            }
        )
    return scored


def filter_qualified(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return only opportunities that pass the commission threshold."""
    return [s for s in scored if s["passes_threshold"]]


def generate_application_draft(opp: CanonicalOpportunity, settings: Any) -> dict[str, str]:
    """Generate a truthful application draft from real opportunity data only.

    No fabricated achievements. Unknowns become questions.
    """
    sender_name = getattr(settings, "operator_name", "") or "Your Name"
    sender_email = getattr(settings, "operator_email", "") or ""
    sender_phone = getattr(settings, "operator_phone", "") or ""
    territory = (opp.territory or opp.territory_details or "as specified").strip()

    subject = f"Independent Sales Representative Application — {opp.title[:50]}"

    body_lines: list[str] = [
        "Dear Hiring Team,",
        "",
        (
            f"I am writing to express my interest in representing "
            f"{opp.title} as an independent commission-only "
            f"sales representative."
        ),
        "",
        "Why This Opportunity Fits Me:",
        f"- Commission structure: {opp.commission_text or 'To be clarified'}",
        f"- Target territory: {territory}",
        f"- Residual terms: {'Yes' if opp.residual_terms else 'Not specified'}",
        "",
        "Proposed Approach:",
        f"- Focus on B2B outreach within {territory}",
        "- Leverage existing professional network for warm introductions",
        "- Prioritise relationship-building over volume",
        "",
        "First 30-Day Plan:",
        "1. Deep-dive into product materials and competitive positioning",
        "2. Map target accounts and decision-makers in assigned territory",
        "3. Initiate 20+ outbound conversations per week",
        "4. Deliver weekly pipeline updates",
        "",
        "Questions Requiring Clarification:",
    ]

    if not opp.commission_percent:
        body_lines.append("- What is the exact commission percentage and payment schedule?")
    if not opp.residual_terms:
        body_lines.append("- Are there residual or recurring commission components?")
    if not opp.contact_email:
        body_lines.append("- What is the best direct contact for application follow-up?")
    if not opp.deal_value_usd:
        body_lines.append("- What is the typical deal size or ACV?")

    body_lines.extend(
        [
            "",
            "I look forward to discussing how I can contribute to your growth.",
            "",
            f"{sender_name}",
        ]
    )
    if sender_email:
        body_lines.append(sender_email)
    if sender_phone:
        body_lines.append(sender_phone)

    body = "\n".join(body_lines)
    return {"subject": subject, "body": body}


def run_live_shadow(
    *,
    limit: int = 5,
    min_commission: float = 20.0,
) -> dict[str, Any]:
    """Live-shadow mode: real data, zero external writes."""
    console.print(_build_summary_table("live-shadow", limit, min_commission))

    # Fetch live data
    opps = fetch_live_opportunities(limit=limit)
    if not opps:
        return {"ok": False, "error": "No opportunities fetched", "mode": "live-shadow"}

    # Score
    scored = score_opportunities(opps, min_commission_pct=min_commission)
    qualified = filter_qualified(scored)

    # Verify lineage: all IDs must trace back to live API
    source_ids = {opp.source_opportunity_id for opp in opps}
    scored_ids = {s["opportunity"].source_opportunity_id for s in scored}
    if scored_ids - source_ids:
        return {
            "ok": False,
            "error": "Lineage contamination detected — synthetic data in pipeline",
            "mode": "live-shadow",
        }

    # Check synthetic contamination
    synthetic_names = {
        "SecureFlow Technologies",
        "IntellectAI",
        "NimbusWatch",
        "PeopleFirst",
    }
    for s in scored:
        comp = s["opportunity"].company_name
        sid = s["opportunity"].source_opportunity_id
        if comp in synthetic_names or "SAMPLE" in sid:
            return {
                "ok": False,
                "error": f"Synthetic contamination: {s['opportunity'].source_opportunity_id}",
                "mode": "live-shadow",
            }

    # Generate drafts (in-memory only)
    settings = load_settings()
    drafts: list[dict[str, Any]] = []
    for q in qualified[:2]:  # max 2 for MVP
        draft = generate_application_draft(q["opportunity"], settings)
        payload_hash = q["opportunity"].payload_hash(
            action_type="apply_to_principal",
            target="CommissionCrowd",
            body=draft["body"],
        )
        drafts.append(
            {
                "opportunity_id": q["opportunity"].source_opportunity_id,
                "title": q["opportunity"].title,
                "score": q["score"],
                "draft": draft,
                "payload_hash": payload_hash,
            }
        )

    return {
        "ok": True,
        "mode": "live-shadow",
        "total_fetched": len(opps),
        "scored": len(scored),
        "qualified": len(qualified),
        "rejected": len(scored) - len(qualified),
        "drafts_prepared": len(drafts),
        "drafts": drafts,
        "source_ids": sorted(source_ids),
        "sheets_written": 0,
        "approvals_created": 0,
        "emails_sent": 0,
        "calendars_created": 0,
    }


def run_controlled_write(
    *,
    limit: int = 5,
    min_commission: float = 20.0,
) -> dict[str, Any]:
    """Controlled-write mode: real data, CRM + approvals only."""
    console.print(_build_summary_table("controlled-write", limit, min_commission))

    from .adapters import GoogleSheetsAdapter
    from .approval_gate import ApprovalGate
    from .crm_pipeline import CRMPipeline

    settings = load_settings()
    sheets = GoogleSheetsAdapter(
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        credentials_path=settings.google_application_credentials_path,
        dry_run=False,
    )
    crm = CRMPipeline(sheets_adapter=sheets)
    gate = ApprovalGate(sheets_adapter=sheets)

    # Fetch and score
    opps = fetch_live_opportunities(limit=limit)
    scored = score_opportunities(opps, min_commission_pct=min_commission)
    qualified = filter_qualified(scored)

    # Track counts
    created = 0
    updated = 0
    duplicates = 0
    approvals_created = 0

    for q in qualified[:2]:
        opp = q["opportunity"]
        # Idempotent CRM write
        crm_result = crm.add_lead(
            lead_id=f"CC-{opp.source_opportunity_id}",
            company_name=opp.title,
            contact_name=opp.contact_name or "",
            contact_email=opp.contact_email or "",
            source=opp.source,
            source_url=opp.source_url,
            notes=f"Score={q['score']}; reasons={' | '.join(q['reasons'])}",
            dry_run=False,
        )
        if crm_result.get("dedup"):
            duplicates += 1
        elif crm_result.get("ok"):
            created += 1

        # Create approval (draft is generated inline; no need to store)
        approval_req = gate.create_and_write_approval(
            entity_type="opportunity",
            entity_id=opp.source_opportunity_id,
            entity_name=opp.title,
            requested_action="apply_to_principal",
            approval_action="apply_to_principal",
            risk_level="medium" if q["score"] >= 70 else "high",
            source_url=opp.source_url,
            notes=f"Commission: {opp.commission_text or 'unknown'} | Score: {q['score']}",
        )
        if approval_req.approval_id:
            approvals_created += 1

    return {
        "ok": True,
        "mode": "controlled-write",
        "total_fetched": len(opps),
        "qualified": len(qualified),
        "rejected": len(scored) - len(qualified),
        "crm_created": created,
        "crm_updated": updated,
        "duplicates": duplicates,
        "approvals_created": approvals_created,
        "sheets_written": created + updated + approvals_created,
        "emails_sent": 0,
        "calendars_created": 0,
    }
