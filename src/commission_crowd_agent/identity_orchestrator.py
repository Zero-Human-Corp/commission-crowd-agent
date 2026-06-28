"""Identity verification orchestrator — wires discovery -> verify -> record.

Wave 3 Track A (H1). Until this module existed, the three identity functions
had zero non-test runtime callers:

- ``candidate_identity.verify_candidate_identity`` (candidate_identity.py:84)
- ``candidate_identity.flag_identity_conflict``       (candidate_identity.py:189)
- ``OpportunityStateRecord.record_identity_verification`` (state_registry.py:143)

The identity gate (``state_registry.evaluate_identity_gate``) therefore only
ever saw hand-stamped ``"OPP-1"`` inputs in tests; no real discovered
candidate ever flowed through verify -> record. This module closes that gap.

``verify_and_record_identity`` is the single hop that, given a discovered
candidate (a real ``opportunity_id`` + a live browser page), calls the three
real functions in sequence and records the result on the registry record so
``evaluate_identity_gate`` receives input that came from discovery.

Hook point: this is callable from ``mvp_pipeline.run_controlled_write``
(after discovery produces a registry record, before any CRM write that would
gate on identity) and from the ``cca verify-identity`` CLI subcommand. It is
deliberately a free function over the registry + page boundary so it can be
exercised against the real ``verify_candidate_identity`` in tests using the
``IdentityFakePage`` pattern from ``tests/test_identity_gate.py`` — the
internal candidate_identity functions are never mocked here.
"""

from __future__ import annotations

import logging
from typing import Any

from .candidate_identity import (
    IdentityVerificationResult,
    flag_identity_conflict,
    verify_candidate_identity,
)
from .state_registry import (
    OpportunityStateRegistry,
    evaluate_identity_gate,
)

logger = logging.getLogger(__name__)


def verify_and_record_identity(
    registry: OpportunityStateRegistry,
    opportunity_id: str,
    page: Any,
    *,
    expected_title_fragments: list[str] | None = None,
    expected_vendor_fragments: list[str] | None = None,
    settle_ms: int = 7000,
) -> dict[str, Any]:
    """Run the discovery->verify->record identity hop for one candidate.

    Sequence:
      1. ``verify_candidate_identity`` navigates the page to the opportunity
         detail route and returns a real ``IdentityVerificationResult``.
      2. ``flag_identity_conflict`` compares the historical registry record
         against the freshly-extracted current identity and returns a
         disposition (RECONCILED / QUARANTINED).
      3. ``record_identity_verification`` writes ``status`` + ``disposition``
         onto the registry record so ``evaluate_identity_gate`` sees input
         that came from discovery rather than a hand-stamped ID.

    Returns a structured result dict with ``ok``, ``status``, ``disposition``,
    and the post-record ``identity_gate`` decision. ``ok`` is False only when
    the opportunity is not in the registry; verification *outcomes* (MISMATCH,
    EMPTY, UNREACHABLE, QUARANTINED) are still recorded and surfaced via the
    gate — the orchestrator never swallows a verification failure.
    """
    record = registry.get_by_id(opportunity_id)
    if record is None:
        return {
            "ok": False,
            "error": f"Opportunity {opportunity_id} not found in registry",
            "status": "",
            "disposition": "",
            "identity_gate": {
                "allowed": False,
                "reason": "Opportunity not found in state registry",
                "status": "",
                "disposition": "",
            },
        }

    verification = verify_candidate_identity(
        page,
        target_id=opportunity_id,
        expected_title_fragments=expected_title_fragments,
        expected_vendor_fragments=expected_vendor_fragments,
        settle_ms=settle_ms,
    )

    # Build historical/current dicts for flag_identity_conflict from the
    # registry record (historical) and the freshly-extracted identity
    # (current). Falls back to the registry value when extraction heuristic
    # returned nothing — preserves the original identity for comparison.
    historical = {
        "opportunity_id": opportunity_id,
        "title": record.title,
        "vendor_or_principal_name": record.principal_name,
    }
    current = {
        "opportunity_id": opportunity_id,
        "title": verification.extracted_title or record.title,
        "vendor_or_principal_name": verification.extracted_vendor or record.principal_name,
    }
    conflict = flag_identity_conflict(historical, current)
    disposition = conflict["disposition"]

    # Record on the registry record — this is the call that had zero runtime
    # callers before this module. evaluate_identity_gate reads these fields.
    record.record_identity_verification(verification.status, disposition=disposition)

    gate = evaluate_identity_gate(record)
    logger.info(
        "identity_orchestrator: %s status=%s disposition=%s gate_allowed=%s",
        opportunity_id,
        verification.status,
        disposition,
        gate["allowed"],
    )
    return {
        "ok": True,
        "opportunity_id": opportunity_id,
        "status": verification.status,
        "disposition": disposition,
        "extracted_title": verification.extracted_title,
        "extracted_vendor": verification.extracted_vendor,
        "detail": verification.detail,
        "conflict": conflict,
        "identity_gate": gate,
    }


__all__ = [
    "IdentityVerificationResult",
    "verify_and_record_identity",
]
