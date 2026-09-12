"""Terminal sanitization, color policy, and stream detection conforming to PLAN.md §16, §33."""

from __future__ import annotations

import os
import re
import sys
from typing import Any

# Regex to detect and strip ANSI escape sequences
_ANSI_ESCAPE_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def sanitize_terminal_text(text: str) -> str:
    """Sanitize terminal text to prevent escape injection attacks.

    Strips ANSI escapes and replaces unprintable ASCII control characters
    (except standard whitespace: newline, tab, carriage return).
    """
    # 1. Remove ANSI escape codes
    stripped = _ANSI_ESCAPE_RE.sub("", text)

    # 2. Replace other dangerous control characters (\x00-\x08, \x0b-\x0c, \x0e-\x1f, \x7f)
    cleaned_chars: list[str] = []
    for ch in stripped:
        cp = ord(ch)
        if cp in (9, 10, 13) or cp >= 32:
            cleaned_chars.append(ch)
        else:
            cleaned_chars.append(f"\\x{cp:02x}")

    return "".join(cleaned_chars)


def should_use_color(
    color_pref: str = "auto",
    stream: Any = None,
    env: dict[str, str] | None = None,
) -> bool:
    """Determine whether color output should be enabled.

    Honors NO_COLOR environment standard and terminal TTY capabilities.
    """
    if env is None:
        env = dict(os.environ)

    # NO_COLOR specification: non-empty variable disables color
    if env.get("NO_COLOR"):
        return False

    if color_pref == "never":
        return False
    if color_pref == "always":
        return True

    # auto
    target = stream or sys.stdout
    is_atty = getattr(target, "isatty", None)
    if callable(is_atty):
        try:
            return bool(is_atty())
        except ValueError:
            return False

    return False
