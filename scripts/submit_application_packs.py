#!/usr/bin/env python3
"""Submit drafted application packs to CommissionCrowd via supervised browser.

This script:
  1. Reads the application pack index.
  2. For each pack with an approved submission approval in Google Sheets:
     a. Logs into CommissionCrowd via Playwright.
     b. Navigates to the opportunity detail page via SPA hash.
     c. Supervises the user through the platform's application flow by
        extracting the principal's email/contact form and printing the exact
        action to take (it does NOT click Apply/Message/Connect).
  3. Records the supervised submission outcome.

State-changing platform clicks are intentionally not automated. The operator
must perform the actual Apply/Message/Connect action on the live site.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.adapters import GoogleSheetsAdapter
from commission_crowd_agent.approval_gate import ApprovalAction, ApprovalGate
from commission_crowd_agent.config import load_settings

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
PACKS_DIR = REPORTS_DIR / "cca_application_packs"
PACKS_INDEX = REPORTS_DIR / "cca_application_packs.json"
BASE_URL = "https://www.commissioncrowd.com"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Supervised CommissionCrowd application submission"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Open the browser and supervise live submission (no automated clicks)",
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


def _find_approved_submissions(
    sheets: GoogleSheetsAdapter | None,
    packs_index: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return drafted packs with any approved apply_to_principal approval."""
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
    decided_idx = header.index("decided_at_utc") if "decided_at_utc" in header else -1

    # Collect the most recent approved row per entity_id
    approved_by_entity: dict[str, dict[str, Any]] = {}
    for row in res["rows"][1:]:
        if len(row) <= max(status_idx, action_idx, entity_idx):
            continue
        row_action = row[action_idx]
        row_status = row[status_idx]
        row_entity = row[entity_idx]
        if (
            row_action in {ApprovalAction.APPLY_TO_PRINCIPAL.value, "apply_to_principal"}
            and row_entity.startswith("cca_")
            and row_status == "approved"
        ):
            entity_id = row_entity
            decided_at = row[decided_idx] if decided_idx >= 0 and len(row) > decided_idx else ""
            existing = approved_by_entity.get(entity_id)
            if existing is None or decided_at > existing["decided_at"]:
                approved_by_entity[entity_id] = {
                    "approval_id": row[id_idx],
                    "decided_at": decided_at,
                }

    approved_packs: list[dict[str, Any]] = []
    for draft in packs_index.get("drafted", []):
        lead_id = draft.get("lead_id")
        approved = approved_by_entity.get(lead_id)
        if approved:
            draft = dict(draft)
            draft["_latest_approval_id"] = approved["approval_id"]
            approved_packs.append(draft)
    return approved_packs


def _login(page: Any, settings: Any) -> None:
    page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded", timeout=30000)
    page.fill('input[type="email"]', settings.commissioncrowd_username)
    page.fill('input[type="password"]', settings.commissioncrowd_password)
    page.click('button[type="submit"]')
    for _ in range(25):
        page.wait_for_timeout(1000)
        if "#/agent" in page.url:
            break
    page.wait_for_timeout(3000)


def _navigate_opportunity(page: Any, opp_id: str) -> None:
    page.evaluate(f"window.location.hash = '#/opportunities/{opp_id}'")
    page.wait_for_timeout(7000)


def _extract_contact_options(page: Any) -> dict[str, Any]:
    """Extract visible contact/apply options from the detail page."""
    return page.evaluate(
        """() => {
            const buttons = Array.from(document.querySelectorAll('button, a, [role="button"]'));
            const options = [];
            for (const b of buttons) {
                const text = (b.innerText || b.textContent || '').trim().toLowerCase();
                if (text.length > 0 && text.length < 80) {
                    options.push({
                        tag: b.tagName.toLowerCase(),
                        text: b.innerText.trim(),
                        href: b.href || '',
                        visible: b.offsetParent !== null
                    });
                }
            }
            const emailLinks = Array.from(document.querySelectorAll('a[href^="mailto:"]'))
                .map(a => a.href);
            const allText = document.body.innerText || '';
            const emailRegex = new RegExp("[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}");
            const emailMatch = allText.match(emailRegex);
            return {
                options: options.slice(0, 20),
                email_links: emailLinks.slice(0, 5),
                text_email: emailMatch ? emailMatch[0] : '',
                page_title: document.title
            };
        }"""
    )


def _record_submission(
    approval_gate: ApprovalGate,
    pack: dict[str, Any],
    contact_options: dict[str, Any],
    *,
    live: bool,
) -> dict[str, Any]:
    opp_id = pack["opportunity_id"]
    lead_id = pack.get("lead_id", "")
    notes = (
        f"Supervised submission step completed for {opp_id}. "
        f"Operator must click the platform's Apply/Message/Connect action. "
        f"Contact options observed: {len(contact_options.get('options', []))}."
    )
    req = approval_gate.create_approval(
        entity_type="submission_record",
        entity_id=lead_id,
        requested_action=ApprovalAction.APPLY_TO_PRINCIPAL.value,
        entity_name=pack.get("pack_md", ""),
        approval_action=f"Confirm platform application submitted for {opp_id}",
        risk_level="medium",
        source_url=pack.get("pack_json", ""),
        notes=notes,
        dry_run=not live,
    )
    return {
        "submission_approval_id": req.approval_id,
        "status": req.status,
    }


def main() -> int:
    args = _parse_args()
    print(f"Mode: {'LIVE SUPERVISED' if args.live else 'DRY-RUN'}")

    settings = load_settings()
    if args.live and not settings.commissioncrowd_username:
        print("ERROR: CommissionCrowd credentials not configured.", file=sys.stderr)
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

    packs_index = _load_json(PACKS_INDEX)
    approved_packs = _find_approved_submissions(sheets, packs_index)
    print(f"Found {len(approved_packs)} approved pack submission(s)")

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if not args.live:
        print("Dry-run: would supervise the following submissions:")
        for pack in approved_packs:
            print(f"  - {pack['opportunity_id']} (approval {pack['_latest_approval_id']})")
        return 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        _login(page, settings)
        print(f"Logged in: {page.url}")

        for pack in approved_packs:
            opp_id = pack["opportunity_id"]
            try:
                print(f"\nSupervising submission for {opp_id}...")
                _navigate_opportunity(page, opp_id)
                contact_options = _extract_contact_options(page)
                print(f"  Page title: {contact_options.get('page_title', '')}")
                print("  Visible contact options:")
                for opt in contact_options.get("options", []):
                    if opt.get("visible"):
                        print(f"    - {opt['tag'].upper()}: {opt['text']}")
                if contact_options.get("email_links"):
                    print("  mailto links:", contact_options["email_links"])
                if contact_options.get("text_email"):
                    print(f"  Email on page: {contact_options['text_email']}")

                print(
                    "  ACTION REQUIRED: Click the platform's Apply / Message / "
                    "Connect button and paste the application body from the pack."
                )

                record = _record_submission(
                    approval_gate, pack, contact_options, live=args.live
                )

                results.append(
                    {
                        "opportunity_id": opp_id,
                        "lead_id": pack.get("lead_id"),
                        "submission_approval_id": pack.get("submission_approval_id"),
                        "recorded_approval_id": record["submission_approval_id"],
                        "status": "supervised_pending_operator_click",
                        "contact_options": contact_options,
                    }
                )
                print(f"  Recorded approval {record['submission_approval_id']}")
            except Exception as exc:
                print(f"  ERROR supervising {opp_id}: {exc}")
                errors.append(
                    {
                        "opportunity_id": opp_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        browser.close()

    summary = {
        "generated_at": _now(),
        "live_mode": args.live,
        "approved_packs": len(approved_packs),
        "supervised": len(results),
        "errors": len(errors),
    }

    report_json = REPORTS_DIR / "cca_submissions.json"
    with open(report_json, "w") as fh:
        json.dump(
            {"summary": summary, "results": results, "errors": errors},
            fh,
            indent=2,
        )
    print(f"\nSaved report: {report_json}")

    report_md = REPORTS_DIR / "cca_submissions.md"
    with open(report_md, "w") as fh:
        fh.write("# CCA Supervised CommissionCrowd Submissions\n\n")
        fh.write(f"**Generated:** {summary['generated_at']}\n")
        fh.write(f"**Live mode:** {'Yes' if args.live else 'No (dry-run)'}\n")
        fh.write(f"**Approved packs:** {summary['approved_packs']}\n")
        fh.write(f"**Supervised:** {summary['supervised']}\n")
        fh.write(f"**Errors:** {summary['errors']}\n\n")
        fh.write("| Opp ID | Lead ID | Status | Recorded Approval |\n")
        fh.write("|--------|---------|--------|-------------------|\n")
        for r in results:
            fh.write(
                f"| {r['opportunity_id']} | `{r.get('lead_id', '')}` | "
                f"{r['status']} | `{r.get('recorded_approval_id', '')}` |\n"
            )
        if errors:
            fh.write("\n## Errors\n\n")
            for e in errors:
                fh.write(f"- `{e.get('opportunity_id')}`: {e.get('error')}\n")
    print(f"Saved report: {report_md}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
