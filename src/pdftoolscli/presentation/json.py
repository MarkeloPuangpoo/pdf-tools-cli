"""JSON presenter conforming to PLAN.md §16, §17 and result-v1 schema."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from pdftoolscli import __version__
from pdftoolscli.domain.errors import ErrorDetail

SCHEMA_VERSION = "1.0"


def format_json_result(
    command: str,
    status: str = "ok",
    data: dict[str, Any] | None = None,
    warnings: list[ErrorDetail] | None = None,
    errors: list[ErrorDetail] | None = None,
    elapsed_ms: int = 0,
    indent: int | None = 2,
) -> str:
    """Format an operation result into a JSON Schema v1 compliant string."""
    warnings_list = [w.to_dict() for w in (warnings or [])]
    errors_list = [e.to_dict() for e in (errors or [])]

    doc = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": __version__,
        "command": command,
        "status": status,
        "data": data,
        "warnings": warnings_list,
        "errors": errors_list,
        "metrics": {
            "elapsed_ms": max(0, int(elapsed_ms)),
        },
    }

    formatted = json.dumps(doc, indent=indent, ensure_ascii=False)
    return f"{formatted}\n"


def render_json(
    command: str,
    status: str = "ok",
    data: dict[str, Any] | None = None,
    warnings: list[ErrorDetail] | None = None,
    errors: list[ErrorDetail] | None = None,
    elapsed_ms: int = 0,
    stream: TextIO | None = None,
) -> None:
    """Render a JSON Schema v1 result envelope directly to stdout (or designated stream)."""
    target = stream or sys.stdout
    payload = format_json_result(
        command=command,
        status=status,
        data=data,
        warnings=warnings,
        errors=errors,
        elapsed_ms=elapsed_ms,
    )
    target.write(payload)
    target.flush()
