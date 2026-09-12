"""Resource budgets and platform limit configurations conforming to PLAN.md §30, §31."""

from __future__ import annotations

import contextlib
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceBudget:
    """Resource constraints for an isolated worker execution."""

    timeout_seconds: float = 300.0
    memory_mib: int = 1024
    max_pixels: int = 100_000_000
    max_input_bytes: int = 20 * 1024 * 1024 * 1024
    max_temp_bytes: int = 40 * 1024 * 1024 * 1024


def apply_child_resource_limits(budget: ResourceBudget) -> None:
    """Apply OS-level limits inside the child worker process upon spawn where safe."""
    if sys.platform != "win32":
        with contextlib.suppress(Exception):
            import resource

            # RLIMIT_DATA or RLIMIT_AS (avoid strict RLIMIT_AS on macOS as Python allocates early)
            if hasattr(resource, "RLIMIT_DATA") and sys.platform.startswith("linux"):
                limit_bytes = budget.memory_mib * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_DATA, (limit_bytes, limit_bytes))
