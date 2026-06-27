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
from .supervisor_relay import SupervisorRelay, SupervisorTaskType
from .workflows.approvals import ApprovalPack, _infer_target_size, send_approval_request

console = Console()


def _build_summary_table(mode: str, limit: int, min_commission: float, min_deal_size: int = 50000) -> Table:
    table = Table(title="CCA MVP Execution Mode")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Mode", mode)
    table.add_row("Limit", str(limit))
    table.add_row("Min Commission %", str(min_commission))
    table.add_row("Min Deal Size USD", f"${min_deal_size:,}")
    return table


def _controlled_write_checkpoint(
    qualified_count: int,
    min_deal_size: int,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Option 2: explicit SupervisorRelay checkpoint before controlled writes.

    Workstream B routes through the configured draft-review model
    (``kimi-k2-thinking``). The checkpoint reviews the planned controlled-write
    plan and only permits non-blocked actions.
    """
    prompt = (
        f"Controlled-write MVP is about to run.\n"
        f"Qualified opportunities: {qualified_count}\n"
        f"Minimum deal size: ${min_deal_size:,}\n"
        f"Workstream dry_run: {dry_run}\n"
        f"Planned actions: create CRM lead rows, create approval rows in Sheets, "
        f"and dispatch Telegram approval requests.\n"
        f"In dry_run mode, no actual CRM/Sheets writes or Telegram sends occur; "
        f"only simulated approval-request messages are generated for operator review.\n\n"
        f"Review this plan. Return JSON with approved (bool), reason (str), "
        f"recommended_action (str), risk_level (low|medium|high|unknown), and notes (str)."
    )
    system = (
        "You are the CCA draft-review supervisor. Review outreach and write plans. "
        "Block any recommendation that would apply, send messages, or spend money. "
        "Approve only safe read-only or approval-request steps. Respond only with JSON."
    )
    # Option 2: supervisor inference is independent of pipeline write dry-run.
    relay_dry_run = __import__("os").environ.get("CCA_SUPERVISOR_INFERENCE_DRY_RUN", "").lower() in {"1", "true"}
    relay = SupervisorRelay(dry_run=relay_dry_run)
    try:
        resp = relay.route(SupervisorTaskType.DRAFT_REVIEW, prompt, system=system)
        return {
            "ok": resp.approved and not _is_blocked_for_pipeline(resp.recommended_action),
            "approved": resp.approved,
            "human_approval_required": resp.human_approval_required,
            "risk_level": resp.risk_level,
            "reason": resp.reason,
            "recommended_action": resp.recommended_action,
            "requested_model": resp.requested_model,
            "actual_model": resp.actual_model,
            "fallback_reason": resp.fallback_reason,
        }
    except Exception as exc:
        return {
            "ok": False,
            "approved": False,
            "reason": f"Checkpoint error: {exc}",
            "recommended_action": "",
        }


def _is_blocked_for_pipeline(action: str) -> bool:
    """Return True if the supervisor's recommended action is blocked for this pipeline."""
    normalized = action.strip().lower().replace(" ", "_")
    blocked = {"send", "apply", "message", "login", "api_call", "spend", "approval_status_change"}
    return normalized in blocked or any(normalized.startswith(f"{verb}_") for verb in blocked)


def _sample_opportunities() -> list[CanonicalOpportunity]:
    """Return a small set of realistic sample opportunities for dry-run demos."""
    return [
        CanonicalOpportunity(
            source="commissioncrowd",
            source_opportunity_id="SAMPLE-22763",
            title="Cutting Edge Platform Connecting Companies & Social Influencers Globally",
            company_name="Sample Principal Ltd",
            commission_text="30% commission + lifetime residuals",
            commission_percent=30.0,
            residual_terms=True,
            territory="Global",
            category="Business Services",
            source_url="https://www.commissioncrowd.com/app/#/opportunities/22763",
            contact_email="ops@sampleprincipal.example",
            contact_name="Sample Hiring Team",
        ),
        CanonicalOpportunity(
            source="commissioncrowd",
            source_opportunity_id="SAMPLE-6655",
            title="AI-Powered B2B Sales Enablement SaaS",
            company_name="Another Sample Inc",
            commission_text="20% recurring commission",
            commission_percent=20.0,
            residual_terms=True,
            territory="United States",
            category="Software",
            source_url="https://www.commissioncrowd.com/app/#/opportunities/6655",
            contact_email="sales@anothersample.example",
            contact_name="Another Team",
        ),
        CanonicalOpportunity(
            source="commissioncrowd",
            source_opportunity_id="SAMPLE-LOW",
            title="Low Commission Generic Opportunity",
            company_name="Low Payer LLC",
            commission_text="5% one-time",
            commission_percent=5.0,
            residual_terms=False,
            territory="",
            category="",
            source_url="",
            contact_email="",
            contact_name="",
        ),
    ]


def fetch_live_opportunities(*, limit: int = 5, sample: bool = False) -> list[CanonicalOpportunity]:
    """Fetch live opportunities from CommissionCrowd API or return sample fixtures."""
    if sample:
        return _sample_opportunities()[:limit]

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
    min_deal_value_usd: int = 50000,
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

        # Threshold gate: commission ≥ min AND (deal size unknown OR ≥ $50k)
        passes_commission = pct is not None and pct >= min_commission_pct
        passes_deal_size = opp.deal_value_usd is None or opp.deal_value_usd >= min_deal_value_usd
        passes_threshold = passes_commission and passes_deal_size
        if opp.deal_value_usd is not None and opp.deal_value_usd < min_deal_value_usd:
            flags.append("deal_size_below_threshold")
            reasons.append(f"Deal size ${opp.deal_value_usd:,} below ${min_deal_value_usd:,} minimum")
        elif opp.deal_value_usd is None:
            missing.append("deal_value_usd")
            flags.append("deal_size_unknown")

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
    min_deal_size: int = 50000,
) -> dict[str, Any]:
    """Live-shadow mode: real data, zero external writes."""
    console.print(_build_summary_table("live-shadow", limit, min_commission, min_deal_size))

    # Fetch live data
    opps = fetch_live_opportunities(limit=limit)
    if not opps:
        return {"ok": False, "error": "No opportunities fetched", "mode": "live-shadow"}

    # Score
    scored = score_opportunities(opps, min_commission_pct=min_commission, min_deal_value_usd=min_deal_size)
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
    min_deal_size: int = 50000,
    dry_run: bool = True,
    notify: bool = True,
    sample: bool = False,
) -> dict[str, Any]:
    """Controlled-write mode: real data, CRM + approvals only.

    Args:
        dry_run: If True, no Sheets/CRM writes and Telegram sends are simulated.
        notify: If True, dispatch Telegram approval requests for created approvals.
        sample: If True, use fixture opportunities instead of the live API.
    """
    mode_label = "controlled-write" + (" (sample)" if sample else "")
    console.print(_build_summary_table(mode_label, limit, min_commission, min_deal_size))

    from .adapters import GoogleSheetsAdapter, NotifierAdapter
    from .approval_gate import ApprovalGate
    from .crm_pipeline import CRMPipeline

    settings = load_settings()
    sheets = GoogleSheetsAdapter(
        spreadsheet_id=settings.google_sheets_spreadsheet_id,
        credentials_path=settings.google_application_credentials_path,
        dry_run=dry_run,
    )
    crm = CRMPipeline(sheets_adapter=sheets)
    gate = ApprovalGate(sheets_adapter=sheets)
    notifier: NotifierAdapter | None = None
    if notify:
        notifier = NotifierAdapter(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
            dry_run=dry_run,
        )

    # Option 2 SupervisorRelay checkpoint (Workstream B: kimi-k2-thinking)
    # We estimate qualified count after scoring, so checkpoint after fetch+score.
    opps = fetch_live_opportunities(limit=limit, sample=sample)
    scored = score_opportunities(opps, min_commission_pct=min_commission, min_deal_value_usd=min_deal_size)
    qualified = filter_qualified(scored)

    checkpoint = _controlled_write_checkpoint(len(qualified), min_deal_size, dry_run=dry_run)
    console.print(f"[cyan]Supervisor checkpoint:[/cyan] {checkpoint}")
    if not checkpoint.get("ok"):
        return {
            "ok": False,
            "error": f"Supervisor did not approve controlled-write: {checkpoint.get('reason')}",
            "mode": "controlled-write",
            "checkpoint": checkpoint,
        }

    # Track counts
    created = 0
    updated = 0
    duplicates = 0
    approvals_created = 0
    notifications_sent = 0

    for q in qualified[:2]:
        opp = q["opportunity"]

        # Idempotent CRM write — only if email present
        crm_result: dict[str, Any] = {"ok": True, "dedup": True, "rows_changed": 0}
        if opp.contact_email:
            crm_result = crm.add_lead(
                lead_id=f"CC-{opp.source_opportunity_id}",
                company_name=opp.title,
                contact_name=opp.contact_name or "",
                contact_email=opp.contact_email,
                source=opp.source,
                source_url=opp.source_url,
                notes=f"Score={q['score']}; reasons={' | '.join(q['reasons'])}",
                dry_run=dry_run,
            )
        if crm_result.get("dedup"):
            duplicates += 1
        elif crm_result.get("ok"):
            created += 1

        # Duplicate approval check: read back existing approvals
        approval_lookup = sheets.read_last_rows("approvals", count=500)
        already_exists = False
        if approval_lookup.get("ok"):
            rows = approval_lookup.get("rows", [])
            if rows:
                header = rows[0]
                if "entity_id" in header:
                    eidx = header.index("entity_id")
                    for row in rows[1:]:
                        if len(row) > eidx and row[eidx] == opp.source_opportunity_id:
                            already_exists = True
                            break

        if not already_exists:
            draft_obj = generate_application_draft(opp, settings)
            draft_body = draft_obj["body"]
            payload_hash = opp.payload_hash(
                action_type="apply_to_principal",
                target="CommissionCrowd",
                body=draft_body,
            )
            if dry_run:
                # In dry-run, create an in-memory approval without requiring a live Sheet.
                approval_req = gate.create_approval(
                    entity_type="opportunity",
                    entity_id=opp.source_opportunity_id,
                    entity_name=opp.title,
                    requested_action="apply_to_principal",
                    approval_action="apply_to_principal",
                    risk_level="medium" if q["score"] >= 70 else "high",
                    source_url=opp.source_url,
                    notes=(
                        f"Commission: {opp.commission_text or 'unknown'}"
                        f" | Score: {q['score']}"
                        f" | Hash: {payload_hash}"
                    ),
                    dry_run=True,
                )
            else:
                approval_req = gate.create_and_write_approval(
                    entity_type="opportunity",
                    entity_id=opp.source_opportunity_id,
                    entity_name=opp.title,
                    requested_action="apply_to_principal",
                    approval_action="apply_to_principal",
                    risk_level="medium" if q["score"] >= 70 else "high",
                    source_url=opp.source_url,
                    notes=(
                        f"Commission: {opp.commission_text or 'unknown'}"
                        f" | Score: {q['score']}"
                        f" | Hash: {payload_hash}"
                    ),
                )
            if approval_req.approval_id:
                approvals_created += 1
                  logger.info(f"Option 2: Invoking SupervisorRelay checkpoint for Opp {opp.source_opportunity_id}")
                  from commission_crowd_agent.workflows.approvals import send_approval_request
                  from commission_crowd_agent.state_registry import OpportunityStateRegistry
                  registry = OpportunityStateRegistry()
                  registry.migrate_lifecycle(opp.source_opportunity_id, "LIFECYCLE_APPLICATION_DRAFT_PENDING")
                  send_approval_request(approval_id=approval_req.approval_id, pack=approval_req)
                # Option 2 notification dispatch bridge: send Telegram approval request
                if notifier is not None:
                    import asyncio

                    pack = ApprovalPack.from_canonical(
                        opp,
                        approval_id=approval_req.approval_id,
                    )
                    pack.commission_terms = opp.commission_text or "Not stated"
                    pack.target_size = _infer_target_size(opp)
                    notify_result = asyncio.run(
                        send_approval_request(
                            pack,
                            notifier,
                            chat_id=settings.telegram_chat_id,
                            dry_run=dry_run,
                        )
                    )
                    if notify_result.get("ok"):
                        notifications_sent += 1

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
        "notifications_sent": notifications_sent,
        "sheets_written": created + updated + approvals_created,
        "emails_sent": 0,
        "calendars_created": 0,
        "checkpoint": checkpoint,
    }
