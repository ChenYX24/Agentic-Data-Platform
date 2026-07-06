from __future__ import annotations

from typing import Any

from harness.verification.contact_causality_verifier import verify_contact_causality


def verify_billiards(case_spec: dict[str, Any], trajectory: list[dict[str, Any]]) -> tuple[str | None, dict[str, Any] | None, list[dict[str, Any]]]:
    """Compatibility wrapper for old imports.

    New code should call verify_contact_causality. Billiards is a case family of
    generic rigid-body contact causality, not a dedicated capability.
    """

    return verify_contact_causality(case_spec, trajectory)
