#!/usr/bin/env python3
"""Automated application pack submission engine for CommissionCrowd.

This script ingests application packs that are in the ``application_approved``
state and submits them through the platform's web forms using the hardened
Playwright browser adapter (sandbox flags + domcontentloaded waits).

Safety:
- Defaults to ``--dry-run``. No browser, no sheets writes, no external calls.
- Real form submission only happens when the operator passes ``--live``;
  live mode still requires explicit approval-gate credentials and a final
  confirmation prompt unless ``--yes`` is supplied.
- Success/failure states are recorded in the local registry and mirrored to
  the Google Sheets ``submissions`` and ``opportunities`` tabs.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.adapters import GoogleSheetsAdapter
from commission_crowd_agent.browser_adapter import CommissionCrowdBrowserAdapter
from commission_crowd_agent.config import load_settings
from commission_crowd_agent.crm_pipeline import CRMPipeline
from commission_crowd_agent.domain import OpportunityStage
from commission_crowd_agent.state_registry import (
    LIFECYCLE_APPLICATION_APPROVED,
    LIFECYCLE_APPLICATION_SUBMITTED,
    OpportunityStateRegistry,
)
from commission_crowd_agent.workflows.approvals import load_registry, save_registry

REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
RUNTIME_DIR = Path("/home/ubuntu/hermes-control/runtime")
PACKS_DIR = REPORTS_DIR / "cca_application_packs"
PACKS_INDEX = REPORTS_DIR / "cca_application_packs.json"
DEFAULT_REGISTRY_PATH = RUNTIME_DIR / "cca_state_registry.json"

# Heuristics used to map operator/application data onto arbitrary web forms.
NAME_LABELS = re.compile(
    r"name|full.?name|your.?name|first.?name|last.?name|representative|agent",
    re.IGNORECASE,
)
EMAIL_LABELS = re.compile(r"email|e-mail|contact.?email", re.IGNORECASE)
COMPANY_LABELS = re.compile(r"company|organisation|organization|business|agency", re.IGNORECASE)
PHONE_LABELS = re.compile(r"phone|mobile|tel|contact.?number", re.IGNORECASE)
LINKEDIN_LABELS = re.compile(r"linkedin|profile|social", re.IGNORECASE)
WEBSITE_LABELS = re.compile(r"website|url|portfolio", re.IGNORECASE)
MESSAGE_LABELS = re.compile(
    r"message|cover.?letter|about|summary|pitch|why|experience|additional|notes",
    re.IGNORECASE,
)
SUBMIT_BUTTON_LABELS = re.compile(
    r"apply|submit|send|send message|connect|get started|apply now|submit application",
    re.IGNORECASE,
)
SUCCESS_BANNER_LABELS = re.compile(
    r"application submitted|thank you|success|message sent|we have received|"
    r"submission confirmed|your application|application complete",
    re.IGNORECASE,
)
VERIFICATION_LABELS = re.compile(
    r"captcha|recaptcha|verification|verify you|are you human|i'm not a robot",
    re.IGNORECASE,
)


@dataclass
class SubmissionJob:
    """A single application pack ready for submission."""

    opportunity_id: str
    lead_id: str
    source_url: str
    pack_md: Path
    pack_json: Path
    application_body: str
    operator_profile: dict[str, Any]
    pack_metadata: dict[str, Any]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated CommissionCrowd application submission engine"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Simulate submission without browser or external writes (default)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run a real browser session and submit forms. Requires operator approval.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt in --live mode",
    )
    parser.add_argument(
        "--registry-path",
        default=str(DEFAULT_REGISTRY_PATH),
        help="Path to the opportunity state registry JSON",
    )
    parser.add_argument(
        "--packs-dir",
        default=str(PACKS_DIR),
        help="Directory containing application pack JSON/Markdown files",
    )
    parser.add_argument(
        "--opportunity-id",
        default="",
        help="Process a single opportunity instead of all approved packs",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run browser in headless mode",
    )
    return parser.parse_args()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    with open(path) as fh:
        return json.load(fh)


def _find_approved_jobs(
    registry: OpportunityStateRegistry,
    packs_index: dict[str, Any],
    packs_dir: Path,
    opportunity_id_filter: str = "",
) -> list[SubmissionJob]:
    """Return jobs for opportunities in the application_approved state."""
    jobs: list[SubmissionJob] = []
    for record in registry.to_list():
        if record.lifecycle_state != LIFECYCLE_APPLICATION_APPROVED:
            continue
        opp_id = record.opportunity_id
        if opportunity_id_filter and opp_id != opportunity_id_filter:
            continue

        pack_json = packs_dir / f"cca_app_pack_{opp_id}.json"
        pack_md = packs_dir / f"cca_app_pack_{opp_id}.md"
        if not pack_json.exists():
            # Try the index to locate an alternate path
            for draft in packs_index.get("drafted", []):
                if draft.get("opportunity_id") == opp_id:
                    pack_json = Path(draft.get("pack_json", pack_json))
                    pack_md = Path(draft.get("pack_md", pack_md))
                    break

        if not pack_json.exists():
            continue

        pack_data = _load_json(pack_json)
        source_url = record.source_url or pack_data.get("opportunity", {}).get("source_url", "")
        application_body = pack_data.get("application_body", "")
        operator_profile = pack_data.get("operator_profile", {})

        jobs.append(
            SubmissionJob(
                opportunity_id=opp_id,
                lead_id=record.to_dict().get("record_hash", opp_id)[:16],
                source_url=source_url,
                pack_md=pack_md,
                pack_json=pack_json,
                application_body=application_body,
                operator_profile=operator_profile,
                pack_metadata=pack_data,
            )
        )
    return jobs


def _visible_label_for_field(page: Any, element: Any) -> str:
    """Best-effort visible label/placeholder text for a form field."""
    try:
        attrs = element.evaluate(
            """el => {
                const label = el.labels && el.labels[0] ? el.labels[0].innerText : '';
                const aria = el.getAttribute('aria-label') || '';
                const placeholder = el.getAttribute('placeholder') || '';
                const name = el.getAttribute('name') || '';
                const id = el.id || '';
                return { label, aria, placeholder, name, id };
            }"""
        )
        parts = [
            attrs.get("label", ""),
            attrs.get("aria", ""),
            attrs.get("placeholder", ""),
            attrs.get("name", ""),
            attrs.get("id", ""),
        ]
        return " ".join(p for p in parts if p)
    except Exception:
        return ""


def _field_score(element: Any, page: Any, *patterns: re.Pattern[str]) -> int:
    """Return the number of matching patterns found in a field's visible text."""
    text = _visible_label_for_field(page, element)
    return sum(1 for p in patterns if p.search(text))


def _fill_field(element: Any, value: str) -> bool:
    """Fill a visible, editable form field."""
    try:
        tag = element.evaluate("el => el.tagName.toLowerCase()")
        if tag == "textarea":
            element.fill(value)
            return True
        input_type = element.evaluate("el => el.type")
        if input_type in {"text", "email", "tel", "url", "search", "password"}:
            element.fill(value)
            return True
        if input_type in {"radio", "checkbox"}:
            # Only check positive booleans
            if value.lower() in {"true", "yes", "1", "on"}:
                element.check()
            return True
    except Exception:
        return False
    return False


def _detect_form_fields(page: Any) -> list[dict[str, Any]]:
    """Enumerate candidate text/textarea inputs on the current page."""
    return page.evaluate(
        """() => {
            const fields = [];
            const selectors = [
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"])',
                'textarea',
                'select'
            ];
            document.querySelectorAll(selectors.join(', ')).forEach(el => {
                const rect = el.getBoundingClientRect();
                const visible = !!(rect.width && rect.height && el.offsetParent !== null);
                if (!visible) return;
                const label = el.labels && el.labels[0] ? el.labels[0].innerText.trim() : '';
                const aria = el.getAttribute('aria-label') || '';
                const placeholder = el.getAttribute('placeholder') || '';
                const name = el.getAttribute('name') || '';
                const id = el.id || '';
                fields.push({
                    tag: el.tagName.toLowerCase(),
                    type: el.type || '',
                    name,
                    id,
                    label,
                    aria,
                    placeholder,
                    tag_name: el.tagName.toLowerCase()
                });
            });
            return fields;
        }"""
    )


def _find_submit_button(page: Any) -> Any:
    """Return the best candidate submit/apply button, or None."""
    # Prefer visible buttons whose text matches submission keywords
    selectors = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Apply")',
        'button:has-text("Submit")',
        'button:has-text("Send")',
        'button:has-text("Connect")',
        'a:has-text("Apply")',
        'a:has-text("Submit")',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                first = loc.first
                if first.is_visible():
                    return first
        except Exception:
            continue

    # Fallback: scan all buttons/links
    try:
        candidates = page.locator("button, a, [role='button']").all()
        for cand in candidates:
            try:
                text = (cand.inner_text() or "").strip()
                if SUBMIT_BUTTON_LABELS.search(text) and cand.is_visible():
                    return cand
            except Exception:
                continue
    except Exception:
        pass
    return None


def _has_success_indicator(page: Any) -> bool:
    """Return True if page content suggests the form succeeded."""
    text = ""
    with contextlib.suppress(Exception):
        text = (page.locator("body").inner_text() or "").lower()
    return bool(SUCCESS_BANNER_LABELS.search(text))


def _has_verification_challenge(page: Any) -> bool:
    """Return True if a CAPTCHA/verification challenge is detected."""
    text = ""
    html = ""
    with contextlib.suppress(Exception):
        text = (page.locator("body").inner_text() or "").lower()
        html = (page.content() or "").lower()
    return bool(VERIFICATION_LABELS.search(text) or VERIFICATION_LABELS.search(html))


def _fill_application_form(page: Any, job: SubmissionJob, settings: Any) -> dict[str, Any]:
    """Map operator profile + application body onto the web form and submit."""
    operator = job.operator_profile
    name = settings.operator_name or operator.get("company", "Syntaxis Labs Representative")
    email = settings.operator_email or "publisher@syntaxis.online"
    phone = settings.operator_phone or ""
    company = operator.get("company", "Syntaxis Labs")
    linkedin = operator.get("linkedin", "")
    website = "https://www.syntaxis.online"
    body = job.application_body or operator.get("disclaimer", "")

    field_map: dict[str, list[tuple[float, Any]]] = {
        "name": [],
        "email": [],
        "company": [],
        "phone": [],
        "linkedin": [],
        "website": [],
        "message": [],
    }

    try:
        fields = page.locator("input, textarea, select").all()
    except Exception as exc:
        return {"ok": False, "error": f"Failed to enumerate form fields: {exc}"}

    for element in fields:
        try:
            if not element.is_visible():
                continue
        except Exception:
            continue

        if _field_score(element, page, NAME_LABELS):
            field_map["name"].append((_field_score(element, page, NAME_LABELS), element))
        if _field_score(element, page, EMAIL_LABELS):
            field_map["email"].append((_field_score(element, page, EMAIL_LABELS), element))
        if _field_score(element, page, COMPANY_LABELS):
            field_map["company"].append((_field_score(element, page, COMPANY_LABELS), element))
        if _field_score(element, page, PHONE_LABELS):
            field_map["phone"].append((_field_score(element, page, PHONE_LABELS), element))
        if _field_score(element, page, LINKEDIN_LABELS):
            field_map["linkedin"].append((_field_score(element, page, LINKEDIN_LABELS), element))
        if _field_score(element, page, WEBSITE_LABELS):
            field_map["website"].append((_field_score(element, page, WEBSITE_LABELS), element))
        if _field_score(element, page, MESSAGE_LABELS):
            field_map["message"].append((_field_score(element, page, MESSAGE_LABELS), element))

    # Fallback: if no message field matched, use the largest textarea
    if not field_map["message"]:
        try:
            textareas = page.locator("textarea").all()
            if textareas:
                field_map["message"].append((1.0, textareas[0]))
        except Exception:
            pass

    fill_results: dict[str, bool] = {}
    for key, value in [
        ("name", name),
        ("email", email),
        ("company", company),
        ("phone", phone),
        ("linkedin", linkedin),
        ("website", website),
        ("message", body),
    ]:
        candidates = sorted(field_map.get(key, []), key=lambda t: t[0], reverse=True)
        filled = False
        for _, element in candidates:
            if _fill_field(element, value):
                filled = True
                break
        fill_results[key] = filled

    if not fill_results.get("message") and not fill_results.get("name"):
        return {"ok": False, "error": "Could not map application body/name onto the form"}

    if _has_verification_challenge(page):
        return {"ok": False, "error": "Verification challenge detected; submission blocked"}

    submit_btn = _find_submit_button(page)
    if submit_btn is None:
        return {"ok": False, "error": "No submit/apply button found"}

    try:
        submit_btn.click()
        # Wait for navigation or SPA update
        with contextlib.suppress(Exception):
            page.wait_for_timeout(3000)
    except Exception as exc:
        return {"ok": False, "error": f"Submit click failed: {exc}"}

    success = _has_success_indicator(page)
    verification = _has_verification_challenge(page)
    return {
        "ok": success and not verification,
        "success": success,
        "verification_detected": verification,
        "final_url": page.url,
        "fill_results": fill_results,
    }


def _submit_one_live(
    job: SubmissionJob,
    browser: CommissionCrowdBrowserAdapter,
    settings: Any,
) -> dict[str, Any]:
    """Submit a single pack through the live browser."""
    page = browser._page
    if page is None:
        return {"ok": False, "error": "Browser page not initialized"}

    url = job.source_url
    if not url.startswith("http"):
        url = f"https://www.commissioncrowd.com/app/opportunities/{job.opportunity_id}"

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception as exc:
        return {"ok": False, "error": f"Navigation failed for {url}: {exc}"}

    # If the URL points to a listing detail, look for an Apply/Connect button
    # first. Some CommissionCrowd listings require clicking into the form.
    apply_button = _find_submit_button(page)
    if apply_button is not None and "apply" in (apply_button.inner_text() or "").lower():
        try:
            apply_button.click()
            page.wait_for_timeout(2000)
        except Exception as exc:
            return {"ok": False, "error": f"Apply button click failed: {exc}"}

    return _fill_application_form(page, job, settings)


def _record_submission(
    sheets: GoogleSheetsAdapter | None,
    pipeline: CRMPipeline,
    job: SubmissionJob,
    result: dict[str, Any],
    *,
    registry: OpportunityStateRegistry,
    registry_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Write the submission outcome to registry, submissions log, and CRM."""
    opp_id = job.opportunity_id
    lead_id = job.lead_id
    submitted_at = _now()
    status = "submitted" if result.get("ok") else "failed"

    # 1. Update local registry in memory
    record = registry.get_by_id(opp_id)
    if record is not None and record.lifecycle_state == LIFECYCLE_APPLICATION_APPROVED:
        record.lifecycle_state = LIFECYCLE_APPLICATION_SUBMITTED
        record.updated_at = submitted_at
        if not dry_run:
            save_registry(registry, registry_path)

    # 2. Update CRM pipeline stage
    stage_result = pipeline.advance_stage(
        lead_id=lead_id,
        new_stage=OpportunityStage.APPLICATION_SUBMITTED.value,
        sheet_tab="leads",
        dry_run=dry_run,
    )

    # 3. Append to submissions log (or simulate)
    submission_row = [
        str(uuid.uuid4())[:16],
        submitted_at,
        opp_id,
        lead_id,
        url_to_log(job.source_url),
        status,
        str(result.get("success", False)).lower(),
        str(result.get("verification_detected", False)).lower(),
        result.get("final_url", ""),
        result.get("error", ""),
    ]
    submissions_result: dict[str, Any] | None = None
    if sheets is not None:
        submissions_result = sheets.append_row("submissions", submission_row)
    elif dry_run:
        submissions_result = {"ok": True, "dry_run": True, "rows_changed": 1}

    # 4. Update opportunities tab status if a row exists
    opportunities_result: dict[str, Any] | None = None
    if sheets is not None:
        opp_read = sheets.read_last_rows("opportunities", count=5000)
        if opp_read.get("ok"):
            rows = opp_read.get("rows", [])
            if rows:
                header = rows[0]
                if "opportunity_id" in header and "status" in header:
                    id_idx = header.index("opportunity_id")
                    status_idx = header.index("status")
                    for row in rows[1:]:
                        if len(row) > max(id_idx, status_idx) and row[id_idx] == opp_id:
                            updated = list(row)
                            while len(updated) <= status_idx:
                                updated.append("")
                            updated[status_idx] = status
                            opportunities_result = sheets.upsert_row_by_key(
                                "opportunities",
                                key_column="opportunity_id",
                                key_value=opp_id,
                                values=updated,
                            )
                            break

    return {
        "ok": result.get("ok", False),
        "status": status,
        "submitted_at_utc": submitted_at,
        "registry_updated": record is not None,
        "stage_result": stage_result,
        "submissions_log": submissions_result,
        "opportunities_update": opportunities_result,
        "error": result.get("error"),
    }


def url_to_log(url: str) -> str:
    """Return a safe, truncated URL for logging."""
    if not url:
        return ""
    return url[:250]


def _build_summary_report(
    results: list[dict[str, Any]],
    *,
    dry_run: bool,
    live: bool,
    started_at: str,
) -> dict[str, Any]:
    submitted = sum(1 for r in results if r.get("ok"))
    failed = sum(1 for r in results if not r.get("ok"))
    return {
        "generated_at": _now(),
        "started_at": started_at,
        "dry_run": dry_run,
        "live_mode": live,
        "total": len(results),
        "submitted": submitted,
        "failed": failed,
    }


def _confirm_live(jobs: list[SubmissionJob]) -> bool:
    """Interactive operator confirmation for live form submission."""
    print("\nLIVE MODE: about to submit application forms for:")
    for job in jobs:
        print(f"  - {job.opportunity_id}: {job.source_url}")
    print("This will interact with CommissionCrowd web forms using stored credentials.")
    try:
        answer = input("Type 'yes' to proceed: ").strip().lower()
    except EOFError:
        print("No stdin available; aborting live mode.", file=sys.stderr)
        return False
    return answer == "yes"


def main() -> int:
    args = _parse_args()

    # --live overrides default --dry-run
    dry_run = not args.live
    live = args.live
    print(f"Mode: {'LIVE' if live else 'DRY-RUN'}")

    settings = load_settings()

    if live and not settings.commissioncrowd_username:
        print("ERROR: CommissionCrowd credentials not configured.", file=sys.stderr)
        return 1

    if live and not args.yes:
        print("INFO: --live requires explicit confirmation. Use --yes to skip the prompt.")

    sheets: GoogleSheetsAdapter | None = None
    if settings.google_ready:
        sheets = GoogleSheetsAdapter(
            spreadsheet_id=settings.google_sheets_spreadsheet_id,
            credentials_path=settings.google_application_credentials_path,
            service_account_json=settings.google_service_account_json,
            dry_run=dry_run,
        )
        if not dry_run:
            health = sheets.health_check()
            if not health.get("ok"):
                print(f"ERROR: Sheets health check failed: {health.get('error')}", file=sys.stderr)
                return 1

    pipeline = CRMPipeline(sheets_adapter=sheets)

    registry_path = Path(args.registry_path)
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry = load_registry(registry_path)

    packs_index: dict[str, Any] = {}
    if PACKS_INDEX.exists():
        packs_index = _load_json(PACKS_INDEX)

    packs_dir = Path(args.packs_dir)
    jobs = _find_approved_jobs(registry, packs_index, packs_dir, args.opportunity_id)
    print(f"Found {len(jobs)} application_approved pack(s)")

    if not jobs:
        print("No approved application packs to submit.")
        return 0

    if live and not args.yes and not _confirm_live(jobs):
        print("Live submission cancelled by operator.")
        return 1

    browser: CommissionCrowdBrowserAdapter | None = None
    if live:
        browser = CommissionCrowdBrowserAdapter()
        browser.start(headless=args.headless)
        try:
            browser.login_or_restore_session(
                settings.commissioncrowd_username,
                settings.commissioncrowd_password,
            )
        except Exception as exc:
            print(f"ERROR: browser login failed: {exc}", file=sys.stderr)
            browser.close()
            return 1

    results: list[dict[str, Any]] = []
    started_at = _now()

    for job in jobs:
        print(f"\nProcessing {job.opportunity_id} ...")
        if dry_run:
            # Simulate a successful submission without touching the browser or site.
            result = {
                "ok": True,
                "success": True,
                "verification_detected": False,
                "final_url": job.source_url,
                "dry_run": True,
            }
        else:
            assert browser is not None, "browser must be initialized in live mode"
            result = _submit_one_live(job, browser, settings)

        record = _record_submission(
            sheets=sheets,
            pipeline=pipeline,
            job=job,
            result=result,
            registry=registry,
            registry_path=registry_path,
            dry_run=dry_run,
        )
        results.append(
            {
                "opportunity_id": job.opportunity_id,
                "lead_id": job.lead_id,
                "source_url": url_to_log(job.source_url),
                "ok": record["ok"],
                "status": record["status"],
                "submitted_at_utc": record["submitted_at_utc"],
                "error": record.get("error"),
                "dry_run": dry_run,
            }
        )
        print(f"  Result: {record['status']} (ok={record['ok']})")
        if record.get("error"):
            print(f"  Error: {record['error']}")

    if browser is not None:
        browser.close()

    summary = _build_summary_report(results, dry_run=dry_run, live=live, started_at=started_at)

    report_json = REPORTS_DIR / "cca_submissions.json"
    report_json.parent.mkdir(parents=True, exist_ok=True)
    with open(report_json, "w") as fh:
        json.dump({"summary": summary, "results": results}, fh, indent=2)
    print(f"\nSaved report: {report_json}")

    report_md = REPORTS_DIR / "cca_submissions.md"
    with open(report_md, "w") as fh:
        fh.write("# CCA Automated Application Submissions\n\n")
        fh.write(f"**Generated:** {summary['generated_at']}\n")
        fh.write(f"**Mode:** {'LIVE' if live else 'DRY-RUN'}\n")
        fh.write(f"**Total:** {summary['total']}\n")
        fh.write(f"**Submitted:** {summary['submitted']}\n")
        fh.write(f"**Failed:** {summary['failed']}\n\n")
        fh.write("| Opp ID | Lead ID | Status | Submitted At | Error |\n")
        fh.write("|--------|---------|--------|--------------|-------|\n")
        for r in results:
            err = (r.get("error") or "").replace("|", "/").replace("\n", " ")[:60]
            fh.write(
                f"| {r['opportunity_id']} | `{r['lead_id']}` | {r['status']} | "
                f"{r['submitted_at_utc']} | {err} |\n"
            )
    print(f"Saved report: {report_md}")

    return 0 if summary["failed"] == 0 or dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
