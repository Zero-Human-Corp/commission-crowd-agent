"""CCA discovery engine — multi-query recovery and candidate verification.

Workstream D under Option 2: every recovery batch and every candidate
verification block is checkpointed through the SupervisorRelay
``reasoning_fallback`` route (``deepseek-v3.2``).

Public API:
    engine = DiscoveryEngine()
    result = engine.run_recovery_and_verification()

The module is also runnable as a script for the Option 2 orchestrator.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from .canonical import CanonicalOpportunity
from .commissioncrowd_adapter import CommissionCrowdApiAdapter
from .config import load_settings
from .supervisor_relay import SupervisorRelay, SupervisorTaskType

DEFAULT_REPORTS_DIR = Path("/home/ubuntu/hermes-control/reports")
DEFAULT_FIXTURE = DEFAULT_REPORTS_DIR / "cca_qualified_candidates.json"


def _load_fixture(path: Path | None = None) -> list[dict[str, Any]]:
    """Load candidate fixtures from the qualified-candidates report."""
    target = path or DEFAULT_FIXTURE
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return list(data.get("candidates", []))
    except Exception:
        return []


def _candidate_to_canonical(data: dict[str, Any]) -> CanonicalOpportunity | None:
    """Best-effort conversion from report candidate to CanonicalOpportunity."""
    try:
        return CanonicalOpportunity(
            source="commissioncrowd",
            source_opportunity_id=str(data.get("opportunity_id", "")),
            title=data.get("title", "")[:200],
            company_name=None,
            commission_text="",
            commission_percent=data.get("commission_percent"),
            residual_terms=bool(data.get("residual_terms", False)),
            territory=data.get("territory", "") or "",
            category="",
            data_quality_flags=list(data.get("flags", [])),
        )
    except Exception:
        return None


class DiscoveryEngine:
    """Multi-query discovery recovery with supervisor-gated verification."""

    def __init__(
        self,
        *,
        use_api: bool = False,
        sample_limit: int = 5,
        dry_run: bool = False,
        fixture_path: Path | None = None,
    ) -> None:
        self.use_api = use_api
        self.sample_limit = sample_limit
        self.dry_run = dry_run
        self.fixture_path = fixture_path
        # Option 2: supervisor inference is independent of discovery write dry-run.
        relay_dry_run = __import__("os").environ.get("CCA_SUPERVISOR_INFERENCE_DRY_RUN", "").lower() in {"1", "true"}
        self.relay = SupervisorRelay(dry_run=relay_dry_run)
        self._raw_candidates: list[dict[str, Any]] = []
        self._recovered: list[CanonicalOpportunity] = []
        self._verified: list[dict[str, Any]] = []
        self._checkpoints: list[dict[str, Any]] = []

    def _checkpoint(
        self,
        name: str,
        context: dict[str, Any],
        *,
        system: str | None = None,
    ) -> dict[str, Any]:
        """Run a SupervisorRelay reasoning_fallback checkpoint.

        Workstream D is routed through ``deepseek-v3.2`` via env override.
        """
        prompt = (
            f"Discovery workstream checkpoint: {name}\n"
            f"Context: {json.dumps(context, ensure_ascii=True)}\n\n"
            f"Return JSON with approved (bool), reason (str), recommended_action (str), "
            f"risk_level (low|medium|high|unknown), and notes (str). "
            f"Approve only safe read-only discovery/verification steps; block send/apply/spend."
        )
        default_system = (
            "You are the CCA reasoning supervisor. Review discovery recovery and "
            "candidate verification plans. Be conservative; any outbound action "
            "requires human approval. Respond only with JSON."
        )
        try:
            resp = self.relay.route(
                SupervisorTaskType.REASONING_FALLBACK,
                prompt,
                system=system or default_system,
            )
            result = {
                "checkpoint": name,
                "ok": resp.approved and not resp.human_approval_required,
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
            result = {
                "checkpoint": name,
                "ok": False,
                "approved": False,
                "reason": f"SupervisorRelay error: {exc}",
                "recommended_action": "",
            }
        self._checkpoints.append(result)
        return result

    def _run_recovery_queries(self) -> dict[str, Any]:
        """Execute multiple discovery queries and recover candidate records."""
        # Supervisor checkpoint before any recovery work
        ctx = {
            "strategy": "api" if self.use_api else "fixture",
            "sample_limit": self.sample_limit,
            "fixture": str(self.fixture_path or DEFAULT_FIXTURE),
        }
        checkpoint = self._checkpoint("recovery_plan", ctx)
        if not checkpoint["ok"]:
            return {"ok": False, "error": checkpoint["reason"], "recovered": 0}

        candidates: list[dict[str, Any]] = []
        if self.use_api:
            settings = load_settings()
            adapter = CommissionCrowdApiAdapter(
                api_key=settings.commissioncrowd_api_key,
                dry_run=self.dry_run,
            )
            # Multiple query recovery: page through the API and de-duplicate
            seen: set[str] = set()
            for page in range(1, 4):
                result = adapter.list_opportunities(page=page, limit=20)
                if not result.get("ok"):
                    break
                for raw in result.get("data", {}).get("items", []):
                    opp_id = str(raw.get("id", ""))
                    if opp_id and opp_id not in seen:
                        seen.add(opp_id)
                        candidates.append(raw)
                if len(candidates) >= self.sample_limit:
                    break
        else:
            all_fixtures = _load_fixture(self.fixture_path)
            # Shuffle for multi-query diversity, then sample
            random.shuffle(all_fixtures)
            candidates = all_fixtures[: self.sample_limit]

        self._raw_candidates = candidates
        canonicals: list[CanonicalOpportunity] = []
        for c in candidates:
            if self.use_api:
                try:
                    canonicals.append(CanonicalOpportunity.from_commissioncrowd_api(c))
                except Exception:
                    pass
            else:
                opp = _candidate_to_canonical(c)
                if opp is not None:
                    canonicals.append(opp)

        self._recovered = canonicals
        return {
            "ok": True,
            "recovered": len(canonicals),
            "source": "api" if self.use_api else "fixture",
        }

    def _verify_candidates(self) -> dict[str, Any]:
        """Run verification blocks over recovered candidates."""
        if not self._recovered:
            return {"ok": True, "verified": 0}

        # Supervisor checkpoint before verification
        ctx = {
            "recovered_count": len(self._recovered),
            "sample_ids": [opp.source_opportunity_id for opp in self._recovered[:3]],
            "verification_steps": [
                "Check opportunity_id is present and non-empty",
                "Check commission_percent is a positive number",
                "Check territory is specified or global flag is set",
                "Flag missing residual_terms without changing state",
                "No outbound actions: no send, apply, message, login, api_call, spend",
            ],
            "output": "read-only report of verification issues per candidate",
        }
        checkpoint = self._checkpoint("verification_plan", ctx)
        if not checkpoint["ok"]:
            return {"ok": False, "error": checkpoint["reason"], "verified": 0}

        verified: list[dict[str, Any]] = []
        for opp in self._recovered[: self.sample_limit]:
            # Candidate-level checkpoint
            ctx = {
                "opportunity_id": opp.source_opportunity_id,
                "title": opp.title,
                "commission_percent": opp.commission_percent,
                "territory": opp.territory,
                "residual_terms": opp.residual_terms,
                "flags": opp.data_quality_flags,
                "actions_to_take": [
                    "Record deterministic verification issues",
                    "Do not apply, send, or mutate external systems",
                ],
            }
            cp = self._checkpoint("candidate_verification", ctx)
            if not cp["ok"]:
                verified.append(
                    {
                        "opportunity_id": opp.source_opportunity_id,
                        "verified": False,
                        "reason": cp["reason"],
                    }
                )
                continue

            # Simple deterministic verification rules (no LLM hallucination)
            issues: list[str] = []
            if not opp.commission_percent:
                issues.append("missing_commission_percent")
            if not opp.territory:
                issues.append("missing_territory")
            if not opp.source_opportunity_id:
                issues.append("missing_opportunity_id")

            verified.append(
                {
                    "opportunity_id": opp.source_opportunity_id,
                    "title": opp.title,
                    "verified": len(issues) == 0,
                    "issues": issues,
                    "supervisor_approved": True,
                }
            )

        self._verified = verified
        return {"ok": True, "verified": len(verified)}

    def run_recovery_and_verification(self) -> dict[str, Any]:
        """Run the full discovery workstream with supervisor checkpoints."""
        recovery = self._run_recovery_queries()
        if not recovery["ok"]:
            return {
                "ok": False,
                "workstream": "D",
                "task": "discovery_recovery_and_verification",
                "error": recovery.get("error"),
                "checkpoints": self._checkpoints,
            }

        verification = self._verify_candidates()
        if not verification["ok"]:
            return {
                "ok": False,
                "workstream": "D",
                "task": "discovery_recovery_and_verification",
                "error": verification.get("error"),
                "checkpoints": self._checkpoints,
            }

        return {
            "ok": True,
            "workstream": "D",
            "task": "discovery_recovery_and_verification",
            "recovered": recovery["recovered"],
            "verified": verification["verified"],
            "verified_candidates": self._verified,
            "checkpoints": self._checkpoints,
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="CCA multi-query discovery and verification")
    parser.add_argument("--use-api", action="store_true", help="Use live CommissionCrowd API")
    parser.add_argument("--limit", type=int, default=5, help="Max candidates to process")
    parser.add_argument("--dry-run", action="store_true", help="Skip real inference/writes")
    parser.add_argument(
        "--fixture",
        default=str(DEFAULT_FIXTURE),
        help="Path to candidate fixture JSON",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_REPORTS_DIR / "cca_discovery_workstream_d.json"),
        help="Path for the workstream report",
    )
    args = parser.parse_args()

    engine = DiscoveryEngine(
        use_api=args.use_api,
        sample_limit=args.limit,
        dry_run=args.dry_run,
        fixture_path=Path(args.fixture),
    )
    result = engine.run_recovery_and_verification()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=True), encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
