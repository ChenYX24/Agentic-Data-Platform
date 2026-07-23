from __future__ import annotations

from typing import Any


def choose_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Prefer hard-gate passes by score; otherwise keep the least-bad diagnostic candidate."""
    if not candidates:
        return None
    passing = [row for row in candidates if (row.get("quality") or {}).get("hard_gate_passed")]
    if passing:
        return max(
            passing,
            key=lambda row: (float(((row.get("quality") or {}).get("ranking") or {}).get("technical_score") or 0.0), -int(row.get("attempt") or 0)),
        )
    return min(
        candidates,
        key=lambda row: (int((((row.get("quality") or {}).get("hard_gate") or {}).get("failure_count")) or 1_000_000), int(row.get("attempt") or 0)),
    )
