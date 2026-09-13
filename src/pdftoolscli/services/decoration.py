"""PDF visual stamping, watermarking, and dynamic page numbering services.

Conforms to PLAN.md §12.7 C37-C38 (CMD-013).
"""

from __future__ import annotations

import io
import math
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pikepdf
from PIL import Image as PILImage
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.domain.errors import ExitCode, FileSafetyError, PDFToolsError
from pdftoolscli.domain.geometry import parse_length
from pdftoolscli.domain.ranges import resolve_range
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace

TEMPLATE_TOKEN_REGEX = re.compile(r"\{([a-zA-Z0-9_]+)\}")
COLOR_HEX_REGEX = re.compile(r"^#([0-9a-fA-F]{6})$")

POSITION_CHOICES = (
    "center",
    "top-left",
    "top",
    "top-right",
    "left",
    "right",
    "bottom-left",
    "bottom",
    "bottom-right",
    "custom",
)


def validate_color_hex(color: str) -> str:
    """Validate that color string is in #RRGGBB format."""
    s = color.strip()
    if not COLOR_HEX_REGEX.match(s):
        raise PDFToolsError(
            f"Invalid color '{color}'. Color must be in '#RRGGBB' hex format.",
            code="E_CLI_INVALID_OPTION",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint="Specify color like '#808080' or '#000000'.",
        )
    return s


def parse_offset_pair(offset_str: str | None) -> tuple[float, float]:
    """Parse comma-separated offset string 'X,Y' into points."""
    if not offset_str:
        return (0.0, 0.0)
    parts = [p.strip() for p in offset_str.split(",")]
    if len(parts) != 2:
        raise PDFToolsError(
            f"Invalid offset format '{offset_str}'. Expected 'X,Y' (e.g. '10pt,20pt').",
            code="E_CLI_INVALID_OPTION",
            exit_code=ExitCode.USAGE_OR_SELECTION,
        )
    x = parse_length(parts[0], allow_negative=True)
    y = parse_length(parts[1], allow_negative=True)
    return (x, y)


def parse_tile_pair(tile_str: str | None) -> tuple[float, float] | None:
    """Parse comma-separated tile steps 'XSTEP,YSTEP' into points."""
    if not tile_str:
        return None
    parts = [p.strip() for p in tile_str.split(",")]
    if len(parts) != 2:
        raise PDFToolsError(
            f"Invalid tile step format '{tile_str}'. Expected 'XSTEP,YSTEP' (e.g. '100pt,100pt').",
            code="E_CLI_INVALID_OPTION",
            exit_code=ExitCode.USAGE_OR_SELECTION,
        )
    x = parse_length(parts[0], allow_negative=False)
    y = parse_length(parts[1], allow_negative=False)
    if x <= 0 or y <= 0:
        raise PDFToolsError(
            f"Tile steps must be strictly positive lengths (got {x}pt, {y}pt).",
            code="E_CLI_INVALID_OPTION",
            exit_code=ExitCode.USAGE_OR_SELECTION,
        )
    return (x, y)


def int_to_roman(val: int, uppercase: bool = True) -> str:
    """Convert integer (1..3999) to Roman numeral string."""
    if not (1 <= val <= 3999):
        raise PDFToolsError(
            f"Roman numerals only support values between 1 and 3999 (got {val}).",
            code="E_CLI_INVALID_OPTION",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint="Ensure page numbers and counts fall within 1 to 3999 when using Roman style.",
        )
    arabic_vals = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    roman_syms = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
    res = []
    rem = val
    for a_val, sym in zip(arabic_vals, roman_syms, strict=False):
        while rem >= a_val:
            res.append(sym)
            rem -= a_val
    roman_str = "".join(res)
    return roman_str if uppercase else roman_str.lower()


def validate_template_string(template: str) -> None:
    """Ensure template contains only supported variables."""
    clean = template.replace("{{", "").replace("}}", "")
    allowed = {"page", "pages", "source_page", "filename", "date"}
    for match in TEMPLATE_TOKEN_REGEX.finditer(clean):
        var = match.group(1)
        if var not in allowed:
            allowed_fmt = ", ".join(f"{{{v}}}" for v in sorted(allowed))
            raise PDFToolsError(
                f"Unknown template variable '{{{var}}}'. Allowed variables: {allowed_fmt}.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )


def render_template_string(template: str, values: dict[str, str]) -> str:
    """Substitute template variables while honoring escaped double-braces."""
    marker_l = "\x00"
    marker_r = "\x01"
    s = template.replace("{{", marker_l).replace("}}", marker_r)
    for k, v in values.items():
        s = s.replace(f"{{{k}}}", v)
    return s.replace(marker_l, "{").replace(marker_r, "}")


class DecorationService:
    """Service handling visual stamp overlay, watermarking, and dynamic page numbering."""

    def __init__(self, backend: PikepdfBackend | None = None) -> None:
        self.backend = backend or PikepdfBackend()

    def stamp(
        self,
        input_path: Path,
        output_path: Path,
        text: str | None = None,
        image_path: Path | None = None,
        pdf_path: Path | None = None,
        layer: str = "foreground",
        position: str = "center",
        offset: tuple[float, float] = (0.0, 0.0),
        opacity: float = 0.25,
        rotation: float = 0.0,
        scale: float = 1.0,
        font_path: Path | None = None,
        font_size: float = 36.0,
        color: str = "#808080",
        tile: tuple[float, float] | None = None,
        page_selection: str = "all",
        source_page: int = 1,
        password: str | None = None,
        overwrite: bool = False,
        is_custom_offset: bool = False,
    ) -> dict[str, Any]:
        """Apply text, image, or PDF watermark/stamp to selected pages."""
        out_res = output_path.resolve()
        assert_distinct_files(input_path, out_res, operation_name="stamp")

        if out_res.exists() and not overwrite:
            raise FileSafetyError(
                f"Destination file '{out_res}' already exists.",
                code="E_OUTPUT_EXISTS",
                hint="Use --overwrite to allow replacing existing files.",
            )

        sources = [s for s in (text, image_path, pdf_path) if s is not None]
        if len(sources) != 1:
            raise PDFToolsError(
                "Exactly one of --text, --image, or --pdf must be specified.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if layer not in ("foreground", "background"):
            raise PDFToolsError(
                f"Invalid layer '{layer}'. Allowed: foreground, background.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if position not in POSITION_CHOICES:
            allowed = ", ".join(POSITION_CHOICES)
            raise PDFToolsError(
                f"Invalid position '{position}'. Allowed: {allowed}.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if position == "custom" and not is_custom_offset:
            raise PDFToolsError(
                "Position 'custom' requires explicit --offset X,Y.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if not (0.0 <= opacity <= 1.0):
            raise PDFToolsError(
                f"Opacity must be between 0.0 and 1.0 (got {opacity}).",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if scale <= 0.0:
            raise PDFToolsError(
                f"Scale must be strictly positive (got {scale}).",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        valid_color = validate_color_hex(color)

        font_name = "Helvetica"
        if font_path is not None:
            if not font_path.is_file():
                raise PDFToolsError(
                    f"Font file '{font_path}' not found.",
                    code="E_IO_READ",
                    exit_code=ExitCode.IO_ERROR,
                )
            font_name = f"Font_{uuid.uuid4().hex[:8]}"
            try:
                pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
            except Exception as err:
                raise PDFToolsError(
                    f"Failed to load font file '{font_path}': {err}",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                ) from err

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            total_pages = len(pdf.pages)
            if total_pages == 0:
                raise PDFToolsError("Document has 0 pages.", code="E_FILE_CORRUPT")

            selected_indices = resolve_range(page_selection, total_pages)

            # Pre-compute stamp dimensions
            stamp_w: float = 0.0
            stamp_h: float = 0.0
            loaded_image_reader: ImageReader | None = None
            source_pdf_doc: pikepdf.Pdf | None = None
            source_form_xobj: pikepdf.Object | None = None

            if text is not None:
                try:
                    stamp_w = pdfmetrics.stringWidth(text, font_name, font_size)
                    stamp_h = font_size
                except UnicodeEncodeError as uerr:
                    raise PDFToolsError(
                        f"Font '{font_name}' cannot encode characters in stamp text: {uerr}. "
                        "Provide a compatible TTF/OTF font via --font.",
                        code="E_CLI_INVALID_OPTION",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    ) from uerr

            elif image_path is not None:
                if not image_path.is_file():
                    raise PDFToolsError(
                        f"Image file '{image_path}' not found.",
                        code="E_IO_READ",
                        exit_code=ExitCode.IO_ERROR,
                    )
                try:
                    with PILImage.open(image_path) as pil_img:
                        img_w, img_h = pil_img.size
                        stamp_w = float(img_w)
                        stamp_h = float(img_h)
                    loaded_image_reader = ImageReader(str(image_path))
                except Exception as err:
                    raise PDFToolsError(
                        f"Failed to read image file '{image_path}': {err}",
                        code="E_IO_READ",
                        exit_code=ExitCode.IO_ERROR,
                    ) from err

            elif pdf_path is not None:
                if not pdf_path.is_file():
                    raise PDFToolsError(
                        f"Watermark PDF file '{pdf_path}' not found.",
                        code="E_IO_READ",
                        exit_code=ExitCode.IO_ERROR,
                    )
                try:
                    source_pdf_doc = pikepdf.open(pdf_path)
                except Exception as err:
                    raise PDFToolsError(
                        f"Failed to open watermark PDF '{pdf_path}': {err}",
                        code="E_IO_READ",
                        exit_code=ExitCode.IO_ERROR,
                    ) from err

                if source_pdf_doc.is_encrypted:
                    raise PDFToolsError(
                        "Watermark PDF is encrypted. Provide an unencrypted PDF source.",
                        code="E_FILE_CORRUPT",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    )

                max_p = len(source_pdf_doc.pages)
                if not (1 <= source_page <= max_p):
                    raise PDFToolsError(
                        f"Source page {source_page} is out of bounds (1..{max_p}).",
                        code="E_PAGE_BOUNDS",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    )

                src_page_obj = source_pdf_doc.pages[source_page - 1]
                source_form_xobj = pdf.copy_foreign(src_page_obj.as_form_xobject())
                bbox = source_form_xobj.BBox
                stamp_w = float(bbox[2]) - float(bbox[0])
                stamp_h = float(bbox[3]) - float(bbox[1])

            # Process each selected page
            for page_num in selected_indices:
                target_page = pdf.pages[page_num - 1]

                cb = target_page.CropBox if "/CropBox" in target_page else target_page.MediaBox
                cb_w = float(cb[2]) - float(cb[0])
                cb_h = float(cb[3]) - float(cb[1])
                rot = int(target_page.get("/Rotate", 0)) % 360

                if rot in (90, 270):
                    disp_w, disp_h = cb_h, cb_w
                else:
                    disp_w, disp_h = cb_w, cb_h

                scaled_w = stamp_w * scale
                scaled_h = stamp_h * scale

                centers = self._calculate_centers(
                    disp_w=disp_w,
                    disp_h=disp_h,
                    stamp_w=scaled_w,
                    stamp_h=scaled_h,
                    position=position,
                    offset=offset,
                    tile=tile,
                )

                if pdf_path is not None and source_pdf_doc is not None:
                    src_page_for_ov = source_pdf_doc.pages[source_page - 1]
                    overlay_bytes = self._build_pdf_overlay_bytes(
                        disp_w=disp_w,
                        disp_h=disp_h,
                        source_page=src_page_for_ov,
                        centers=centers,
                        rotation_deg=rotation,
                        scale=scale,
                        opacity=opacity,
                    )
                else:
                    overlay_bytes = self._build_rl_overlay_bytes(
                        disp_w=disp_w,
                        disp_h=disp_h,
                        text=text,
                        image_reader=loaded_image_reader,
                        centers=centers,
                        rotation_deg=rotation,
                        scale=scale,
                        opacity=opacity,
                        font_name=font_name,
                        font_size=font_size,
                        color_hex=valid_color,
                        stamp_orig_w=stamp_w,
                        stamp_orig_h=stamp_h,
                    )

                with pikepdf.open(io.BytesIO(overlay_bytes)) as ov_doc:
                    if layer == "background":
                        target_page.add_underlay(ov_doc.pages[0], rect=None)
                    else:
                        target_page.add_overlay(ov_doc.pages[0], rect=None)

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="stamp-", suffix=".pdf")
                pdf.save(scratch)
                AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "input": str(input_path.resolve()),
            "output": str(out_res),
            "layer": layer,
            "position": position,
            "pages_modified": len(selected_indices),
        }

    def number(
        self,
        input_path: Path,
        output_path: Path,
        format_template: str = "{page} / {pages}",
        start: int = 1,
        style: str = "decimal",
        header: str | None = None,
        footer: str | None = None,
        position: str = "bottom",
        font_path: Path | None = None,
        font_size: float = 10.0,
        color: str = "#000000",
        page_selection: str = "all",
        date_str: str | None = None,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Apply dynamic page numbering, header, and footer to selected pages."""
        out_res = output_path.resolve()
        assert_distinct_files(input_path, out_res, operation_name="number")

        if out_res.exists() and not overwrite:
            raise FileSafetyError(
                f"Destination file '{out_res}' already exists.",
                code="E_OUTPUT_EXISTS",
                hint="Use --overwrite to allow replacing existing files.",
            )

        if style not in ("decimal", "roman", "ROMAN"):
            raise PDFToolsError(
                f"Invalid style '{style}'. Allowed: decimal, roman, ROMAN.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if style in ("roman", "ROMAN") and start < 1:
            raise PDFToolsError(
                f"Roman numeral numbering requires start >= 1 (got {start}).",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
                hint="Roman numerals cannot represent zero or negative numbers.",
            )

        if style == "decimal" and start < 0:
            raise PDFToolsError(
                f"Decimal numbering requires start >= 0 (got {start}).",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        # Preflight collision check
        if header is not None and position == "top":
            raise PDFToolsError(
                "Header and format are both configured at position 'top'. "
                "Configure distinct positions to avoid overlap.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if footer is not None and position == "bottom":
            raise PDFToolsError(
                "Footer and format are both configured at position 'bottom'. "
                "Configure distinct positions to avoid overlap.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        # Preflight date verification
        templates_to_check = [format_template]
        if header is not None:
            templates_to_check.append(header)
        if footer is not None:
            templates_to_check.append(footer)

        needs_date = any("{date}" in t for t in templates_to_check)
        if needs_date:
            if not date_str:
                raise PDFToolsError(
                    "Template variable '{date}' is referenced but --date was not provided.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                    hint="Provide an explicit date via --date YYYY-MM-DD.",
                )
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError as val_err:
                raise PDFToolsError(
                    f"Invalid date '{date_str}'. Expected format YYYY-MM-DD.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                ) from val_err

        # Validate template syntax
        for t in templates_to_check:
            validate_template_string(t)

        valid_color = validate_color_hex(color)

        font_name = "Helvetica"
        if font_path is not None:
            if not font_path.is_file():
                raise PDFToolsError(
                    f"Font file '{font_path}' not found.",
                    code="E_IO_READ",
                    exit_code=ExitCode.IO_ERROR,
                )
            font_name = f"Font_{uuid.uuid4().hex[:8]}"
            try:
                pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
            except Exception as err:
                raise PDFToolsError(
                    f"Failed to load font file '{font_path}': {err}",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                ) from err

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            total_pages = len(pdf.pages)
            if total_pages == 0:
                raise PDFToolsError("Document has 0 pages.", code="E_FILE_CORRUPT")

            selected_indices = resolve_range(page_selection, total_pages)
            selected_count = len(selected_indices)

            if style in ("roman", "ROMAN") and (start + selected_count - 1 > 3999):
                raise PDFToolsError(
                    "Roman numerals cannot exceed 3999.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )

            # Format total pages string according to style
            if style == "roman":
                total_pages_str = int_to_roman(selected_count, uppercase=False)
            elif style == "ROMAN":
                total_pages_str = int_to_roman(selected_count, uppercase=True)
            else:
                total_pages_str = str(selected_count)

            # Render overlay for each selected page
            for ordinal_idx, page_num in enumerate(selected_indices):
                target_page = pdf.pages[page_num - 1]

                cb = target_page.CropBox if "/CropBox" in target_page else target_page.MediaBox
                cb_w = float(cb[2]) - float(cb[0])
                cb_h = float(cb[3]) - float(cb[1])
                rot = int(target_page.get("/Rotate", 0)) % 360

                if rot in (90, 270):
                    disp_w, disp_h = cb_h, cb_w
                else:
                    disp_w, disp_h = cb_w, cb_h

                cur_page_num = start + ordinal_idx
                if style == "roman":
                    page_num_str = int_to_roman(cur_page_num, uppercase=False)
                elif style == "ROMAN":
                    page_num_str = int_to_roman(cur_page_num, uppercase=True)
                else:
                    page_num_str = str(cur_page_num)

                template_values = {
                    "page": page_num_str,
                    "pages": total_pages_str,
                    "source_page": str(page_num),
                    "filename": input_path.name,
                    "date": date_str or "",
                }

                # Generate ReportLab overlay
                buf = io.BytesIO()
                rl_canvas = canvas.Canvas(buf, pagesize=(disp_w, disp_h))
                rl_canvas.setFont(font_name, font_size)
                rl_canvas.setFillColor(HexColor(valid_color))

                inset = 12.0

                # Render header at top center
                if header is not None:
                    hdr_text = render_template_string(header, template_values)
                    try:
                        rl_canvas.drawCentredString(
                            disp_w / 2, disp_h - inset - font_size, hdr_text
                        )
                    except UnicodeEncodeError as uerr:
                        raise PDFToolsError(
                            f"Font '{font_name}' cannot encode header text: {uerr}.",
                            code="E_CLI_INVALID_OPTION",
                            exit_code=ExitCode.USAGE_OR_SELECTION,
                        ) from uerr

                # Render footer at bottom center
                if footer is not None:
                    ftr_text = render_template_string(footer, template_values)
                    try:
                        rl_canvas.drawCentredString(disp_w / 2, inset, ftr_text)
                    except UnicodeEncodeError as uerr:
                        raise PDFToolsError(
                            f"Font '{font_name}' cannot encode footer text: {uerr}.",
                            code="E_CLI_INVALID_OPTION",
                            exit_code=ExitCode.USAGE_OR_SELECTION,
                        ) from uerr

                # Render format template at position
                fmt_text = render_template_string(format_template, template_values)
                try:
                    self._draw_positioned_text(
                        rl_canvas=rl_canvas,
                        text=fmt_text,
                        position=position,
                        disp_w=disp_w,
                        disp_h=disp_h,
                        inset=inset,
                        font_size=font_size,
                    )
                except UnicodeEncodeError as uerr:
                    raise PDFToolsError(
                        f"Font '{font_name}' cannot encode format text: {uerr}.",
                        code="E_CLI_INVALID_OPTION",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    ) from uerr

                rl_canvas.save()
                buf.seek(0)
                with pikepdf.open(buf) as ov_pdf:
                    target_page.add_overlay(ov_pdf.pages[0], rect=None)

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="number-", suffix=".pdf")
                pdf.save(scratch)
                AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "input": str(input_path.resolve()),
            "output": str(out_res),
            "style": style,
            "start": start,
            "pages_numbered": selected_count,
        }

    def _calculate_centers(
        self,
        disp_w: float,
        disp_h: float,
        stamp_w: float,
        stamp_h: float,
        position: str,
        offset: tuple[float, float],
        tile: tuple[float, float] | None,
    ) -> list[tuple[float, float]]:
        """Calculate list of center coordinates in displayed space (origin top-left)."""
        inset = 12.0
        ox, oy = offset

        if position == "center":
            base_cx = disp_w / 2 + ox
            base_cy = disp_h / 2 + oy
        elif position == "top-left":
            base_cx = inset + ox + stamp_w / 2
            base_cy = inset + oy + stamp_h / 2
        elif position == "top":
            base_cx = disp_w / 2 + ox
            base_cy = inset + oy + stamp_h / 2
        elif position == "top-right":
            base_cx = disp_w - inset + ox - stamp_w / 2
            base_cy = inset + oy + stamp_h / 2
        elif position == "left":
            base_cx = inset + ox + stamp_w / 2
            base_cy = disp_h / 2 + oy
        elif position == "right":
            base_cx = disp_w - inset + ox - stamp_w / 2
            base_cy = disp_h / 2 + oy
        elif position == "bottom-left":
            base_cx = inset + ox + stamp_w / 2
            base_cy = disp_h - inset + oy - stamp_h / 2
        elif position == "bottom":
            base_cx = disp_w / 2 + ox
            base_cy = disp_h - inset + oy - stamp_h / 2
        elif position == "bottom-right":
            base_cx = disp_w - inset + ox - stamp_w / 2
            base_cy = disp_h - inset + oy - stamp_h / 2
        elif position == "custom":
            base_cx = ox
            base_cy = oy
        else:
            base_cx = disp_w / 2 + ox
            base_cy = disp_h / 2 + oy

        if tile is None:
            return [(base_cx, base_cy)]

        xstep, ystep = tile
        x_positions = []
        curr_x = base_cx % xstep
        while curr_x < disp_w + stamp_w:
            x_positions.append(curr_x)
            curr_x += xstep

        y_positions = []
        curr_y = base_cy % ystep
        while curr_y < disp_h + stamp_h:
            y_positions.append(curr_y)
            curr_y += ystep

        return [(x, y) for x in x_positions for y in y_positions]

    def _build_rl_overlay_bytes(
        self,
        disp_w: float,
        disp_h: float,
        text: str | None,
        image_reader: ImageReader | None,
        centers: list[tuple[float, float]],
        rotation_deg: float,
        scale: float,
        opacity: float,
        font_name: str,
        font_size: float,
        color_hex: str,
        stamp_orig_w: float,
        stamp_orig_h: float,
    ) -> bytes:
        """Create a ReportLab-generated overlay PDF byte string for text or image stamps."""
        buf = io.BytesIO()
        rl_canvas = canvas.Canvas(buf, pagesize=(disp_w, disp_h))

        for cx, cy in centers:
            rl_cx = cx
            rl_cy = disp_h - cy

            rl_canvas.saveState()
            rl_canvas.setFillAlpha(opacity)
            rl_canvas.setStrokeAlpha(opacity)

            rl_canvas.translate(rl_cx, rl_cy)
            rl_canvas.rotate(-rotation_deg)
            rl_canvas.scale(scale, scale)

            if text is not None:
                rl_canvas.setFillColor(HexColor(color_hex))
                rl_canvas.setFont(font_name, font_size)
                # Vertical center adjustment around baseline
                rl_canvas.drawCentredString(0, -font_size * 0.35, text)
            elif image_reader is not None:
                rl_canvas.drawImage(
                    image_reader,
                    -stamp_orig_w / 2,
                    -stamp_orig_h / 2,
                    width=stamp_orig_w,
                    height=stamp_orig_h,
                    mask="auto",
                )

            rl_canvas.restoreState()

        rl_canvas.save()
        return buf.getvalue()

    def _build_pdf_overlay_bytes(
        self,
        disp_w: float,
        disp_h: float,
        source_page: pikepdf.Page,
        centers: list[tuple[float, float]],
        rotation_deg: float,
        scale: float,
        opacity: float,
    ) -> bytes:
        """Create a Pikepdf-generated overlay PDF byte string for PDF Form XObject watermark."""
        ov_doc = pikepdf.new()
        ov_page = ov_doc.add_blank_page(page_size=(disp_w, disp_h))

        form_xobj = ov_doc.copy_foreign(source_page.as_form_xobject())
        xobj_name = ov_page.add_resource(form_xobj, pikepdf.Name.XObject)

        gs_dict = ov_doc.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name.ExtGState,
                ca=opacity,
                CA=opacity,
            )
        )
        gs_name = ov_page.add_resource(gs_dict, pikepdf.Name.ExtGState)

        bbox = form_xobj.BBox
        lx = (float(bbox[0]) + float(bbox[2])) / 2.0
        ly = (float(bbox[1]) + float(bbox[3])) / 2.0

        stream_parts = []
        alpha = math.radians(-rotation_deg)
        cos_a = math.cos(alpha)
        sin_a = math.sin(alpha)
        a = scale * cos_a
        b = scale * sin_a
        c = -scale * sin_a
        d = scale * cos_a

        for cx, cy in centers:
            rl_cx = cx
            rl_cy = disp_h - cy

            e = rl_cx - (a * lx + c * ly)
            f = rl_cy - (b * lx + d * ly)

            chunk = (
                f"q\n"
                f"{gs_name} gs\n"
                f"{a:.6f} {b:.6f} {c:.6f} {d:.6f} {e:.6f} {f:.6f} cm\n"
                f"{xobj_name} Do\n"
                f"Q\n"
            )
            stream_parts.append(chunk.encode("ascii"))

        ov_page.contents_add(b"".join(stream_parts))
        buf = io.BytesIO()
        ov_doc.save(buf)
        return buf.getvalue()

    def _draw_positioned_text(
        self,
        rl_canvas: canvas.Canvas,
        text: str,
        position: str,
        disp_w: float,
        disp_h: float,
        inset: float,
        font_size: float,
    ) -> None:
        """Render text string at designated built-in position on canvas."""
        if position == "bottom":
            rl_canvas.drawCentredString(disp_w / 2, inset, text)
        elif position == "top":
            rl_canvas.drawCentredString(disp_w / 2, disp_h - inset - font_size, text)
        elif position == "bottom-left":
            rl_canvas.drawString(inset, inset, text)
        elif position == "bottom-right":
            rl_canvas.drawRightString(disp_w - inset, inset, text)
        elif position == "top-left":
            rl_canvas.drawString(inset, disp_h - inset - font_size, text)
        elif position == "top-right":
            rl_canvas.drawRightString(disp_w - inset, disp_h - inset - font_size, text)
        elif position == "left":
            rl_canvas.drawString(inset, disp_h / 2 - font_size / 2, text)
        elif position == "right":
            rl_canvas.drawRightString(disp_w - inset, disp_h / 2 - font_size / 2, text)
        elif position == "center":
            rl_canvas.drawCentredString(disp_w / 2, disp_h / 2 - font_size / 2, text)
        else:
            rl_canvas.drawCentredString(disp_w / 2, inset, text)
