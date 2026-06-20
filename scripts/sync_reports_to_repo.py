#!/usr/bin/env python3
"""Sync selected CCA runtime reports into the repo's reports/ and obsidian/ directories.

Only Markdown + JSON reports are copied. Secret-bearing files, logs, and
.env files are excluded.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

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


def _sync_file(src: Path, dst: Path, dry_run: bool = False) -> bool:
    if not src.exists():
        return False
    if not _is_allowed(src):
        return False
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return True


def run_git_sync(repo_root: Path, dry_run: bool = False) -> None:
    # 1. git add reports/*
    cmd_add = "git add reports/*"
    print(f"Executing: {cmd_add} (Cwd: {repo_root})")
    if not dry_run:
        try:
            # We use shell=True to support wildcard expansion in git add
            subprocess.run(cmd_add, shell=True, cwd=repo_root, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error staging reports: {e}", file=sys.stderr)
            return

    # 2. Check if there are staged changes
    if not dry_run:
        res = subprocess.run(["git", "diff", "--quiet", "--cached"], cwd=repo_root)
        if res.returncode == 0:
            print("No changes staged to commit. Skipping git commit and push.")
            return
    else:
        print("Checking staged changes: git diff --cached --quiet (dry-run)")

    # 3. git commit -m "sync: update reports [skip ci]"
    cmd_commit = ["git", "commit", "-m", "sync: update reports [skip ci]"]
    print(f"Executing: {' '.join(cmd_commit)}")
    if not dry_run:
        try:
            subprocess.run(cmd_commit, cwd=repo_root, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error committing reports: {e}", file=sys.stderr)
            return

    # 4. git push
    cmd_push = ["git", "push"]
    print(f"Executing: {' '.join(cmd_push)}")
    if not dry_run:
        try:
            subprocess.run(cmd_push, cwd=repo_root, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error pushing reports to upstream: {e}", file=sys.stderr)
            return


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync selected CCA runtime reports into the repo.")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without modifying files or git.")
    parser.add_argument("--runtime-reports-dir", type=str, help="Override path to runtime reports directory.")
    args = parser.parse_args()

    dry_run = args.dry_run

    # Determine RUNTIME_REPORTS path
    runtime_reports = None
    if args.runtime_reports_dir:
        runtime_reports = Path(args.runtime_reports_dir)
    else:
        env_path = os.environ.get("CCA_RUNTIME_REPORTS_DIR")
        if env_path:
            runtime_reports = Path(env_path)
        else:
            candidates = [
                Path("/home/ubuntu/hermes-control/reports"),
                Path.home() / "OCI-Projects" / "hermes-control" / "reports",
            ]
            for p in candidates:
                if p.exists():
                    runtime_reports = p
                    break
            if not runtime_reports:
                runtime_reports = candidates[0]  # default fallback

    print(f"Using runtime reports directory: {runtime_reports}")
    if not runtime_reports.exists():
        print(f"Runtime reports directory not found: {runtime_reports}", file=sys.stderr)
        return 1

    repo_root = Path(__file__).parent.parent.resolve()
    repo_reports = repo_root / "reports"
    repo_obsidian = repo_root / "obsidian" / "reports"

    # Verify or map symlink for obsidian/reports -> ../reports
    obsidian_dir = repo_obsidian.parent
    symlink_target = Path("../reports")

    def _obsidian_reports_exists() -> bool:
        # Python 3.11 compatible lstat-based existence check
        try:
            repo_obsidian.lstat()
            return True
        except FileNotFoundError:
            return False

    if _obsidian_reports_exists():
        if repo_obsidian.is_symlink():
            target = repo_obsidian.readlink()
            if target != symlink_target:
                print(f"Symlink target mismatch for {repo_obsidian}: {target} != {symlink_target}. Re-linking...")
                if not dry_run:
                    repo_obsidian.unlink()
                    repo_obsidian.symlink_to(symlink_target)
            else:
                print(f"Symlink verified: {repo_obsidian} -> {target}")
        else:
            print(f"Warning: {repo_obsidian} exists but is not a symlink. Replacing with symlink...")
            if not dry_run:
                try:
                    if repo_obsidian.is_dir():
                        shutil.rmtree(repo_obsidian)
                    else:
                        repo_obsidian.unlink()
                    repo_obsidian.symlink_to(symlink_target)
                except Exception as e:
                    print(f"Failed to replace with symlink: {e}", file=sys.stderr)
    else:
        print(f"Creating symlink: {repo_obsidian} -> {symlink_target}")
        if not dry_run:
            obsidian_dir.mkdir(parents=True, exist_ok=True)
            repo_obsidian.symlink_to(symlink_target)

    if not dry_run:
        repo_reports.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0

    for name in REPORT_FILES:
        src = runtime_reports / name
        # Copy to repo reports
        if not _sync_file(src, repo_reports / name, dry_run=dry_run):
            print(f"  skip (missing/excluded): {name}")
            skipped += 1
            continue
        print(f"  copied: {name}")
        copied += 1
        # Mirror Markdown files into obsidian/ directory
        if src.suffix == ".md":
            _sync_file(src, repo_obsidian / name, dry_run=dry_run)

    # Also sync the application pack Markdown files into a sub-directory
    packs_dir = runtime_reports / "cca_application_packs"
    repo_packs_dir = repo_reports / "cca_application_packs"
    obsidian_packs_dir = repo_obsidian / "cca_application_packs"
    if packs_dir.exists():
        if not dry_run:
            repo_packs_dir.mkdir(parents=True, exist_ok=True)
            obsidian_packs_dir.mkdir(parents=True, exist_ok=True)

        for src in sorted(packs_dir.iterdir()):
            if _is_allowed(src):
                _sync_file(src, repo_packs_dir / src.name, dry_run=dry_run)
                if src.suffix == ".md":
                    _sync_file(src, obsidian_packs_dir / src.name, dry_run=dry_run)
                print(f"  copied: cca_application_packs/{src.name}")
                copied += 1

    print(f"\nCopied {copied} report(s), skipped {skipped}.")

    # Automated git handling post-run
    run_git_sync(repo_root, dry_run=dry_run)

    return 0


if __name__ == "__main__":
    sys.exit(main())
