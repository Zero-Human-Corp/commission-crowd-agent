#!/usr/bin/env python3
"""CCA Option 2 concurrent workstream orchestrator.

Spawns Workstreams A, B, C, and D as independent subprocesses, each with its
own SupervisorRelay model routing enforced via environment variables. Every
workstream uses the local Hermes gateway (never Anthropic cloud boundaries).

Workstream routing:
    A  scripts/telegram_approval_daemon.py      primary_supervisor  -> glm-5.2:cloud
    B  src/commission_crowd_agent/mvp_pipeline  draft_review        -> kimi-k2-thinking
    C  scripts/refresh_lifecycle_schema_specs.py code_review       -> qwen3-coder-next
    D  src/commission_crowd_agent/discovery.py   reasoning_fallback  -> deepseek-v3.2

All writes are dry-run; supervisor inference is live against the Hermes gateway.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / "src"
REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# The CCA codebase requires Python 3.11+ (uses datetime.UTC, enum.StrEnum, etc.).
# Prefer the project venv so third-party deps (rich, pydantic, httpx) are available.
PYTHON311 = (
    "/home/ubuntu/.venvs/commission-crowd-agent/bin/python"
    if Path("/home/ubuntu/.venvs/commission-crowd-agent/bin/python").exists()
    else (shutil.which("python3.11") or shutil.which("python3") or sys.executable)
)

# The registered environment models are served by the local Ollama endpoint.
# The relay resolves exact model names to their :cloud variants automatically.
OLLAMA_BASE_URL = "http://localhost:11434/v1"

COMMON_ENV = {
    "SUPERVISOR_MODE": "local",
    "SUPERVISOR_BASE_URL": OLLAMA_BASE_URL,
    # Keep supervisor inference live (not dry-run) so models are actually invoked.
    # Workstream code still dry-runs external writes independently.
    "CCA_SUPERVISOR_INFERENCE_DRY_RUN": "false",
}

WORKSTREAMS: dict[str, dict[str, Any]] = {
    "A": {
        "name": "telegram_approval_daemon",
        "description": "Continuous long-polling loop over Telegram callbacks",
        "model_env": {
            "SUPERVISOR_PRIMARY_MODEL": "glm-5.2:cloud",
            # glm-5.2:cloud is not currently registered; allow fallback to glm-5.1:cloud.
            "SUPERVISOR_ALLOW_FALLBACK": "true",
            "SUPERVISOR_FALLBACK_MODEL": "glm-5.1:cloud",
        },
        # Demo mode: simulates one inline-keyboard callback so the supervisor
        # checkpoint fires without requiring a real Telegram long-poll session.
        "command": [
            PYTHON311,
            "-m",
            "scripts.telegram_approval_daemon",
            "--dry-run",
            "--demo-mode",
            "--opportunity-id",
            "WS-A-1001",
            "--action",
            "approve",
        ],
        "cwd": str(PROJECT_ROOT),
        "timeout": 90,
        "report": None,
    },
    "B": {
        "name": "mvp_pipeline_controlled_write",
        "description": "Controlled-write bridge into Telegram notification dispatch",
        "model_env": {
            # NOTE: kimi-k2-thinking:cloud is retired in the local registry (410 Gone).
            # Routing through the available kimi-k2.6:cloud to keep Workstream B running.
            "SUPERVISOR_DRAFT_REVIEW_MODEL": "kimi-k2.6:cloud",
        },
        "command": [
            PYTHON311,
            "-c",
            (
                "import sys, json; "
                "sys.path.insert(0, 'src'); "
                "from commission_crowd_agent.mvp_pipeline import run_controlled_write; "
                "r = run_controlled_write(limit=3, dry_run=True, notify=True, sample=True); "
                "print(json.dumps(r, indent=2, default=str))"
            ),
        ],
        "cwd": str(PROJECT_ROOT),
        "timeout": 120,
        "report": None,
    },
    "C": {
        "name": "refresh_lifecycle_schema_specs",
        "description": "Refresh active lifecycle schema specifications",
        "model_env": {
            "SUPERVISOR_CODE_REVIEW_MODEL": "qwen3-coder-next",
        },
        "command": [
            PYTHON311,
            "-m",
            "scripts.refresh_lifecycle_schema_specs",
            "--output",
            str(REPORTS_DIR / "cca_lifecycle_schema_refresh.json"),
        ],
        "cwd": str(PROJECT_ROOT),
        "timeout": 120,
        "report": str(REPORTS_DIR / "cca_lifecycle_schema_refresh.json"),
    },
    "D": {
        "name": "discovery_recovery_and_verification",
        "description": "Multi-query discovery recovery and candidate verification",
        "model_env": {
            "SUPERVISOR_REASONING_FALLBACK_MODEL": "deepseek-v3.2",
        },
        "command": [
            PYTHON311,
            "-m",
            "commission_crowd_agent.discovery",
            "--dry-run",
            "--limit",
            "3",
            "--output",
            str(REPORTS_DIR / "cca_discovery_workstream_d.json"),
        ],
        "cwd": str(PROJECT_ROOT),
        "env_extra": {"PYTHONPATH": str(SRC_DIR)},
        "timeout": 180,
        "report": str(REPORTS_DIR / "cca_discovery_workstream_d.json"),
    },
}


def _build_env(workstream: dict[str, Any]) -> dict[str, str]:
    """Merge base environment with workstream-specific supervisor model overrides."""
    env = dict(os.environ)
    env.update(COMMON_ENV)
    env.update(workstream.get("env_extra", {}))
    env.update(workstream["model_env"])
    return env


def _run_workstream(key: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Execute one workstream subprocess and return a structured result."""
    env = _build_env(spec)
    timeout = spec["timeout"]
    start = time.time()

    proc = subprocess.Popen(
        spec["command"],
        cwd=spec["cwd"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    returncode: int | None = None

    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        stdout_lines = stdout.splitlines()
        stderr_lines = stderr.splitlines()
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        proc.send_signal(signal.SIGTERM)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        stdout_lines = stdout.splitlines()
        stderr_lines = stderr.splitlines()
        returncode = proc.returncode
        stderr_lines.append(f"[orchestrator] subprocess terminated after {timeout}s")

    elapsed = time.time() - start

    report_data: dict[str, Any] | None = None
    if spec["report"] and Path(spec["report"]).exists():
        try:
            report_data = json.loads(Path(spec["report"]).read_text(encoding="utf-8"))
        except Exception as exc:
            report_data = {"error_reading_report": str(exc)}

    # Try to parse JSON from stdout if the workstream emitted one
    parsed_stdout: dict[str, Any] | None = None
    for line in reversed(stdout_lines):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                parsed_stdout = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    return {
        "key": key,
        "name": spec["name"],
        "description": spec["description"],
        "elapsed_seconds": round(elapsed, 2),
        "returncode": returncode,
        "stdout": stdout_lines,
        "stderr": stderr_lines,
        "parsed_stdout": parsed_stdout,
        "report_path": spec["report"],
        "report_data": report_data,
        "model_env": spec["model_env"],
    }


def main() -> int:
    print("=" * 70)
    print("CCA Option 2 Concurrent Workstream Execution")
    print(f"Local model endpoint: {OLLAMA_BASE_URL}")
    print("=" * 70)

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(WORKSTREAMS)) as executor:
        futures = {
            executor.submit(_run_workstream, key, spec): key
            for key, spec in WORKSTREAMS.items()
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "key": key,
                    "error": f"Orchestrator failed to run workstream: {exc}",
                }
            results[key] = result

    # Aggregate summary
    summary = {
        "ok": all(r.get("returncode") == 0 and not r.get("error") for r in results.values()),
        "workstreams": results,
    }

    out_path = REPORTS_DIR / "cca_option2_workstream_run.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True, default=str), encoding="utf-8")

    # Human-readable summary
    print("\n" + "=" * 70)
    print("Workstream Results")
    print("=" * 70)
    for key in sorted(results):
        r = results[key]
        status = "OK" if r.get("returncode") == 0 and not r.get("error") else "FAIL"
        model = r.get("model_env", {})
        print(f"\n[{key}] {r.get('name')} — {status} ({r.get('elapsed_seconds')}s)")
        print(f"  models: {json.dumps(model, ensure_ascii=True)}")
        if r.get("parsed_stdout"):
            ok = r["parsed_stdout"].get("ok")
            print(f"  workstream ok: {ok}")
        if r.get("error"):
            print(f"  error: {r['error']}")
        if r.get("stderr"):
            for line in r["stderr"][:5]:
                print(f"  stderr: {line}")

    print(f"\nFull summary written to: {out_path}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
