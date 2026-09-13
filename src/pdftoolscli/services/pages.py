"""Page topology operations and split service conforming to PLAN.md §12.3 (CMD-002)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pikepdf

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.domain.errors import ExitCode, PageBoundsError, PDFToolsError
from pdftoolscli.domain.geometry import (
    apply_crop_margins_to_box,
    parse_box_coordinates,
    parse_margins,
    parse_page_size,
)
from pdftoolscli.domain.ranges import resolve_range
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace


def _prune_dangling_outlines(pdf: pikepdf.Pdf) -> None:
    """Safely remove bookmarks pointing to pages no longer in the document."""
    with contextlib.suppress(Exception), pdf.open_outline() as outline:
        page_objgens = {p.objgen for p in pdf.pages}

        def _filter_items(items: list[Any]) -> list[Any]:
            survivors = []
            for item in items:
                keep = True
                dest = getattr(item, "destination", None)
                if dest is not None and isinstance(dest, (list, pikepdf.Array)) and len(dest) > 0:
                    target = dest[0]
                    target_objgen = getattr(target, "objgen", None)
                    if target_objgen is not None and target_objgen not in page_objgens:
                        keep = False
                if keep:
                    if hasattr(item, "children") and item.children:
                        item.children = _filter_items(item.children)
                    survivors.append(item)
            return survivors

        outline.root[:] = _filter_items(outline.root)


class PageService:
    """Service providing single-source page topology and split operations."""

    def __init__(self, backend: PikepdfBackend | None = None) -> None:
        self.backend = backend or PikepdfBackend()

    def split(
        self,
        input_path: Path,
        output_dir: Path,
        every: int | None = None,
        ranges: str | None = None,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Split a document by --every N or --ranges GROUPS into dedicated output directory."""
        if every is not None and ranges is not None:
            raise PDFToolsError(
                "Cannot specify both --every and --ranges.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
                hint="Choose either --every N or --ranges GROUPS.",
            )

        if every is not None and every <= 0:
            raise PDFToolsError(
                f"--every must be a positive integer greater than 0 (got {every}).",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
                hint="Pass a positive integer such as --every 1 or --every 5.",
            )

        effective_every = every
        if every is None and ranges is None:
            effective_every = 1

        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        with self.backend.open_document(input_path, password=password) as handle:
            total_pages = len(handle.pdf.pages)
            if total_pages == 0:
                raise PageBoundsError(
                    "Cannot split an empty document with 0 pages.",
                    page_count=0,
                )

            # Determine page groups (0-based indices)
            groups: list[list[int]] = []
            if effective_every is not None:
                for start_idx in range(0, total_pages, effective_every):
                    end_idx = min(start_idx + effective_every, total_pages)
                    groups.append(list(range(start_idx, end_idx)))
            elif ranges is not None:
                range_specs = [r.strip() for r in ranges.split(";") if r.strip()]
                if not range_specs:
                    raise PDFToolsError(
                        "--ranges cannot be empty.",
                        code="E_CLI_INVALID_OPTION",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                        hint="Specify range expressions, e.g. --ranges '1-3;4-last'.",
                    )
                for r_spec in range_specs:
                    p_indices = resolve_range(r_spec, total_pages, context="sequence")
                    if not p_indices:
                        raise PageBoundsError(
                            f"Range group '{r_spec}' yielded 0 pages.",
                            page_count=total_pages,
                        )
                    groups.append([p - 1 for p in p_indices])

            stem = input_path.stem
            parts_summary: list[dict[str, Any]] = []

            # Preflight destination collision with input
            for i in range(len(groups)):
                part_filename = f"{stem}-part-{i + 1:04d}.pdf"
                dest_path = output_dir / part_filename
                assert_distinct_files(input_path, dest_path, operation_name="split")

            # Extract and write each part atomically
            with InvocationWorkspace() as ws:
                for i, group_pages in enumerate(groups):
                    part_num = i + 1
                    part_filename = f"{stem}-part-{part_num:04d}.pdf"
                    dest_path = output_dir / part_filename

                    extracted_handle = self.backend.extract_pages(handle, group_pages)
                    _prune_dangling_outlines(extracted_handle.pdf)

                    scratch_file = ws.create_scratch_file(
                        prefix=f"split-part-{part_num:04d}-", suffix=".pdf"
                    )
                    self.backend.save(extracted_handle, scratch_file)
                    extracted_handle.close()

                    published = AtomicPublisher.publish_file(
                        scratch_file, dest_path, overwrite=overwrite
                    )
                    parts_summary.append(
                        {
                            "part": part_num,
                            "filename": published.name,
                            "path": str(published.resolve()),
                            "page_count": len(group_pages),
                        }
                    )

            return {
                "source": str(input_path.resolve()),
                "output_dir": str(output_dir.resolve()),
                "total_parts": len(parts_summary),
                "total_source_pages": total_pages,
                "parts": parts_summary,
            }

    def extract(
        self,
        input_path: Path,
        range_expr: str,
        output_path: Path,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Extract arbitrary page sequence into a new PDF."""
        assert_distinct_files(input_path, output_path, operation_name="pages extract")

        with self.backend.open_document(input_path, password=password) as handle:
            total_pages = len(handle.pdf.pages)
            pages_1based = resolve_range(range_expr, total_pages, context="sequence")
            if not pages_1based:
                raise PageBoundsError(
                    "No pages selected for extraction.",
                    page_count=total_pages,
                )

            pages_0based = [p - 1 for p in pages_1based]

            with InvocationWorkspace() as ws:
                extracted = self.backend.extract_pages(handle, pages_0based)
                _prune_dangling_outlines(extracted.pdf)

                scratch = ws.create_scratch_file(prefix="extract-", suffix=".pdf")
                self.backend.save(extracted, scratch)
                extracted.close()

                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

            return {
                "command": "pages extract",
                "input": str(input_path.resolve()),
                "output": str(published.resolve()),
                "page_count": len(pages_1based),
                "pages": pages_1based,
            }

    def remove(
        self,
        input_path: Path,
        range_expr: str,
        output_path: Path,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Delete specified page selection from document."""
        assert_distinct_files(input_path, output_path, operation_name="pages remove")

        with self.backend.open_document(input_path, password=password) as handle:
            total_pages = len(handle.pdf.pages)
            to_remove_1based = resolve_range(range_expr, total_pages, context="selection")

            if len(to_remove_1based) >= total_pages:
                raise PageBoundsError(
                    "Cannot remove all pages from document. A PDF must contain at least one page.",
                    page_count=total_pages,
                    hint="Ensure at least one page remains in the document.",
                )

            survivors_0based = [
                p - 1 for p in range(1, total_pages + 1) if p not in to_remove_1based
            ]

            with InvocationWorkspace() as ws:
                extracted = self.backend.extract_pages(handle, survivors_0based)
                _prune_dangling_outlines(extracted.pdf)

                scratch = ws.create_scratch_file(prefix="remove-", suffix=".pdf")
                self.backend.save(extracted, scratch)
                extracted.close()

                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

            return {
                "command": "pages remove",
                "input": str(input_path.resolve()),
                "output": str(published.resolve()),
                "removed_count": len(to_remove_1based),
                "remaining_count": len(survivors_0based),
            }

    def reorder(
        self,
        input_path: Path,
        order_expr: str,
        output_path: Path,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Apply a complete permutation of all document pages."""
        assert_distinct_files(input_path, output_path, operation_name="pages reorder")

        with self.backend.open_document(input_path, password=password) as handle:
            total_pages = len(handle.pdf.pages)
            new_order_1based = resolve_range(order_expr, total_pages, context="permutation")
            new_order_0based = [p - 1 for p in new_order_1based]

            with InvocationWorkspace() as ws:
                extracted = self.backend.extract_pages(handle, new_order_0based)
                _prune_dangling_outlines(extracted.pdf)

                scratch = ws.create_scratch_file(prefix="reorder-", suffix=".pdf")
                self.backend.save(extracted, scratch)
                extracted.close()

                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

            return {
                "command": "pages reorder",
                "input": str(input_path.resolve()),
                "output": str(published.resolve()),
                "page_count": total_pages,
                "order": new_order_1based,
            }

    def reverse(
        self,
        input_path: Path,
        output_path: Path,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Reverse the entire physical page order of a document."""
        assert_distinct_files(input_path, output_path, operation_name="pages reverse")

        with self.backend.open_document(input_path, password=password) as handle:
            total_pages = len(handle.pdf.pages)
            reversed_0based = list(reversed(range(total_pages)))

            with InvocationWorkspace() as ws:
                extracted = self.backend.extract_pages(handle, reversed_0based)
                _prune_dangling_outlines(extracted.pdf)

                scratch = ws.create_scratch_file(prefix="reverse-", suffix=".pdf")
                self.backend.save(extracted, scratch)
                extracted.close()

                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

            return {
                "command": "pages reverse",
                "input": str(input_path.resolve()),
                "output": str(published.resolve()),
                "page_count": total_pages,
            }

    def rotate(
        self,
        input_path: Path,
        angle: int,
        output_path: Path,
        range_expr: str | None = None,
        absolute: bool = False,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Rotate selected pages by an integer multiple of 90 degrees."""
        if angle % 90 != 0:
            raise PDFToolsError(
                f"Invalid rotation angle {angle}. Angle must be an integer multiple of 90 degrees.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
                hint="Specify 90, 180, 270, or a negative multiple of 90.",
            )

        assert_distinct_files(input_path, output_path, operation_name="pages rotate")

        with self.backend.open_document(input_path, password=password) as handle:
            total_pages = len(handle.pdf.pages)

            if range_expr is not None:
                pages_1based = resolve_range(range_expr, total_pages, context="selection")
                indices_0based = [p - 1 for p in pages_1based]
            else:
                indices_0based = list(range(total_pages))
                pages_1based = list(range(1, total_pages + 1))

            with InvocationWorkspace() as ws:
                # In-memory rotation
                self.backend.rotate_pages(
                    handle,
                    indices_0based,
                    angle,
                    relative=not absolute,
                )

                scratch = ws.create_scratch_file(prefix="rotate-", suffix=".pdf")
                self.backend.save(handle, scratch)

                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

            return {
                "command": "pages rotate",
                "input": str(input_path.resolve()),
                "output": str(published.resolve()),
                "angle": angle % 360,
                "absolute": absolute,
                "rotated_pages_count": len(indices_0based),
            }

    def duplicate(
        self,
        input_path: Path,
        range_expr: str,
        after_page: str,
        output_path: Path,
        copies: int = 1,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Duplicate a selected sequence of pages N times at designated anchor."""
        if copies < 1:
            raise PDFToolsError(
                f"--copies must be a positive integer (got {copies}).",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        assert_distinct_files(input_path, output_path, operation_name="pages duplicate")

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            total_pages = len(pdf.pages)
            resolved = resolve_range(range_expr, total_pages, context="sequence")

            raw_after = after_page.strip().lower()
            if raw_after == "0":
                anchor = 0
            elif raw_after == "last":
                anchor = total_pages
            else:
                try:
                    val = int(raw_after)
                    if val < 0 or val > total_pages:
                        raise ValueError()
                    anchor = val
                except ValueError:
                    raise PDFToolsError(
                        f"Invalid --after page '{after_page}'. Expected 0 (before first), "
                        f"'last', or an integer between 1 and {total_pages}.",
                        code="E_PAGE_BOUNDS",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    ) from None

            clones: list[pikepdf.Page] = []
            for _ in range(copies):
                for page_num in resolved:
                    src_page = pdf.pages[page_num - 1]
                    cloned_obj = pdf.make_indirect(src_page.obj.copy())
                    clones.append(pikepdf.Page(cloned_obj))

            pdf.pages[anchor:anchor] = clones
            final_count = len(pdf.pages)

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="duplicate-", suffix=".pdf")
                self.backend.save(handle, scratch)
                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

            return {
                "command": "pages duplicate",
                "input": str(input_path.resolve()),
                "output": str(published.resolve()),
                "copies": copies,
                "duplicated_pages_count": len(resolved) * copies,
                "total_pages": final_count,
            }

    def crop(
        self,
        input_path: Path,
        margins_str: str,
        output_path: Path,
        range_expr: str | None = None,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Apply margin offsets to displayed CropBox coordinates of selected pages."""
        margins = parse_margins(margins_str)
        assert_distinct_files(input_path, output_path, operation_name="pages crop")

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            total_pages = len(pdf.pages)
            if range_expr is not None:
                pages_1based = resolve_range(range_expr, total_pages, context="selection")
            else:
                pages_1based = list(range(1, total_pages + 1))

            for p_num in pages_1based:
                page = pdf.pages[p_num - 1]
                raw_box = (
                    page.cropbox if hasattr(page, "cropbox") and page.cropbox else page.mediabox
                )
                curr_box = [float(c) for c in raw_box]
                rot = (
                    int(page.rotation)
                    if hasattr(page, "rotation") and page.rotation is not None
                    else 0
                )
                new_box = apply_crop_margins_to_box(curr_box, margins, rotation=rot)
                page.cropbox = pikepdf.Rectangle(*new_box)

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="crop-", suffix=".pdf")
                self.backend.save(handle, scratch)
                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

            return {
                "command": "pages crop",
                "input": str(input_path.resolve()),
                "output": str(published.resolve()),
                "margins": margins_str,
                "cropped_pages_count": len(pages_1based),
                "total_pages": total_pages,
            }

    def resize(
        self,
        input_path: Path,
        size_str: str,
        output_path: Path,
        fit: str = "none",
        anchor: str = "center",
        range_expr: str | None = None,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Resize selected pages to standard dimensions or explicit dimensions."""
        target_w, target_h = parse_page_size(size_str)
        fit_mode = fit.lower().strip()
        if fit_mode not in ("none", "contain"):
            raise PDFToolsError(
                f"Invalid --fit mode '{fit}'. Allowed values: none, contain.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        assert_distinct_files(input_path, output_path, operation_name="pages resize")

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            total_pages = len(pdf.pages)
            if range_expr is not None:
                pages_1based = resolve_range(range_expr, total_pages, context="selection")
            else:
                pages_1based = list(range(1, total_pages + 1))

            for p_num in pages_1based:
                page = pdf.pages[p_num - 1]
                cur_mb = [float(c) for c in page.mediabox]
                cur_w = cur_mb[2] - cur_mb[0]
                cur_h = cur_mb[3] - cur_mb[1]

                if fit_mode == "contain":
                    scale = min(target_w / cur_w, target_h / cur_h)
                    scaled_w = cur_w * scale
                    scaled_h = cur_h * scale
                    tx = (target_w - scaled_w) / 2.0 - cur_mb[0] * scale
                    ty = (target_h - scaled_h) / 2.0 - cur_mb[1] * scale
                    prefix = f"q {scale:.6f} 0 0 {scale:.6f} {tx:.4f} {ty:.4f} cm\n".encode("ascii")
                    suffix = b"\nQ\n"
                    page.contents_add(prefix, prepend=True)
                    page.contents_add(suffix, prepend=False)
                else:
                    tx = (target_w - cur_w) / 2.0 - cur_mb[0]
                    ty = (target_h - cur_h) / 2.0 - cur_mb[1]
                    prefix = f"q 1 0 0 1 {tx:.4f} {ty:.4f} cm\n".encode("ascii")
                    suffix = b"\nQ\n"
                    page.contents_add(prefix, prepend=True)
                    page.contents_add(suffix, prepend=False)

                page.mediabox = pikepdf.Rectangle(0, 0, target_w, target_h)
                if hasattr(page, "cropbox") and page.cropbox:
                    page.cropbox = pikepdf.Rectangle(0, 0, target_w, target_h)

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="resize-", suffix=".pdf")
                self.backend.save(handle, scratch)
                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

            return {
                "command": "pages resize",
                "input": str(input_path.resolve()),
                "output": str(published.resolve()),
                "size": size_str,
                "fit": fit_mode,
                "resized_pages_count": len(pages_1based),
                "total_pages": total_pages,
            }

    def boxes(
        self,
        input_path: Path,
        set_boxes: list[tuple[str, str]],
        output_path: Path,
        range_expr: str | None = None,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """View or set raw unrotated PDF bounding boxes (media, crop, trim, bleed, art)."""
        if not set_boxes:
            raise PDFToolsError(
                "pages boxes requires at least one '--set BOX=LLX,LLY,URX,URY' option.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        valid_boxes = {
            "media": "mediabox",
            "crop": "cropbox",
            "trim": "trimbox",
            "bleed": "bleedbox",
            "art": "artbox",
        }
        parsed_sets: dict[str, tuple[float, float, float, float]] = {}
        for b_name, coords_str in set_boxes:
            b_key = b_name.lower().strip()
            if b_key not in valid_boxes:
                raise PDFToolsError(
                    f"Invalid box '{b_name}'. Allowed boxes: media, crop, trim, bleed, art.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )
            if b_key in parsed_sets:
                raise PDFToolsError(
                    f"Duplicate box setting for '{b_name}'.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )
            parsed_sets[b_key] = parse_box_coordinates(coords_str)

        assert_distinct_files(input_path, output_path, operation_name="pages boxes")

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            total_pages = len(pdf.pages)
            if range_expr is not None:
                pages_1based = resolve_range(range_expr, total_pages, context="selection")
            else:
                pages_1based = list(range(1, total_pages + 1))

            for p_num in pages_1based:
                page = pdf.pages[p_num - 1]

                for b_key, coords in parsed_sets.items():
                    setattr(page, valid_boxes[b_key], pikepdf.Rectangle(*coords))

                mb = [float(c) for c in page.mediabox]
                cb = [float(c) for c in page.cropbox] if page.cropbox else mb
                if cb[0] < mb[0] or cb[1] < mb[1] or cb[2] > mb[2] or cb[3] > mb[3]:
                    raise PDFToolsError(
                        f"Page {p_num}: CropBox ({cb}) must be contained within MediaBox ({mb}).",
                        code="E_CLI_INVALID_OPTION",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    )

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="boxes-", suffix=".pdf")
                self.backend.save(handle, scratch)
                published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

            return {
                "command": "pages boxes",
                "input": str(input_path.resolve()),
                "output": str(published.resolve()),
                "set_boxes": [{"box": b, "coordinates": c} for b, c in set_boxes],
                "modified_pages_count": len(pages_1based),
                "total_pages": total_pages,
            }
