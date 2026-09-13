"""Image-to-PDF and PDF rasterization service conforming to PLAN.md §12.4 (CMD-010)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import img2pdf
import pikepdf
import PIL.Image
import PIL.ImageOps

from pdftoolscli.backends.pdfium_backend import PdfiumBackend
from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.contracts.rendering import RenderSpec
from pdftoolscli.domain.errors import ExitCode, FileSafetyError, PDFToolsError
from pdftoolscli.domain.geometry import parse_color, parse_page_size
from pdftoolscli.domain.ranges import resolve_range
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace


class ConversionService:
    """Service providing image-to-PDF assembly and vector-to-raster PDF flattening."""

    def __init__(
        self,
        pdfium: PdfiumBackend | None = None,
        pikepdf_backend: PikepdfBackend | None = None,
    ) -> None:
        self.pdfium = pdfium or PdfiumBackend()
        self.pikepdf = pikepdf_backend or PikepdfBackend()

    def convert_images(
        self,
        image_paths: list[Path],
        output_path: Path,
        size: str = "auto",
        dpi: int | None = None,
        fit: str = "contain",
        background: str | None = None,
        all_frames: bool = False,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Convert an ordered list of raster images into a clean PDF."""
        if not image_paths:
            raise PDFToolsError(
                "No input images provided.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        out_res = output_path.resolve()
        for img_p in image_paths:
            assert_distinct_files(img_p, out_res, operation_name="convert images")
            if not img_p.is_file():
                raise PDFToolsError(
                    f"Image file not found: '{img_p}'.",
                    code="E_IO_NOT_FOUND",
                    exit_code=ExitCode.IO_ERROR,
                )
            if img_p.stat().st_size == 0:
                raise PDFToolsError(
                    f"Image file '{img_p.name}' is empty (zero bytes).",
                    code="E_EMPTY_IMAGE",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )

        if out_res.exists() and not overwrite:
            raise FileSafetyError(
                f"Destination file '{out_res}' already exists.",
                code="E_OUTPUT_EXISTS",
                hint="Use --overwrite to allow replacing existing files.",
            )

        bg_rgb = parse_color(background) if background else None

        # Preflight each image
        items_to_convert: list[bytes | str] = []
        for img_p in image_paths:
            try:
                with PIL.Image.open(img_p) as pil_im:
                    n_frames = getattr(pil_im, "n_frames", 1)
                    if n_frames > 1 and not all_frames:
                        raise PDFToolsError(
                            f"Image '{img_p.name}' contains {n_frames} frames. "
                            "Pass --all-frames to convert all frames.",
                            code="E_IMAGE_MULTIFRAME",
                            exit_code=ExitCode.USAGE_OR_SELECTION,
                            hint="Use --all-frames to expand all animation/TIFF frames.",
                        )

                    if n_frames > 1 and all_frames:
                        for frame_idx in range(n_frames):
                            pil_im.seek(frame_idx)
                            frame = PIL.ImageOps.exif_transpose(pil_im.copy())
                            if bg_rgb and frame.mode == "RGBA":
                                comp = PIL.Image.new("RGB", frame.size, bg_rgb)
                                comp.paste(frame, mask=frame.split()[3])
                                frame = comp
                            buf = io.BytesIO()
                            frame.save(buf, format="PNG")
                            items_to_convert.append(buf.getvalue())
                    else:
                        # Single frame
                        oriented = PIL.ImageOps.exif_transpose(pil_im)
                        # If user gave background and image has alpha, composite
                        if bg_rgb and oriented.mode == "RGBA":
                            comp = PIL.Image.new("RGB", oriented.size, bg_rgb)
                            comp.paste(oriented, mask=oriented.split()[3])
                            buf = io.BytesIO()
                            comp.save(buf, format="PNG")
                            items_to_convert.append(buf.getvalue())
                        elif (
                            pil_im.format == "JPEG"
                            and oriented == pil_im
                            and not getattr(oriented, "_getexif", lambda: None)()
                        ):
                            # Direct JPEG passthrough if unchanged
                            items_to_convert.append(str(img_p.resolve()))
                        else:
                            # Save to bytes buffer
                            buf = io.BytesIO()
                            fmt = "JPEG" if oriented.mode == "RGB" else "PNG"
                            oriented.save(buf, format=fmt)
                            items_to_convert.append(buf.getvalue())
            except (OSError, PIL.UnidentifiedImageError) as err:
                raise PDFToolsError(
                    f"Failed to read image '{img_p.name}': {err}",
                    code="E_IMAGE_INVALID",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                ) from err

        # Determine layout function
        clean_size = size.strip().lower()
        if clean_size == "auto":
            if dpi is not None:
                layout_fun = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
            else:
                layout_fun = img2pdf.default_layout_fun
        else:
            w_pt, h_pt = parse_page_size(size)
            fit_mode = img2pdf.FitMode.into if fit == "contain" else img2pdf.FitMode.exact
            layout_fun = img2pdf.get_layout_fun(pagesize=(w_pt, h_pt), fit=fit_mode)

        try:
            pdf_bytes = img2pdf.convert(items_to_convert, layout_fun=layout_fun)
        except Exception as err:
            raise PDFToolsError(
                f"Failed to convert images to PDF: {err}",
                code="E_CONVERT_FAILED",
                exit_code=ExitCode.INTERNAL_ERROR,
            ) from err

        with InvocationWorkspace() as ws:
            scratch = ws.create_scratch_file(prefix="conv-", suffix=".pdf")
            scratch.write_bytes(pdf_bytes)
            AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        with pikepdf.open(out_res) as doc:
            page_count = len(doc.pages)

        return {
            "output": str(out_res),
            "page_count": page_count,
            "images_converted": len(items_to_convert),
            "size_bytes": out_res.stat().st_size,
        }

    def convert_rasterize(
        self,
        input_path: Path,
        output_path: Path,
        pages_range: str | None = None,
        dpi: int = 150,
        colorspace: str = "rgb",
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Rasterize a vector/text PDF into an image-only flattened PDF."""
        if not input_path.is_file():
            raise PDFToolsError(
                f"Input file not found: '{input_path}'.",
                code="E_IO_NOT_FOUND",
                exit_code=ExitCode.IO_ERROR,
            )

        out_res = output_path.resolve()
        assert_distinct_files(input_path, out_res, operation_name="convert rasterize")

        if out_res.exists() and not overwrite:
            raise FileSafetyError(
                f"Destination file '{out_res}' already exists.",
                code="E_OUTPUT_EXISTS",
                hint="Use --overwrite to allow replacing existing files.",
            )

        clean_cs = colorspace.strip().lower()
        if clean_cs not in ("rgb", "gray"):
            raise PDFToolsError(
                f"Unsupported colorspace '{colorspace}'. Allowed: rgb, gray.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        spec = RenderSpec(
            dpi=dpi,
            format="png",
            alpha=False,
            bg_color=(255, 255, 255),
            colorspace=clean_cs,
        )

        with self.pikepdf.open_document(input_path, password=password) as handle:
            total_pages = len(handle.pdf.pages)

        if pages_range:
            pages_1based = resolve_range(pages_range, total_pages, context="selection")
            selected_indices = [p - 1 for p in pages_1based]
        else:
            selected_indices = list(range(total_pages))

        new_pdf = pikepdf.Pdf.new()
        for idx in selected_indices:
            res = self.pdfium.render_page(input_path, idx, spec, password=password)
            # Create a 1-page PDF from the rendered raster image with fixed DPI matching render DPI
            fixed_layout = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
            page_pdf_bytes = img2pdf.convert(res.image_bytes, layout_fun=fixed_layout)
            with pikepdf.open(io.BytesIO(page_pdf_bytes)) as temp_pdf:
                new_pdf.pages.append(temp_pdf.pages[0])

        with InvocationWorkspace() as ws:
            scratch = ws.create_scratch_file(prefix="raster-", suffix=".pdf")
            new_pdf.save(scratch)
            AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "input": str(input_path.resolve()),
            "output": str(out_res),
            "pages_rasterized": len(selected_indices),
            "dpi": dpi,
            "colorspace": clean_cs,
            "size_bytes": out_res.stat().st_size,
        }
