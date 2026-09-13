"""Page raster rendering service conforming to PLAN.md §12.4, §19, §26 (CMD-010)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Any

from pdftoolscli.backends.pdfium_backend import PdfiumBackend
from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.contracts.rendering import RenderSpec
from pdftoolscli.domain.errors import ExitCode, FileSafetyError, PDFToolsError
from pdftoolscli.domain.geometry import parse_color
from pdftoolscli.domain.ranges import resolve_range
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.naming import CollisionTracker, render_template
from pdftoolscli.storage.workspace import InvocationWorkspace


class RenderService:
    """Service providing PDF page rasterization to image formats."""

    def __init__(
        self,
        pdfium: PdfiumBackend | None = None,
        pikepdf_backend: PikepdfBackend | None = None,
    ) -> None:
        self.pdfium = pdfium or PdfiumBackend()
        self.pikepdf = pikepdf_backend or PikepdfBackend()

    def render(
        self,
        input_path: Path,
        output_dir: Path | None = None,
        output_file: Path | str | None = None,
        to: str = "png",
        dpi: int = 150,
        quality: int | None = None,
        background: str = "white",
        colorspace: str = "rgb",
        pages_range: str | None = None,
        template: str | None = None,
        password: str | None = None,
        overwrite: bool = False,
    ) -> list[dict[str, Any]]:
        """Render selected PDF pages to bitmap images."""
        if not input_path.is_file():
            raise PDFToolsError(
                f"Input file not found: '{input_path}'.",
                code="E_IO_NOT_FOUND",
                exit_code=ExitCode.IO_ERROR,
            )

        clean_to = to.lower()
        if clean_to == "jpg":
            clean_to = "jpeg"
        if clean_to not in ("png", "jpeg", "webp", "tiff"):
            raise PDFToolsError(
                f"Unsupported render format '{to}'. Allowed: png, jpeg, webp, tiff.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        clean_bg = background.strip().lower()
        if clean_bg == "transparent":
            if clean_to in ("jpeg", "tiff"):
                raise PDFToolsError(
                    f"Transparent background is not supported for {clean_to.upper()} format.",
                    code="E_INVALID_FORMAT_ALPHA",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                    hint="Use PNG or WebP for transparency, or specify an opaque background.",
                )
            alpha = True
            bg_tuple = (255, 255, 255)
        else:
            alpha = False
            bg_tuple = parse_color(clean_bg)

        if quality is not None:
            if clean_to in ("png", "tiff"):
                raise PDFToolsError(
                    f"--quality is only supported for JPEG and WebP, not {clean_to.upper()}.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )
            eff_quality = quality
        else:
            eff_quality = 85

        clean_cs = colorspace.strip().lower()
        if clean_cs not in ("rgb", "gray"):
            raise PDFToolsError(
                f"Unsupported colorspace '{colorspace}'. Allowed: rgb, gray.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        spec = RenderSpec(
            dpi=dpi,
            format=clean_to,
            alpha=alpha,
            bg_color=bg_tuple,
            quality=eff_quality,
            colorspace=clean_cs,
        )

        if output_dir is not None and output_file is not None:
            raise PDFToolsError(
                "Cannot specify both --output-dir and -o/--output.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )
        if output_dir is None and output_file is None:
            raise PDFToolsError(
                "Must specify either --output-dir or -o/--output.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        # Inspect total pages
        with self.pikepdf.open_document(input_path, password=password) as handle:
            total_pages = len(handle.pdf.pages)

        if pages_range:
            pages_1based = resolve_range(pages_range, total_pages, context="selection")
            selected_indices = [p - 1 for p in pages_1based]
        else:
            selected_indices = list(range(total_pages))

        # Case A: Single page output to file or stdout
        if output_file is not None:
            if len(selected_indices) != 1:
                raise PDFToolsError(
                    "-o/--output can only be used when exactly one page is selected.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                    hint="Use --pages N to select a single page, or use --output-dir.",
                )

            page_idx = selected_indices[0]
            result = self.pdfium.render_page(input_path, page_idx, spec, password=password)

            if str(output_file) == "-":
                sys.stdout.buffer.write(result.image_bytes)
                sys.stdout.buffer.flush()
                return [
                    {
                        "page": result.page_number,
                        "width_px": result.width_px,
                        "height_px": result.height_px,
                        "dpi": result.dpi,
                        "format": result.format,
                        "path": "-",
                    }
                ]

            out_res = Path(output_file).resolve()
            assert_distinct_files(input_path, out_res, operation_name="render")

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="render-", suffix=f".{clean_to}")
                scratch.write_bytes(result.image_bytes)
                AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

            return [
                {
                    "page": result.page_number,
                    "width_px": result.width_px,
                    "height_px": result.height_px,
                    "dpi": result.dpi,
                    "format": result.format,
                    "path": str(out_res),
                }
            ]

        # Case B: Multi-page output to directory
        if output_dir is None:
            raise PDFToolsError(
                "Must specify either --output-dir or -o/--output.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )
        out_dir = Path(output_dir).resolve()
        assert_distinct_files(input_path, out_dir, operation_name="render")
        try:
            input_path.resolve().relative_to(out_dir)
            msg = f"Input file ({input_path.resolve()}) cannot be inside output dir ({out_dir})."
            raise FileSafetyError(
                msg,
                code="E_NESTED_PATH",
                hint="Specify an output directory that does not contain the input file.",
            )
        except ValueError:
            pass

        tpl = template or "{stem}-page-{page:04d}.{ext}"
        tracker = CollisionTracker()

        with InvocationWorkspace() as ws:
            scratch = ws.create_scratch_dir("render")
            manifest: list[dict[str, Any]] = []

            for idx in selected_indices:
                res = self.pdfium.render_page(input_path, idx, spec, password=password)
                filename = render_template(
                    tpl,
                    stem=input_path.stem,
                    page=res.page_number,
                    ext=clean_to,
                )
                tracker.register(out_dir / filename)
                staged_item = scratch / filename
                staged_item.write_bytes(res.image_bytes)
                manifest.append(
                    {
                        "page": res.page_number,
                        "width_px": res.width_px,
                        "height_px": res.height_px,
                        "dpi": res.dpi,
                        "format": res.format,
                        "filename": filename,
                    }
                )

            out_dir.mkdir(parents=True, exist_ok=True)
            for item in manifest:
                src_file = scratch / item["filename"]
                dst_file = out_dir / item["filename"]
                if dst_file.exists() and not overwrite:
                    raise FileSafetyError(
                        f"Destination file '{dst_file}' already exists.",
                        code="E_OUTPUT_EXISTS",
                        hint="Use --overwrite to allow replacing existing files.",
                    )
                shutil.move(str(src_file), str(dst_file))
                item["path"] = str(dst_file)

        return manifest
