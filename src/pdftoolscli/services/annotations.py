"""Annotations inspection and removal service conforming to PLAN.md §12.7 C42-C43 (CMD-014)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pikepdf

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.domain.errors import ExitCode, FileSafetyError, PDFToolsError
from pdftoolscli.domain.ranges import resolve_range
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace


class AnnotationsService:
    """Service for listing and removing non-widget PDF annotations."""

    def __init__(self, backend: PikepdfBackend | None = None) -> None:
        self.backend = backend or PikepdfBackend()

    def list_annotations(
        self,
        input_path: Path,
        page_selection: str = "all",
        include_content: bool = False,
        password: str | None = None,
    ) -> list[dict[str, Any]]:
        """Inspect and list annotations across selected pages."""
        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            total_pages = len(pdf.pages)
            if total_pages == 0:
                return []

            selected_pages = resolve_range(page_selection, total_pages)
            results: list[dict[str, Any]] = []

            for page_num in selected_pages:
                page = pdf.pages[page_num - 1]
                if "/Annots" not in page or not isinstance(page.Annots, pikepdf.Array):
                    continue
                annots = list(page.Annots)

                for idx, annot in enumerate(annots):
                    if not isinstance(annot, (pikepdf.Dictionary, pikepdf.Stream)):
                        continue

                    raw_subtype = str(annot.get("/Subtype", "Unknown")).lstrip("/")
                    raw_rect = annot.get("/Rect", [0.0, 0.0, 0.0, 0.0])
                    try:
                        rect = [float(x) for x in raw_rect]
                    except Exception:
                        rect = [0.0, 0.0, 0.0, 0.0]

                    flags = int(annot.get("/F", 0)) if "/F" in annot else 0
                    author_present = "/T" in annot

                    obj_id = f"ann-p{page_num}-{idx}"
                    objgen = getattr(annot, "objgen", (0, 0))

                    item: dict[str, Any] = {
                        "id": obj_id,
                        "objgen": f"{objgen[0]} {objgen[1]} R" if objgen[0] != 0 else None,
                        "page": page_num,
                        "subtype": raw_subtype,
                        "rect": rect,
                        "flags": flags,
                        "author_present": author_present,
                    }

                    if include_content:
                        item["author"] = str(annot.get("/T")) if "/T" in annot else None
                        item["content"] = (
                            str(annot.get("/Contents")) if "/Contents" in annot else None
                        )
                        item["modification_date"] = str(annot.get("/M")) if "/M" in annot else None
                        popup_id = None
                        if "/Popup" in annot:
                            pop = annot.Popup
                            for p_idx, candidate in enumerate(annots):
                                if (
                                    getattr(candidate, "objgen", None)
                                    == getattr(pop, "objgen", None)
                                    and candidate.objgen[0] != 0
                                ):
                                    popup_id = f"ann-p{page_num}-{p_idx}"
                                    break
                        item["popup_id"] = popup_id

                    results.append(item)

            return results

    def remove_annotations(
        self,
        input_path: Path,
        output_path: Path,
        all_annotations: bool = False,
        types: list[str] | None = None,
        ids: list[str] | None = None,
        page_selection: str = "all",
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Remove targeted non-widget annotations and reconcile popup/reply links."""
        out_res = output_path.resolve()
        assert_distinct_files(input_path, out_res, operation_name="annotations remove")

        if out_res.exists() and not overwrite:
            raise FileSafetyError(
                f"Destination file '{out_res}' already exists.",
                code="E_OUTPUT_EXISTS",
                hint="Use --overwrite to allow replacing existing files.",
            )

        # Preflight validation of deletion targets
        active_options = sum([bool(all_annotations), bool(types), bool(ids)])
        if active_options != 1:
            raise PDFToolsError(
                "Exactly one of --all, --type, or --id must be specified.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        normalized_types = set()
        if types:
            for t in types:
                clean_t = t.strip().lower()
                if clean_t == "widget":
                    raise PDFToolsError(
                        "Widget annotations cannot be removed using 'annotations remove'. "
                        "Interactive form fields are managed by forms commands.",
                        code="E_CLI_INVALID_OPTION",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                        hint="Use 'forms' commands to manage or flatten form fields.",
                    )
                normalized_types.add(clean_t)

        target_ids = set(ids) if ids else set()
        matched_ids: set[str] = set()

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            total_pages = len(pdf.pages)
            if total_pages == 0:
                raise PDFToolsError("Document has 0 pages.", code="E_FILE_CORRUPT")

            selected_pages = resolve_range(page_selection, total_pages)
            removed_count = 0
            widgets_preserved_count = 0
            pages_affected: set[int] = set()

            # First pass for ID discovery if targeting by ID
            if target_ids:
                all_known_ids: set[str] = set()
                for page_num in selected_pages:
                    page = pdf.pages[page_num - 1]
                    if "/Annots" not in page or not isinstance(page.Annots, pikepdf.Array):
                        continue
                    page_annots = list(page.Annots)
                    for idx, annot in enumerate(page_annots):
                        obj_id = f"ann-p{page_num}-{idx}"
                        all_known_ids.add(obj_id)
                        objgen = getattr(annot, "objgen", (0, 0))
                        if objgen[0] != 0:
                            all_known_ids.add(str(objgen[0]))

                unmatched = target_ids - all_known_ids
                if unmatched:
                    missing_str = ", ".join(sorted(unmatched))
                    raise PDFToolsError(
                        f"Annotation ID(s) not found: {missing_str}.",
                        code="E_CLI_INVALID_OPTION",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    )

            # Perform removal page by page
            for page_num in selected_pages:
                page = pdf.pages[page_num - 1]
                if "/Annots" not in page or not isinstance(page.Annots, pikepdf.Array):
                    continue
                current_annots = list(page.Annots)

                to_remove_objgens: set[tuple[int, int]] = set()
                to_remove_direct: list[Any] = []
                page_removed_count = 0

                # Identify annotations to remove
                for idx, annot in enumerate(current_annots):
                    if not isinstance(annot, (pikepdf.Dictionary, pikepdf.Stream)):
                        continue

                    raw_subtype = str(annot.get("/Subtype", "")).lstrip("/")
                    is_widget = raw_subtype.lower() == "widget"

                    if is_widget:
                        widgets_preserved_count += 1
                        continue

                    obj_id = f"ann-p{page_num}-{idx}"
                    objgen = getattr(annot, "objgen", (0, 0))
                    obj_num_str = str(objgen[0]) if objgen[0] != 0 else ""

                    match_type = bool(normalized_types and raw_subtype.lower() in normalized_types)
                    should_remove = False
                    if all_annotations or match_type:
                        should_remove = True
                    elif target_ids and (obj_id in target_ids or obj_num_str in target_ids):
                        should_remove = True
                        if obj_id in target_ids:
                            matched_ids.add(obj_id)
                        if obj_num_str in target_ids:
                            matched_ids.add(obj_num_str)

                    if should_remove:
                        if objgen[0] != 0:
                            to_remove_objgens.add(objgen)
                        else:
                            to_remove_direct.append(annot)
                        page_removed_count += 1

                        # Cascade removal to linked popup
                        if "/Popup" in annot:
                            pop = annot.Popup
                            pop_objgen = getattr(pop, "objgen", (0, 0))
                            if pop_objgen[0] != 0:
                                to_remove_objgens.add(pop_objgen)
                            else:
                                to_remove_direct.append(pop)

                if not to_remove_objgens and not to_remove_direct:
                    continue

                # Reconcile surviving annotations
                surviving_annots: list[Any] = []
                for annot in current_annots:
                    objgen = getattr(annot, "objgen", (0, 0))
                    is_marked = (objgen in to_remove_objgens and objgen[0] != 0) or any(
                        annot == d for d in to_remove_direct
                    )

                    if is_marked:
                        continue

                    # Clean up dangling /Popup pointer
                    if "/Popup" in annot:
                        pop = annot.Popup
                        pop_og = getattr(pop, "objgen", (0, 0))
                        if pop_og in to_remove_objgens and pop_og[0] != 0:
                            del annot["/Popup"]

                    # Clean up dangling /Parent pointer on popups
                    if "/Parent" in annot:
                        parent = annot.Parent
                        par_og = getattr(parent, "objgen", (0, 0))
                        if par_og in to_remove_objgens and par_og[0] != 0:
                            del annot["/Parent"]

                    # Clean up dangling /IRT (In-Reply-To) pointer
                    if "/IRT" in annot:
                        irt = annot.IRT
                        irt_og = getattr(irt, "objgen", (0, 0))
                        if irt_og in to_remove_objgens and irt_og[0] != 0:
                            del annot["/IRT"]

                    surviving_annots.append(annot)

                if len(surviving_annots) < len(current_annots):
                    pages_affected.add(page_num)
                    removed_count += page_removed_count

                    if surviving_annots:
                        page.Annots = pdf.make_indirect(pikepdf.Array(surviving_annots))
                    else:
                        del page["/Annots"]

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="annot-rem-", suffix=".pdf")
                pdf.save(scratch)
                AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "input": str(input_path.resolve()),
            "output": str(out_res),
            "removed_count": removed_count,
            "pages_affected": len(pages_affected),
            "widgets_preserved": widgets_preserved_count,
        }
