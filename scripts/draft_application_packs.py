#!/usr/bin/env python3
"""Draft CommissionCrowd application packs for approved shortlist candidates.

This script:
  1. Reads the approvals tab and finds candidates approved for apply_to_principal.
  2. Loads candidate detail from the shortlist + detail capture reports.
  3. Generates a tailored application body, 30-day sales plan, risks,
     clarification questions, and integrity hash.
  4. Writes application packs as JSON + Markdown to the runtime reports dir.
  5. Creates new approval requests for operator review of each draft before
     any platform submission.

No live CommissionCrowd submission occurs in this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.adapters import GoogleSheetsAdapter
from commission_crowd_agent.approval_gate import ApprovalAction, ApprovalGate
from commission_crowd_agent.config import load_settings

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
SHORTLIST_PATH = REPORTS_DIR / "cca_shortlist.json"
DETAIL_PATH = REPORTS_DIR / "cca_detail_capture.json"
PACKS_DIR = REPORTS_DIR / "cca_application_packs"

OPERATOR_PROFILE: dict[str, Any] = {
    "company": "Syntaxis Labs",
    "business_unit": "Syntaxis Commission Partners",
    "experience": "10 years B2B commission-based sales",
    "buyer_type": "B2B",
    "organization_type": "Commission-only sales agency",
    "coverage": "Global — remote-first, timezone-flexible",
    "industries": [
        "B2B SaaS",
        "Artificial Intelligence",
        "Data Analytics",
        "Automation",
        "Cybersecurity",
        "Business Services",
        "Cloud Computing",
        "FinTech",
        "MarTech",
    ],
    "territories": [
        "Global",
        "North America",
        "United States",
        "Canada",
        "Africa",
        "European Union",
        "Middle East",
        "United Kingdom",
        "Asia-Pacific",
    ],
    "selling_methods": [
        "Appointment Setting",
        "Online Demos",
        "Affiliate Link",
        "Email Outreach",
        "LinkedIn Outreach",
        "Webinar / Event Lead Gen",
        "Referral Programs",
        "Channel Partner Development",
        "Social Selling",
    ],
    "preferred_features": [
        "Recurring Commission",
        "Residual Commission",
        "Clear Sales Process",
        "Training Provided",
        "Sales Materials Provided",
        "CRM Access Provided",
        "Transparent Reporting",
        "Demo Environment Provided",
    ],
    "linkedin": "https://www.linkedin.com/in/syntaxis-labs-30829b401/",
    "disclaimer": (
        "Syntaxis Labs is an independent commission-based sales representative. "
        "We are not employees of the principal."
    ),
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Draft application packs for approved shortlist candidates"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Write new application-draft approvals to Google Sheets",
    )
    return parser.parse_args()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    with open(path) as fh:
        return json.load(fh)


def _lead_id_for(candidate: dict[str, Any]) -> str:
    opp_id = candidate["opportunity_id"]
    safe_title = "".join(
        c if c.isalnum() else "_" for c in candidate["title"].split(" ")[0:4]
    ).rstrip("_")[:30]
    return f"cca_{opp_id}_{safe_title}"


def _find_approved_candidates(
    sheets: GoogleSheetsAdapter | None,
    shortlist: dict[str, Any],
    detail: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return candidates whose apply_to_principal approval is approved."""
    if sheets is None:
        return []

    res = sheets.read_last_rows("approvals", count=500)
    if not res.get("ok"):
        return []

    header = res["rows"][0]
    id_idx = header.index("approval_id")
    status_idx = header.index("status")
    entity_idx = header.index("entity_id")
    action_idx = header.index("requested_action")

    approved_rows: list[list[str]] = []
    for row in res["rows"][1:]:
        if (
            len(row) > max(status_idx, action_idx, entity_idx)
            and row[status_idx] == "approved"
            and row[action_idx] == ApprovalAction.APPLY_TO_PRINCIPAL.value
            and row[entity_idx].startswith("cca_")
        ):
            approved_rows.append(row)

    detail_lookup = {c["opportunity_id"]: c for c in detail.get("details", [])}

    approved_candidates: list[dict[str, Any]] = []
    for row in approved_rows:
        entity_id = row[entity_idx]
        for candidate in shortlist.get("top_10", []):
            expected_lead_id = _lead_id_for(candidate)
            if expected_lead_id == entity_id:
                candidate = dict(candidate)
                candidate["_lead_id"] = expected_lead_id
                candidate["_approval_id"] = row[id_idx]
                candidate["_detail"] = detail_lookup.get(candidate["opportunity_id"], {})
                approved_candidates.append(candidate)
                break
    return approved_candidates


def _build_body_text(candidate: dict[str, Any]) -> str:
    company = candidate.get("principal") or candidate.get("title", "")
    paragraphs = [
        f"Dear {company} team,",
        (
            "Syntaxis Labs is a commission-only B2B sales agency. We specialise in "
            "qualifying, engaging and closing enterprise and mid-market accounts for "
            "SaaS, AI, cybersecurity, cloud and business-services vendors. Our model is "
            "purely performance-based: we earn when we generate qualified pipeline and "
            "revenue for our principals."
        ),
        (
            f"We reviewed your CommissionCrowd listing \"{candidate.get('title', '')}\" "
            "and believe there is a strong fit. The advertised commission structure "
            f"({candidate.get('commission_text', 'not specified')}) aligns with the "
            "B2B opportunities we represent, and your territory/sector notes match "
            "our coverage."
        ),
        (
            "Our typical motion: build a qualified target-account list, run LinkedIn "
            "and email outreach, schedule discovery calls or demos, and report weekly "
            "on pipeline activity. We also bring existing channel relationships where "
            "relevant."
        ),
        (
            "We would welcome the chance to represent you. Please let us know the "
            "next step to formalise the relationship."
        ),
        "Best regards,\nSyntaxis Labs\n"
        "https://www.linkedin.com/in/syntaxis-labs-30829b401/",
    ]
    return "\n\n".join(paragraphs)


def _build_markdown_pack(
    candidate: dict[str, Any],
    body_text: str,
    payload_hash: str,
    timestamp: str,
) -> str:
    company = candidate.get("principal") or candidate.get("title", "")
    detail = candidate.get("_detail", {})
    signals = candidate.get("signals", {})
    ai_sw = bool(signals.get("ai") or signals.get("software"))
    md = f"""# Application Pack — {company}

**Opportunity ID:** {candidate['opportunity_id']} \
**Source:** {candidate.get('source_url', '')} \
**Generated:** {timestamp} \
**Lead ID:** `{candidate.get('_lead_id', '')}` \
**Parent Approval:** `{candidate.get('_approval_id', '')}`

## Operator Profile

- **Company:** {OPERATOR_PROFILE['company']}
- **Business unit:** {OPERATOR_PROFILE['business_unit']}
- **Experience:** {OPERATOR_PROFILE['experience']}
- **Coverage:** {OPERATOR_PROFILE['coverage']}
- **Industries:** {', '.join(OPERATOR_PROFILE['industries'])}
- **Territories:** {', '.join(OPERATOR_PROFILE['territories'][:6])} ...
- **Selling methods:** {', '.join(OPERATOR_PROFILE['selling_methods'][:6])} ...
- **Preferred features:** {', '.join(OPERATOR_PROFILE['preferred_features'][:4])} ...
- **LinkedIn:** {OPERATOR_PROFILE['linkedin']}
- **Disclaimer:** {OPERATOR_PROFILE['disclaimer']}

## Application Body

{body_text}

## Why This Opportunity Fits

- **Qualification score:** {candidate.get('fit_score', 0)} fit /
  {candidate.get('shortlist_score', 0)} shortlist
- **Commission:** {candidate.get('commission_text', 'N/A')}
- **Territory:** {candidate.get('territory', 'N/A')}
- **B2B signal:** {'Yes' if signals.get('b2b') else 'No'}
- **Company website found:** {'Yes' if signals.get('website_found') else 'No'}
- **AI/software signal:** {'Yes' if ai_sw else 'No'}

## Detail Capture Summary

- **Title:** {detail.get('title', 'N/A')}
- **Commission text:** {detail.get('commission_text', 'N/A')}
- **Category:** {detail.get('category', 'N/A')}
- **Active:** {'Yes' if detail.get('active') else 'No / unknown'}
- **Views:** {detail.get('view_count', 'N/A')} |
  Applications: {detail.get('application_count', 'N/A')}

## Proposed First 30-Day Motion

1. **Week 1–2:** Complete onboarding/training, review collateral,
   build target-account list (150–200 prospects).
2. **Week 3:** Launch LinkedIn + email outreach; A/B test messaging;
   aim for 15–20 first conversations.
3. **Week 4:** Schedule 5–8 discovery calls/demos; document objections;
   submit weekly pipeline report.

## Risks / Unknowns

- Claims in the listing should be verified during principal onboarding.
- Territory and exclusivity terms should be confirmed.
- Commission payment terms and reporting cadence should be clarified.

## Clarification Questions for the Principal

1. Which territories are currently open for new reps?
2. Are there vertical or account-type exclusions?
3. What sales enablement materials and demo environments are provided?
4. What is the average time from first contact to signed contract?
5. How and when are commissions tracked, reported and paid?
6. Are there minimum activity or quota requirements?
7. Can you share anonymised case studies or reference customers?

## Integrity Metadata

| Field | Value |
|-------|-------|
| Payload Hash (SHA-256) | `{payload_hash}` |
| Opportunity ID | {candidate['opportunity_id']} |
| Action Type | `apply_to_principal` |
| Timestamp | {timestamp} |

> SHA-256 computed over canonical application body text + opportunity_id +
> action_type + timestamp.
"""
    return md


def _build_json_pack(
    candidate: dict[str, Any],
    body_text: str,
    payload_hash: str,
    timestamp: str,
) -> dict[str, Any]:
    return {
        "operator_profile": OPERATOR_PROFILE,
        "opportunity": {
            "opportunity_id": candidate["opportunity_id"],
            "title": candidate.get("title", ""),
            "source_url": candidate.get("source_url", ""),
            "fit_score": candidate.get("fit_score", 0),
            "shortlist_score": candidate.get("shortlist_score", 0),
            "commission_text": candidate.get("commission_text", ""),
            "territory": candidate.get("territory", ""),
            "signals": candidate.get("signals", {}),
        },
        "detail_capture": candidate.get("_detail", {}),
        "lead_id": candidate.get("_lead_id", ""),
        "parent_approval_id": candidate.get("_approval_id", ""),
        "application_body": body_text,
        "proposed_first_30_day_motion": [
            (
                "Week 1–2: onboarding, collateral review, build target-account list "
                "(150–200 prospects)."
            ),
            (
                "Week 3: launch LinkedIn + email outreach, A/B test messaging, "
                "aim for 15–20 first conversations."
            ),
            (
                "Week 4: schedule 5–8 discovery calls/demos, document objections, "
                "submit weekly pipeline report."
            ),
        ],
        "clarification_questions": [
            "Which territories are currently open for new reps?",
            "Are there vertical or account-type exclusions?",
            "What sales enablement materials and demo environments are provided?",
            "What is the average time from first contact to signed contract?",
            "How and when are commissions tracked, reported and paid?",
            "Are there minimum activity or quota requirements?",
            "Can you share anonymised case studies or reference customers?",
        ],
        "integrity": {
            "payload_hash_sha256": payload_hash,
            "opportunity_id": candidate["opportunity_id"],
            "action_type": "apply_to_principal",
            "timestamp": timestamp,
            "hash_computation_note": (
                "SHA-256 computed over canonical application body text concatenated "
                "with action metadata (opportunity_id + action_type + timestamp)."
            ),
        },
    }


def _create_submission_approval(
    approval_gate: ApprovalGate,
    candidate: dict[str, Any],
    pack_path: Path,
    *,
    live: bool,
) -> dict[str, Any]:
    req = approval_gate.create_approval(
        entity_type="application_pack",
        entity_id=candidate.get("_lead_id", ""),
        requested_action=ApprovalAction.APPLY_TO_PRINCIPAL.value,
        entity_name=candidate.get("principal") or candidate.get("title", ""),
        approval_action=(
            f"Submit application pack for {candidate['opportunity_id']} "
            "to CommissionCrowd"
        ),
        risk_level="medium",
        source_url=candidate.get("source_url", ""),
        notes=(
            f"Application pack written to {pack_path}. "
            f"Operator reviewed parent approval {candidate.get('_approval_id')}. "
            "Approve to proceed with platform submission."
        ),
        dry_run=not live,
    )
    return {
        "approval_id": req.approval_id,
        "status": req.status,
    }


def main() -> int:
    args = _parse_args()
    print(f"Mode: {'LIVE' if args.live else 'DRY-RUN'}")

    settings = load_settings()
    if args.live and not settings.google_ready:
        print(
            "ERROR: Google Sheets not configured for live approvals.",
            file=sys.stderr,
        )
        return 1

    sheets = None
    if settings.google_ready:
        sheets = GoogleSheetsAdapter(
            spreadsheet_id=settings.google_sheets_spreadsheet_id,
            credentials_path=settings.google_application_credentials_path,
            service_account_json=settings.google_service_account_json,
        )
        health = sheets.health_check()
        if not health.get("ok"):
            err = health.get("error")
            print(f"ERROR: Sheets health check failed: {err}", file=sys.stderr)
            return 1

    approval_gate = ApprovalGate(sheets_adapter=sheets)

    shortlist = _load_json(SHORTLIST_PATH)
    detail = _load_json(DETAIL_PATH)

    approved_candidates = _find_approved_candidates(sheets, shortlist, detail)
    print(f"Found {len(approved_candidates)} approved apply_to_principal candidate(s)")

    PACKS_DIR.mkdir(parents=True, exist_ok=True)

    drafted: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for candidate in approved_candidates:
        try:
            ts = _now()
            body = _build_body_text(candidate)
            hash_input = body + candidate["opportunity_id"] + "apply_to_principal" + ts
            payload_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()

            pack_md = PACKS_DIR / f"cca_app_pack_{candidate['opportunity_id']}.md"
            pack_json = PACKS_DIR / f"cca_app_pack_{candidate['opportunity_id']}.json"

            pack_md.write_text(
                _build_markdown_pack(candidate, body, payload_hash, ts)
            )
            pack_json.write_text(
                json.dumps(_build_json_pack(candidate, body, payload_hash, ts), indent=2)
            )

            approval = _create_submission_approval(
                approval_gate, candidate, pack_md, live=args.live
            )

            drafted.append(
                {
                    "opportunity_id": candidate["opportunity_id"],
                    "lead_id": candidate.get("_lead_id"),
                    "parent_approval_id": candidate.get("_approval_id"),
                    "pack_md": str(pack_md),
                    "pack_json": str(pack_json),
                    "submission_approval_id": approval["approval_id"],
                    "submission_approval_status": approval["status"],
                    "payload_hash": payload_hash,
                }
            )
            print(
                f"  Drafted pack for {candidate['opportunity_id']} "
                f"(approval {approval['approval_id']})"
            )
        except Exception as exc:
            print(f"  ERROR drafting {candidate.get('opportunity_id')}: {exc}")
            errors.append(
                {
                    "opportunity_id": candidate.get("opportunity_id"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    summary = {
        "generated_at": _now(),
        "live_mode": args.live,
        "approved_candidates_found": len(approved_candidates),
        "packs_drafted": len(drafted),
        "errors": len(errors),
    }

    report_json = REPORTS_DIR / "cca_application_packs.json"
    with open(report_json, "w") as fh:
        json.dump(
            {"summary": summary, "drafted": drafted, "errors": errors},
            fh,
            indent=2,
        )
    print(f"\nSaved report: {report_json}")

    report_md = REPORTS_DIR / "cca_application_packs.md"
    with open(report_md, "w") as fh:
        fh.write("# CCA Application Packs — Drafted\n\n")
        fh.write(f"**Generated:** {summary['generated_at']}\n")
        fh.write(f"**Live mode:** {'Yes' if args.live else 'No (dry-run)'}\n")
        fh.write(
            f"**Approved candidates found:** {summary['approved_candidates_found']}\n"
        )
        fh.write(f"**Packs drafted:** {summary['packs_drafted']}\n")
        fh.write(f"**Errors:** {summary['errors']}\n\n")
        fh.write(
            "| Opp ID | Lead ID | Pack MD | Submission Approval | Status |\n"
        )
        fh.write(
            "|--------|---------|---------|---------------------|--------|\n"
        )
        for d in drafted:
            fh.write(
                f"| {d['opportunity_id']} | `{d.get('lead_id', '')}` | "
                f"[md]({Path(d['pack_md']).name}) | "
                f"`{d['submission_approval_id']}` | "
                f"{d['submission_approval_status']} |\n"
            )
        if errors:
            fh.write("\n## Errors\n\n")
            for e in errors:
                fh.write(f"- `{e.get('opportunity_id')}`: {e.get('error')}\n")
    print(f"Saved report: {report_md}")

    print("\nDrafting summary:")
    print(f"  Approved candidates: {summary['approved_candidates_found']}")
    print(f"  Packs drafted: {summary['packs_drafted']}")
    print(f"  Errors: {summary['errors']}")
    for d in drafted:
        print(f"  -> {d['opportunity_id']}: approval {d['submission_approval_id']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
