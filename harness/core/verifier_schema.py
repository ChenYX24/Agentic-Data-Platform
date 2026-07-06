from __future__ import annotations

from typing import Any


VERIFIER_SCHEMA_VERSION = "harness_verifier_report_v1"


def verifier_report(
    *,
    case_id: str,
    capability_id: str,
    status: str,
    failure_type: str | None,
    first_failure: dict[str, Any] | None,
    evidence: list[dict[str, Any]],
    repair_suggestions: list[str],
    artifact_completeness: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": VERIFIER_SCHEMA_VERSION,
        "case_id": case_id,
        "capability_id": capability_id,
        "status": status,
        "failure_type": failure_type,
        "first_failure": first_failure,
        "evidence": evidence,
        "repair_suggestions": repair_suggestions,
        "artifact_completeness": artifact_completeness,
    }
