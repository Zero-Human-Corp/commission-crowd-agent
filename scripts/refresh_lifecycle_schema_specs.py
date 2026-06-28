#!/usr/bin/env python3
"""CCA Workstream C — refresh active lifecycle schema specs.

Scans ``docs/`` and ``specs/`` for lifecycle-state references, builds a
consistency prompt, and routes it through the SupervisorRelay code-review
checkpoint (``qwen3-coder-next``) under Option 2.

Environment (enforced by the Option 2 orchestrator):
    SUPERVISOR_MODE=local
    SUPERVISOR_BASE_URL=http://localhost:8642/v1
    SUPERVISOR_CODE_REVIEW_MODEL=qwen3-coder-next
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from commission_crowd_agent.config import load_settings  # type: ignore[import-untyped]
from commission_crowd_agent.supervisor_relay import (  # type: ignore[import-untyped]
    SupervisorRelay,
    SupervisorTaskType,
)

DOCS_DIR = Path(__file__).parent.parent / "docs"
SPECS_DIR = Path(__file__).parent.parent / "specs"
REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Lifecycle tokens we expect to find consistently across docs/specs.
# Kept in sync with src/commission_crowd_agent/state_registry.py.
LIFECYCLE_TOKENS: tuple[str, ...] = (
    # Constant names
    "LIFECYCLE_APPLICATION_DRAFT_PENDING",
    "LIFECYCLE_APPLICATION_APPROVED",
    "LIFECYCLE_APPLICATION_SUBMITTED",
    "LIFECYCLE_APPLICATION_REJECTED",
    "LIFECYCLE_PRINCIPAL_ACCEPTED",
    "LIFECYCLE_DISCOVERED",
    "LIFECYCLE_UNDER_REVIEW",
    "LIFECYCLE_INVITED",
    "LIFECYCLE_FAVOURITED",
    "LIFECYCLE_ACTIVE",
    "LIFECYCLE_PAUSED",
    "LIFECYCLE_CLOSED",
    "LIFECYCLE_WITHDRAWN",
    "LIFECYCLE_EXPIRED",
    "LIFECYCLE_UNKNOWN",
    # String literal values
    "application_draft_pending",
    "application_approved",
    "application_submitted",
    "application_rejected",
    "principal_accepted",
    "discovered",
    "under_review",
    "invited",
    "favourited",
    "active",
    "paused",
    "closed",
    "withdrawn",
    "expired",
    "unknown",
)


def _scan_files(*, max_chars: int = 12000) -> dict[str, Any]:
    """Collect lifecycle references from markdown docs and specs."""
    findings: list[dict[str, Any]] = []
    total_files = 0
    total_matches = 0

    for base_dir in (DOCS_DIR, SPECS_DIR):
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.rglob("*.md")):
            total_files += 1
            text = path.read_text(encoding="utf-8")
            matches: list[dict[str, Any]] = []
            for token in LIFECYCLE_TOKENS:
                for m in re.finditer(re.escape(token), text):
                    matches.append(
                        {
                            "token": token,
                            "line": text[: m.start()].count("\n") + 1,
                        }
                    )
            if matches:
                total_matches += len(matches)
                findings.append(
                    {
                        "file": str(path.relative_to(path.parent.parent)),
                        "match_count": len(matches),
                        "matches": matches[:10],  # cap detail
                    }
                )

    # Compile a compact corpus for the supervisor prompt
    corpus_parts: list[str] = []
    corpus_chars = 0
    for f in findings:
        snippet = json.dumps(f, ensure_ascii=True)
        if corpus_chars + len(snippet) > max_chars:
            break
        corpus_parts.append(snippet)
        corpus_chars += len(snippet)

    return {
        "total_files": total_files,
        "files_with_matches": len(findings),
        "total_matches": total_matches,
        "corpus": "[" + ",".join(corpus_parts) + "]",
    }


def _schema_refresh_prompt(scan: dict[str, Any]) -> tuple[str, str]:
    """Return (system, user) prompts for the code-review supervisor."""
    system = (
        "You are the CCA code-review supervisor. Audit documentation and spec files "
        "for lifecycle-state schema consistency. Identify missing states, mismatched "
        "naming (LIFECYCLE_ constant vs string literal), or outdated migration guards. "
        "Return only the requested JSON."
    )
    prompt = (
        f"The CCA system is refreshing its active schema specifications.\n"
        f"Scanned {scan['total_files']} markdown files; "
        f"{scan['files_with_matches']} files referenced lifecycle tokens; "
        f"{scan['total_matches']} total matches.\n\n"
        f"Corpus of findings (JSON):\n{scan['corpus']}\n\n"
        f"Required canonical lifecycle states include:\n"
        f"- LIFECYCLE_APPLICATION_DRAFT_PENDING (gateway before operator approval)\n"
        f"- LIFECYCLE_APPLICATION_APPROVED (operator approved via Telegram inline keyboard)\n"
        f"- LIFECYCLE_APPLICATION_SUBMITTED (application sent to principal)\n"
        f"- LIFECYCLE_APPLICATION_REJECTED / LIFECYCLE_PRINCIPAL_ACCEPTED\n\n"
        f"Review the corpus. Return JSON with:\n"
        f"- approved (bool): true if the spec surface is internally consistent\n"
        f"- reason (str): concise summary of findings\n"
        f"- recommended_action (str): one of review|revise|deeper_research|ok\n"
        f"- risk_level (str): low|medium|high|unknown\n"
        f"- notes (str): any missing or mismatched lifecycle references\n"
        f"- issues (list[str]): concrete issues found, empty if none"
    )
    return system, prompt


def _post_process(resp: dict[str, Any]) -> dict[str, Any]:
    """Normalize the supervisor response into a refresh report."""
    return {
        "approved": resp.get("approved", False),
        "reason": resp.get("reason", ""),
        "recommended_action": resp.get("recommended_action", ""),
        "risk_level": resp.get("risk_level", "unknown"),
        "notes": resp.get("notes", ""),
        "issues": resp.get("issues") if isinstance(resp.get("issues"), list) else [],
        "requested_model": resp.get("requested_model"),
        "actual_model": resp.get("actual_model"),
        "fallback_reason": resp.get("fallback_reason"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh CCA lifecycle schema specs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the supervisor HTTP call and emit a canned report",
    )
    parser.add_argument(
        "--output",
        default=str(REPORTS_DIR / "cca_lifecycle_schema_refresh.json"),
        help="Path for the refresh report JSON",
    )
    args = parser.parse_args()

    settings = load_settings()
    relay = SupervisorRelay(settings=settings, dry_run=args.dry_run)

    scan = _scan_files()
    system, prompt = _schema_refresh_prompt(scan)

    # Option 2 SupervisorRelay checkpoint (Workstream C: qwen3-coder-next)
    resp = relay.route(SupervisorTaskType.CODE_REVIEW, prompt, system=system)
    report = {
        "ok": resp.approved and not resp.human_approval_required,
        "workstream": "C",
        "task": "lifecycle_schema_refresh",
        "scan_summary": {
            "total_files": scan["total_files"],
            "files_with_matches": scan["files_with_matches"],
            "total_matches": scan["total_matches"],
        },
        "supervisor": _post_process(resp.model_dump()),
    }

    out_path = Path(args.output)
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=True))
    # A schema refresh is successful if the supervisor responded and the report
    # was written, even when the supervisor flags schema issues.
    return 0


if __name__ == "__main__":
    sys.exit(main())
