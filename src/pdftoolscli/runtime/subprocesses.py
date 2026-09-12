"""Subprocess hygiene and environment sanitation conforming to PLAN.md §28."""

from __future__ import annotations

from collections.abc import Iterable


def sanitize_environment(
    env: dict[str, str],
    requested_secret_vars: Iterable[str],
) -> dict[str, str]:
    """Return a sanitized copy of the environment dictionary with secret variables stripped.

    Ensures that credentials acquired via environment variables are not leaked to
    child processes or external tool invocations.
    """
    cleaned = dict(env)
    for var_name in requested_secret_vars:
        cleaned.pop(var_name, None)

    # Strip any generic or obvious secret environment variables
    for k in list(cleaned.keys()):
        if k.upper() in ("PASSWORD", "PDF_PASSWORD", "PDFTOOLSCLI_PASSWORD"):
            cleaned.pop(k, None)

    return cleaned
