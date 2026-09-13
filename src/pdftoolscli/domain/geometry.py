"""PDF page geometry, dimensions, margin parsing, and coordinate transformations.

Conforms to PLAN.md §12.3, §13.
"""

from __future__ import annotations

import re

from pdftoolscli.domain.errors import ExitCode, PDFToolsError

# Standard page dimensions in points (72 points per inch)
STANDARD_PAGE_SIZES: dict[str, tuple[float, float]] = {
    "a4": (595.28, 841.89),
    "letter": (612.0, 792.0),
}

LENGTH_PATTERN = re.compile(r"^\s*([+-]?[0-9]+(?:\.[0-9]+)?)\s*(pt|mm|in|inch)?\s*$", re.IGNORECASE)


def parse_length(val_str: str, allow_negative: bool = False) -> float:
    """Parse a length string with required or optional units (pt, mm, in) into points.

    Conforms to PLAN.md §12.3: Lengths require pt/mm/in; decimal dot.
    """
    m = LENGTH_PATTERN.match(val_str.strip())
    if not m:
        raise PDFToolsError(
            f"Invalid length expression '{val_str}'. "
            "Expected format like '10mm', '72pt', or '1in'.",
            code="E_CLI_INVALID_OPTION",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint="Specify length with unit: pt, mm, or in (e.g. 10mm).",
        )

    num_str, unit = m.group(1), (m.group(2) or "").lower()
    val = float(num_str)

    if not allow_negative and val < 0:
        raise PDFToolsError(
            f"Length '{val_str}' cannot be negative.",
            code="E_CLI_INVALID_OPTION",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint="Provide a non-negative dimension value.",
        )

    if unit in ("pt", ""):
        return val
    if unit == "mm":
        return val * 72.0 / 25.4
    if unit in ("in", "inch"):
        return val * 72.0

    raise PDFToolsError(
        f"Unsupported length unit '{unit}'. Supported units: pt, mm, in.",
        code="E_CLI_INVALID_OPTION",
        exit_code=ExitCode.USAGE_OR_SELECTION,
    )


def parse_page_size(size_str: str) -> tuple[float, float]:
    """Parse standard page size name (A4, Letter) or explicit 'WIDTHxHEIGHT'."""
    s = size_str.strip().lower()
    if s in STANDARD_PAGE_SIZES:
        return STANDARD_PAGE_SIZES[s]

    if "x" in s:
        parts = s.split("x")
        if len(parts) == 2:
            w = parse_length(parts[0], allow_negative=False)
            h = parse_length(parts[1], allow_negative=False)
            if w <= 0 or h <= 0:
                raise PDFToolsError(
                    f"Page dimensions must be strictly positive (got {w}x{h}).",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )
            return (w, h)

    raise PDFToolsError(
        f"Invalid page size '{size_str}'. "
        "Allowed: A4, Letter, or 'WIDTHxHEIGHT' (e.g. 210mmx297mm).",
        code="E_CLI_INVALID_OPTION",
        exit_code=ExitCode.USAGE_OR_SELECTION,
        hint="Use a standard size name like 'A4' or dimensions like '595ptx842pt'.",
    )


def parse_margins(margins_str: str) -> tuple[float, float, float, float]:
    """Parse margins string 'LEFT,TOP,RIGHT,BOTTOM' into points."""
    parts = [p.strip() for p in margins_str.split(",")]
    if len(parts) != 4:
        raise PDFToolsError(
            f"Invalid margins format '{margins_str}'. "
            "Expected 4 comma-separated values: LEFT,TOP,RIGHT,BOTTOM.",
            code="E_CLI_INVALID_OPTION",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint="Specify margins as 'LEFT,TOP,RIGHT,BOTTOM' (e.g. 10mm,10mm,10mm,10mm).",
        )

    left = parse_length(parts[0], allow_negative=False)
    top = parse_length(parts[1], allow_negative=False)
    right = parse_length(parts[2], allow_negative=False)
    bottom = parse_length(parts[3], allow_negative=False)
    return (left, top, right, bottom)


def parse_box_coordinates(coords_str: str) -> tuple[float, float, float, float]:
    """Parse raw unrotated PDF box coordinates 'LLX,LLY,URX,URY' into points."""
    parts = [p.strip() for p in coords_str.split(",")]
    if len(parts) != 4:
        raise PDFToolsError(
            f"Invalid box coordinates '{coords_str}'. "
            "Expected 4 comma-separated values: LLX,LLY,URX,URY.",
            code="E_CLI_INVALID_OPTION",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint="Specify coordinates as 'LLX,LLY,URX,URY' (e.g. 0pt,0pt,595pt,842pt).",
        )

    llx = parse_length(parts[0], allow_negative=True)
    lly = parse_length(parts[1], allow_negative=True)
    urx = parse_length(parts[2], allow_negative=True)
    ury = parse_length(parts[3], allow_negative=True)

    if llx >= urx or lly >= ury:
        raise PDFToolsError(
            f"Invalid box ordering: LLX ({llx}) must be < URX ({urx}) "
            f"and LLY ({lly}) must be < URY ({ury}).",
            code="E_CLI_INVALID_OPTION",
            exit_code=ExitCode.USAGE_OR_SELECTION,
        )

    return (llx, lly, urx, ury)


def apply_crop_margins_to_box(
    box: list[float] | tuple[float, float, float, float],
    margins: tuple[float, float, float, float],
    rotation: int = 0,
) -> tuple[float, float, float, float]:
    """Apply displayed margins to an unrotated CropBox considering rotation.

    Rotation is 0, 90, 180, or 270 degrees clockwise.
    Origin for margins is displayed top-left.
    """

    llx, lly, urx, ury = float(box[0]), float(box[1]), float(box[2]), float(box[3])
    m_left, m_top, m_right, m_bottom = margins
    norm_rot = rotation % 360

    # In displayed space:
    # rot 0: displayed top is ury, left is llx, right is urx, bottom is lly
    # rot 90: displayed top is urx, left is ury, right is lly, bottom is llx
    # rot 180: displayed top is lly, left is urx, right is llx, bottom is ury
    # rot 270: displayed top is llx, left is lly, right is ury, bottom is urx

    if norm_rot == 0:
        new_llx = llx + m_left
        new_urx = urx - m_right
        new_ury = ury - m_top
        new_lly = lly + m_bottom
    elif norm_rot == 90:
        new_ury = ury - m_left
        new_lly = lly + m_right
        new_urx = urx - m_top
        new_llx = llx + m_bottom
    elif norm_rot == 180:
        new_urx = urx - m_left
        new_llx = llx + m_right
        new_lly = lly + m_top
        new_ury = ury - m_bottom
    elif norm_rot == 270:
        new_lly = lly + m_left
        new_ury = ury - m_right
        new_llx = llx + m_top
        new_urx = urx - m_bottom
    else:
        new_llx = llx + m_left
        new_urx = urx - m_right
        new_ury = ury - m_top
        new_lly = lly + m_bottom

    if new_llx >= new_urx or new_lly >= new_ury:
        raise PDFToolsError(
            f"Crop margins {margins} exceed page dimensions ({urx - llx} x {ury - lly} pt). "
            "Resulting box would be empty or negative.",
            code="E_PAGE_BOUNDS",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint="Reduce margins to be smaller than the page dimensions.",
        )

    return (new_llx, new_lly, new_urx, new_ury)
