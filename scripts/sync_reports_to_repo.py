#!/usr/bin/env python3
"""Sync selected CCA runtime reports into the repo's reports/ and obsidian/ directories.

Only Markdown + JSON reports are copied. Secret-bearing files, logs, and
.env files are excluded.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

RUNTIME_REPORTS = Path("/home/ubuntu/hermes-control/reports")
REPO_REPORTS = Path(__file__).parent.parent / "reports"
REPO_OBSIDIAN = Path(__file__).parent.parent / "obsidian" / "reports"

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
    "cca_crm_staging.json",
    "cca_crm_staging.md",
    "cca_approval_requests.json",
    "cca_application_packs.json",
    "cca_application_packs.md",
    "cca_submissions.json",
    "cca_submissions.md",
    "cca_sheet_sync.json",
    "cca_sheet_sync.md",
]


def _is_allowed(path: Path) -> bool:
    if path.suffix not in ALLOWED_SUFFIXES:
        return False
    lower = path.name.lower()
    return not any(part in lower for part in EXCLUDED_NAME_PARTS)


def _sync_file(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    if not _is_allowed(src):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def main() -> int:
    if not RUNTIME_REPORTS.exists():
        print(f"Runtime reports directory not found: {RUNTIME_REPORTS}", file=sys.stderr)
        return 1

    REPO_REPORTS.mkdir(parents=True, exist_ok=True)
    REPO_OBSIDIAN.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0

    for name in REPORT_FILES:
        src = RUNTIME_REPORTS / name
        if not _sync_file(src, REPO_REPORTS / name):
            print(f"  skip (missing/excluded): {name}")
            skipped += 1
            continue
        print(f"  copied: {name}")
        copied += 1
        # Mirror Markdown files into obsidian/ directory
        if src.suffix == ".md":
            _sync_file(src, REPO_OBSIDIAN / name)

    # Also sync the application pack Markdown files into a sub-directory
    packs_dir = RUNTIME_REPORTS / "cca_application_packs"
    repo_packs_dir = REPO_REPORTS / "cca_application_packs"
    obsidian_packs_dir = REPO_OBSIDIAN / "cca_application_packs"
    if packs_dir.exists():
        repo_packs_dir.mkdir(parents=True, exist_ok=True)
        obsidian_packs_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted(packs_dir.iterdir()):
            if _is_allowed(src):
                _sync_file(src, repo_packs_dir / src.name)
                if src.suffix == ".md":
                    _sync_file(src, obsidian_packs_dir / src.name)
                print(f"  copied: cca_application_packs/{src.name}")
                copied += 1

    print(f"\nCopied {copied} report(s), skipped {skipped}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
