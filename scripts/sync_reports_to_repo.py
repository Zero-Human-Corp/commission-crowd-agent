#!/usr/bin/env python3
"""Sync selected CCA runtime reports into the repo's reports/ directory.

Only Markdown + JSON reports are copied. Secret-bearing files, logs, and
.env files are excluded.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

RUNTIME_REPORTS = Path("/home/ubuntu/hermes-control/reports")
REPO_REPORTS = Path(__file__).parent.parent / "reports"

ALLOWED_SUFFIXES = {".md", ".json"}
EXCLUDED_NAME_PARTS = {
    "secret",
    "credential",
    "token",
    "password",
    "env",
    ".env",
    "private",
    "auth",
}

REPORT_FILES = [
    "cca_net_new_candidates.json",
    "cca_net_new_candidates.md",
    "cca_qualified_candidates.json",
    "cca_qualified_candidates.md",
    "cca_detail_capture.json",
    "cca_detail_capture.md",
    "cca_web_research.json",
    "cca_web_research.md",
    "cca_shortlist.json",
    "cca_shortlist.md",
    "cca_opportunity_id_deduplication_v1.json",
    "cca_opportunity_id_deduplication_v1.md",
]


def _is_allowed(path: Path) -> bool:
    if path.suffix not in ALLOWED_SUFFIXES:
        return False
    lower = path.name.lower()
    return not any(part in lower for part in EXCLUDED_NAME_PARTS)


def main() -> int:
    if not RUNTIME_REPORTS.exists():
        print(f"Runtime reports directory not found: {RUNTIME_REPORTS}", file=sys.stderr)
        return 1

    REPO_REPORTS.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0

    for name in REPORT_FILES:
        src = RUNTIME_REPORTS / name
        if not src.exists():
            print(f"  skip (missing): {name}")
            skipped += 1
            continue
        if not _is_allowed(src):
            print(f"  skip (excluded): {name}")
            skipped += 1
            continue
        dst = REPO_REPORTS / name
        shutil.copy2(src, dst)
        print(f"  copied: {name}")
        copied += 1

    print(f"\nCopied {copied} report(s), skipped {skipped}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
