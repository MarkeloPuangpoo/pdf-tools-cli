"""Filename sanitization, template rendering, and collision detection.

Conforms to PLAN.md §14, §18, §29.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

from pdftoolscli.domain.errors import FileSafetyError

# Reserved DOS device names that must be rejected or escaped for cross-platform safety
RESERVED_DOS_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "COM2",
        "COM3",
        "COM4",
        "COM5",
        "COM6",
        "COM7",
        "COM8",
        "COM9",
        "LPT1",
        "LPT2",
        "LPT3",
        "LPT4",
        "LPT5",
        "LPT6",
        "LPT7",
        "LPT8",
        "LPT9",
    }
)

# Invalid characters across Windows/POSIX filesystems (including control characters)
INVALID_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')

# Whitelist pattern for template tokens: e.g. {stem}, {ext}, {index:04d}, {page}, etc.
TEMPLATE_TOKEN_PATTERN = re.compile(
    r"\{(?P<var>stem|ext|asset|relparent|index|page)(?::(?P<fmt>[0-9]*d))?\}"
)


def normalize_name_for_comparison(path_or_name: str | Path) -> str:
    """Normalize a path or filename using NFC normalization and casefolding for collision checks."""
    s = str(path_or_name)
    return unicodedata.normalize("NFC", s).casefold()


def validate_safe_filename(name: str) -> None:
    """Validate that a filename is safe across platforms (no traversal, reserved names, etc.).

    Raises FileSafetyError if the filename is unsafe.
    """
    if not name or not name.strip():
        raise FileSafetyError("Filename cannot be empty or whitespace.", code="E_UNSAFE_NAME")

    if name in (".", ".."):
        raise FileSafetyError(
            f"Filename '{name}' is a reserved directory name.", code="E_UNSAFE_NAME"
        )

    if "/" in name or "\\" in name:
        raise FileSafetyError(
            f"Filename '{name}' contains directory separators.", code="E_UNSAFE_NAME"
        )

    if INVALID_FILENAME_CHARS.search(name):
        raise FileSafetyError(
            f"Filename '{name}' contains forbidden control or reserved filesystem characters.",
            code="E_UNSAFE_NAME",
        )

    # Windows prohibits filenames ending with dot or space
    if name.endswith(".") or name.endswith(" "):
        raise FileSafetyError(
            f"Filename '{name}' cannot end with a dot or trailing whitespace.",
            code="E_UNSAFE_NAME",
        )

    # Check reserved DOS device names
    base_stem = name.split(".")[0].upper()
    if base_stem in RESERVED_DOS_NAMES:
        raise FileSafetyError(
            f"Filename '{name}' conflicts with reserved system device name '{base_stem}'.",
            code="E_UNSAFE_NAME",
        )


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """Sanitize a filename by removing or replacing unsafe characters."""
    if not name or not name.strip():
        return "unnamed"

    # Replace directory separators and forbidden characters
    clean = INVALID_FILENAME_CHARS.sub(replacement, name)

    # Strip leading/trailing dots and whitespace
    clean = clean.strip(". ")
    if not clean or clean in (".", ".."):
        clean = "unnamed"

    # Avoid reserved device names
    base_stem = clean.split(".")[0].upper()
    if base_stem in RESERVED_DOS_NAMES:
        clean = f"file_{clean}"

    return clean


def assert_not_nested(input_root: Path, output_dir: Path) -> None:
    """Assert that output_dir is not inside input_root and input_root is not inside output_dir.

    Conforms to PLAN.md §29: Reject any output inside input tree or input inside output tree.
    """
    in_res = input_root.resolve()
    out_res = output_dir.resolve()

    if in_res == out_res:
        raise FileSafetyError(
            f"Output directory ({out_res}) cannot be identical to input root ({in_res}).",
            code="E_NESTED_PATH",
            hint="Specify a distinct output directory outside the input tree.",
        )

    try:
        out_res.relative_to(in_res)
        raise FileSafetyError(
            f"Output directory ({out_res}) cannot be nested inside input tree ({in_res}).",
            code="E_NESTED_PATH",
            hint="Specify an output directory outside the input tree.",
        )
    except ValueError:
        pass

    try:
        in_res.relative_to(out_res)
        raise FileSafetyError(
            f"Input tree ({in_res}) cannot be nested inside output directory ({out_res}).",
            code="E_NESTED_PATH",
            hint="Specify an output directory outside the input tree.",
        )
    except ValueError:
        pass


def render_template(
    template: str,
    *,
    stem: str,
    index: int | None = None,
    page: int | None = None,
    asset: str | None = None,
    ext: str | None = None,
    relparent: str | None = None,
) -> str:
    """Render a multi-file filename template with strict token whitelisting.

    Supported tokens: {stem}, {ext}, {asset}, {relparent}, {index}, {index:04d}, {page}, {page:04d}.
    Arbitrary Python expressions or unknown tokens are rejected.
    Traversal components ('..') in the rendered path are rejected.
    """
    if not template or not template.strip():
        raise FileSafetyError("Template cannot be empty.", code="E_UNSAFE_TEMPLATE")

    # Reject template containing raw '..'
    parts = template.replace("\\", "/").split("/")
    if ".." in parts:
        raise FileSafetyError(
            f"Template '{template}' contains forbidden directory traversal component '..'.",
            code="E_UNSAFE_TEMPLATE",
        )

    clean_ext = (ext or "").lstrip(".")
    clean_relparent = (relparent or "").strip("/\\")

    context: dict[str, Any] = {
        "stem": stem,
        "ext": clean_ext,
        "asset": asset or "",
        "relparent": clean_relparent,
        "index": index if index is not None else 0,
        "page": page if page is not None else 0,
    }

    # Verify that all {tokens} match whitelist
    # First find all bracketed expressions
    all_tokens = re.findall(r"\{[^{}]*\}", template)
    for tok in all_tokens:
        if not TEMPLATE_TOKEN_PATTERN.fullmatch(tok):
            raise FileSafetyError(
                f"Template token '{tok}' is not allowed. "
                "Only {stem}, {ext}, {asset}, {relparent}, {index}, {page} "
                "(with optional :04d format) are supported.",
                code="E_UNSAFE_TEMPLATE",
            )

    def _replace_token(match: re.Match[str]) -> str:
        var = match.group("var")
        fmt = match.group("fmt")
        val = context.get(var, "")
        if fmt and isinstance(val, int):
            return format(val, fmt)
        return str(val)

    rendered = TEMPLATE_TOKEN_PATTERN.sub(_replace_token, template)

    # Normalize separators
    norm_rendered = rendered.replace("\\", "/")
    # Reject resulting ..
    if ".." in norm_rendered.split("/"):
        raise FileSafetyError(
            f"Rendered template path '{rendered}' resolved to directory traversal.",
            code="E_UNSAFE_TEMPLATE",
        )

    return norm_rendered


def default_batch_output_name(stem: str, operation: str, ext: str = ".pdf") -> str:
    """Generate default leaf artifact name conforming to PLAN.md §29: {stem}-{operation}.pdf."""
    safe_stem = sanitize_filename(stem)
    safe_op = sanitize_filename(operation)
    if not ext.startswith("."):
        ext = f".{ext}"
    return f"{safe_stem}-{safe_op}{ext}"


class CollisionTracker:
    """Track planned destination paths and detect case-insensitive collisions preflight."""

    def __init__(self) -> None:
        self._normalized_paths: dict[str, Path] = {}

    def register(self, destination: Path) -> None:
        """Register a destination path. Raises FileSafetyError on collision."""
        norm_key = normalize_name_for_comparison(destination.resolve())
        if norm_key in self._normalized_paths:
            existing = self._normalized_paths[norm_key]
            raise FileSafetyError(
                f"Destination collision detected: '{destination}' resolves to the same filesystem "
                f"location as '{existing}'.",
                code="E_FILE_COLLISION",
                hint="Use unique output paths or an output template with unique identifiers.",
            )
        self._normalized_paths[norm_key] = destination
