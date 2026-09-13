"""Pypdfium2 / Google PDFium backend adapter implementation.

Conforms to PLAN.md §19, §26 (PDF-002).
"""

from __future__ import annotations

import io
import math
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image

from pdftoolscli.contracts.rendering import (
    MAX_PIXELS_PER_PAGE,
    RenderResult,
    RenderSpec,
)
from pdftoolscli.contracts.text import (
    TextBox,
    TextExtractSpec,
    TextPageResult,
)
from pdftoolscli.domain.errors import (
    PageBoundsError,
    PDFEncryptedError,
    PDFInvalidError,
    ResourceLimitError,
)


class PdfiumBackend:
    """Renderer and TextExtractor implementation wrapping Google PDFium via pypdfium2."""

    def _open_doc(self, path: Path, password: str | None = None) -> pdfium.PdfDocument:
        """Open a PDF document via PDFium with typed exception translation."""
        if not path.is_file():
            raise PDFInvalidError(f"PDF file not found: {path}")

        try:
            return pdfium.PdfDocument(path, password=password or "")
        except pdfium.PdfiumError as err:
            err_msg = str(err).lower()
            if "password" in err_msg:
                if password:
                    raise PDFEncryptedError(
                        f"Invalid password for encrypted document '{path.name}'.",
                        code="E_PASSWORD_INVALID",
                        hint="Check that the password is correct.",
                    ) from err
                raise PDFEncryptedError(
                    f"Password required for encrypted document '{path.name}'.",
                    code="E_PASSWORD_REQUIRED",
                    hint=(
                        "Provide a password using --password-file, "
                        "--password-env, or --password-stdin."
                    ),
                ) from err
            raise PDFInvalidError(
                f"Failed to open PDF document with PDFium '{path.name}': {err}",
                details={"path": str(path), "error": str(err)},
            ) from err

    def render_page(
        self,
        path: Path,
        page_index: int,
        spec: RenderSpec,
        password: str | None = None,
    ) -> RenderResult:
        """Render a single page to bitmap image bytes with bounds pre-allocation checking."""
        doc = self._open_doc(path, password=password)
        try:
            total_pages = len(doc)
            if page_index < 0 or page_index >= total_pages:
                raise PageBoundsError(
                    f"Page index {page_index} out of bounds (document has {total_pages} pages).",
                    page=page_index + 1,
                    page_count=total_pages,
                )

            page = doc[page_index]
            try:
                width_pt, height_pt = page.get_size()
                scale = spec.scale if spec.scale is not None else (spec.dpi / 72.0)
                width_px = math.ceil(width_pt * scale)
                height_px = math.ceil(height_pt * scale)
                total_pixels = width_px * height_px

                if total_pixels > MAX_PIXELS_PER_PAGE:
                    err_msg = (
                        f"Requested render resolution ({spec.dpi} DPI) produces "
                        f"{width_px}x{height_px} ({total_pixels:,} pixels), exceeding "
                        f"maximum allowed {MAX_PIXELS_PER_PAGE:,} pixels per page."
                    )
                    raise ResourceLimitError(
                        err_msg,
                        hint="Reduce requested DPI or render at a lower scale.",
                    )

                fill = (0, 0, 0, 0) if spec.alpha else (*spec.bg_color, 255)
                bitmap = page.render(scale=scale, fill_color=fill)
                try:
                    pil_image: Image.Image = bitmap.to_pil()
                    fmt = spec.format.lower()
                    buf = io.BytesIO()

                    if fmt in ("jpg", "jpeg"):
                        if pil_image.mode == "RGBA":
                            rgb_im = Image.new("RGB", pil_image.size, spec.bg_color)
                            rgb_im.paste(pil_image, mask=pil_image.split()[3])
                            rgb_im.save(buf, format="JPEG", quality=90)
                        else:
                            pil_image.convert("RGB").save(buf, format="JPEG", quality=90)
                    elif fmt == "webp":
                        pil_image.save(buf, format="WEBP")
                    elif fmt == "tiff":
                        pil_image.save(buf, format="TIFF")
                    else:
                        pil_image.save(buf, format="PNG")

                    image_bytes = buf.getvalue()
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            doc.close()

        return RenderResult(
            page_index=page_index,
            page_number=page_index + 1,
            width_px=width_px,
            height_px=height_px,
            dpi=spec.dpi,
            format=spec.format.lower(),
            image_bytes=image_bytes,
        )

    def render_document(
        self,
        path: Path,
        page_indices: list[int],
        spec: RenderSpec,
        password: str | None = None,
    ) -> list[RenderResult]:
        """Render multiple pages in sequence."""
        return [self.render_page(path, idx, spec, password=password) for idx in page_indices]

    def extract_page_text(
        self,
        path: Path,
        page_index: int,
        spec: TextExtractSpec,
        password: str | None = None,
    ) -> TextPageResult:
        """Extract clean UTF-8 plain text from a page with optional bounding boxes."""
        doc = self._open_doc(path, password=password)
        try:
            total_pages = len(doc)
            if page_index < 0 or page_index >= total_pages:
                raise PageBoundsError(
                    f"Page index {page_index} out of bounds (document has {total_pages} pages).",
                    page=page_index + 1,
                    page_count=total_pages,
                )

            page = doc[page_index]
            try:
                textpage = page.get_textpage()
                try:
                    raw_text = textpage.get_text_range()
                    clean_text = raw_text.replace("\x00", "")

                    boxes: list[TextBox] = []
                    if spec.include_boxes:
                        rect_count = textpage.count_rects()
                        for i in range(rect_count):
                            rect = textpage.get_rect(i)
                            b_text = textpage.get_text_bounded(*rect)
                            boxes.append(
                                TextBox(
                                    text=b_text,
                                    x0=float(rect[0]),
                                    y0=float(rect[1]),
                                    x1=float(rect[2]),
                                    y1=float(rect[3]),
                                )
                            )

                    if spec.include_page_breaks:
                        clean_text = f"{clean_text}\x0c"

                finally:
                    textpage.close()
            finally:
                page.close()
        finally:
            doc.close()

        return TextPageResult(
            page_index=page_index,
            page_number=page_index + 1,
            text=clean_text,
            char_count=len(clean_text),
            boxes=boxes,
        )

    def extract_document_text(
        self,
        path: Path,
        page_indices: list[int],
        spec: TextExtractSpec,
        password: str | None = None,
    ) -> list[TextPageResult]:
        """Extract plain text from multiple pages."""
        return [self.extract_page_text(path, idx, spec, password=password) for idx in page_indices]
