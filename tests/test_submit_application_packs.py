"""Tests for the automated application pack submission engine.

Only dry-run behaviour is exercised; live browser submissions require operator
approval and CommissionCrowd credentials.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "scripts" / "submit_application_packs.py"


class TestSubmissionEngineDryRun:
    def test_dry_run_exits_zero_with_no_approved_packs(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--dry-run"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        assert "Mode: DRY-RUN" in result.stdout
        assert "Found 0 application_approved pack(s)" in result.stdout

    def test_help_lists_required_arguments(self) -> None:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0
        assert "--dry-run" in result.stdout
        assert "--live" in result.stdout
