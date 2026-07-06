from __future__ import annotations

from pathlib import Path
from typing import Any

from tools.capability_planner import CapabilityPlanner as LegacyCapabilityPlanner


class CapabilityPlanner:
    """Agent-facing wrapper around the existing capability planner."""

    def __init__(self, profile_path: str | Path | None = None) -> None:
        self._planner = LegacyCapabilityPlanner(profile_path) if profile_path else LegacyCapabilityPlanner()

    def plan(self, prompt: str) -> dict[str, Any]:
        return self._planner.plan(prompt)
