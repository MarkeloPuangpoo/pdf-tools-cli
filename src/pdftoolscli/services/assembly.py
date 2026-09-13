"""Document assembly and concatenation service conforming to PLAN.md §12.3 C05 (CMD-003)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

import pikepdf

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend, PikepdfDocumentHandle
from pdftoolscli.contracts.editing import OutlineNode
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace


def _transfer_outline_nodes(
    nodes: list[OutlineNode],
    target_root: list[pikepdf.OutlineItem],
    page_offset: int,
) -> None:
    """Transfer and rebase bookmark targets with page offset."""
    for node in nodes:
        target_page_0based = (node.page_number - 1) + page_offset
        item = pikepdf.OutlineItem(node.title, target_page_0based)
        if node.children:
            _transfer_outline_nodes(node.children, item.children, page_offset)
        target_root.append(item)


class AssemblyService:
    """Service providing multi-document assembly and concatenation."""

    def __init__(self, backend: PikepdfBackend | None = None) -> None:
        self.backend = backend or PikepdfBackend()

    def merge(
        self,
        input_paths: list[Path],
        output_path: Path,
        document_policy: str = "none",
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Concatenate multiple PDF documents in exact order."""
        if len(input_paths) < 2:
            raise PDFToolsError(
                f"Merge requires at least two input documents (got {len(input_paths)}).",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
                hint="Specify two or more input PDFs, e.g. `merge doc1.pdf doc2.pdf -o out.pdf`.",
            )

        policy = document_policy.lower().strip()
        if policy not in ("none", "first"):
            raise PDFToolsError(
                f"Invalid --document-policy '{document_policy}'. Allowed values: none, first.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        output_path = Path(output_path).resolve()
        for in_p in input_paths:
            assert_distinct_files(in_p, output_path, operation_name="merge")

        merged_pdf = pikepdf.new()
        accumulated_pages = 0
        outline_nodes_to_transfer: list[tuple[list[OutlineNode], int]] = []

        # Open sources lazily one by one to prevent fd exhaustion
        for idx, in_p in enumerate(input_paths):
            with self.backend.open_document(in_p, password=password) as handle:
                if policy == "first" and idx == 0:
                    with contextlib.suppress(Exception):
                        merged_pdf.docinfo.update(handle.pdf.docinfo)

                if policy == "first":
                    nodes = self.backend.get_outlines(handle)
                    if nodes:
                        outline_nodes_to_transfer.append((nodes, accumulated_pages))

                page_count = len(handle.pdf.pages)
                merged_pdf.pages.extend(handle.pdf.pages)
                accumulated_pages += page_count

        # Transfer outlines with page offset if policy is first
        if outline_nodes_to_transfer:
            with contextlib.suppress(Exception), merged_pdf.open_outline() as target_outline:
                for nodes, offset in outline_nodes_to_transfer:
                    _transfer_outline_nodes(nodes, target_outline.root, offset)

        with InvocationWorkspace() as ws:
            scratch = ws.create_scratch_file(prefix="merge-", suffix=".pdf")
            merged_handle = PikepdfDocumentHandle(path=None, pdf=merged_pdf)
            self.backend.save(merged_handle, scratch)
            merged_handle.close()

            published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

        return {
            "command": "merge",
            "inputs": [str(p.resolve()) for p in input_paths],
            "output": str(published.resolve()),
            "total_pages": accumulated_pages,
            "input_count": len(input_paths),
            "document_policy": policy,
        }

    def assemble(
        self,
        sources: list[tuple[Path, str]],
        output_path: Path,
        document_policy: str = "none",
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Assemble a new PDF from multiple (path, range) pairs."""
        if not sources:
            raise PDFToolsError(
                "Assemble requires at least one --source PATH RANGE specification.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        policy = document_policy.lower().strip()
        if policy not in ("none", "first"):
            raise PDFToolsError(
                f"Invalid --document-policy '{document_policy}'. Allowed values: none, first.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        out_res = Path(output_path).resolve()
        for p, _ in sources:
            assert_distinct_files(p, out_res, operation_name="assemble")

        from pdftoolscli.domain.ranges import resolve_range

        out_pdf = pikepdf.new()
        total_assembled = 0

        for idx, (src_path, range_expr) in enumerate(sources):
            with self.backend.open_document(src_path, password=password) as handle:
                src_count = len(handle.pdf.pages)
                resolved = resolve_range(range_expr, src_count, context="sequence")
                if not resolved:
                    raise PDFToolsError(
                        f"Source '{src_path}' range '{range_expr}' resolved to 0 pages.",
                        code="E_PAGE_BOUNDS",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    )

                if policy == "first" and idx == 0:
                    with contextlib.suppress(Exception):
                        out_pdf.docinfo.update(handle.pdf.docinfo)

                for page_num in resolved:
                    out_pdf.pages.append(handle.pdf.pages[page_num - 1])
                    total_assembled += 1

        with InvocationWorkspace() as ws:
            scratch = ws.create_scratch_file(prefix="assemble-", suffix=".pdf")
            handle_out = PikepdfDocumentHandle(path=None, pdf=out_pdf)
            self.backend.save(handle_out, scratch)
            handle_out.close()
            published = AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "command": "assemble",
            "sources": [{"path": str(p), "range": r} for p, r in sources],
            "output": str(published.resolve()),
            "total_pages": total_assembled,
            "document_policy": policy,
        }

    def insert(
        self,
        base_path: Path,
        insert_path: Path,
        after_page: str,
        output_path: Path,
        pages_range: str = "all",
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Insert a page sequence from secondary PDF into base document at designated anchor."""
        out_res = Path(output_path).resolve()
        assert_distinct_files(base_path, out_res, operation_name="insert")
        assert_distinct_files(insert_path, out_res, operation_name="insert")

        from pdftoolscli.domain.ranges import resolve_range

        with self.backend.open_document(base_path, password=password) as base_handle:
            base_pdf = base_handle.pdf
            base_count = len(base_pdf.pages)

            # Resolve anchor PAGE
            raw_after = after_page.strip().lower()
            if raw_after == "0":
                anchor = 0
            elif raw_after == "last":
                anchor = base_count
            else:
                try:
                    val = int(raw_after)
                    if val < 0 or val > base_count:
                        raise ValueError()
                    anchor = val
                except ValueError:
                    raise PDFToolsError(
                        f"Invalid --after page '{after_page}'. Expected 0 (before first), "
                        f"'last', or an integer between 1 and {base_count}.",
                        code="E_PAGE_BOUNDS",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    ) from None

            with self.backend.open_document(insert_path, password=password) as ins_handle:
                ins_pdf = ins_handle.pdf
                ins_count = len(ins_pdf.pages)
                resolved = resolve_range(pages_range, ins_count, context="sequence")

                # Insert pages at anchor position
                inserted_pages = [ins_pdf.pages[i - 1] for i in resolved]
                base_pdf.pages[anchor:anchor] = inserted_pages
                final_count = len(base_pdf.pages)

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="insert-", suffix=".pdf")
                self.backend.save(base_handle, scratch)
                published = AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "command": "insert",
            "base": str(base_path.resolve()),
            "inserted": str(insert_path.resolve()),
            "after_page": after_page,
            "inserted_pages_count": len(resolved),
            "output": str(published.resolve()),
            "total_pages": final_count,
        }

    def interleave(
        self,
        input_paths: list[Path],
        output_path: Path,
        remainder: str = "append",
        reverse_even_inputs: bool = False,
        document_policy: str = "none",
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Interleave pages round-robin from multiple PDF inputs."""
        if len(input_paths) < 2:
            raise PDFToolsError(
                f"Interleave requires at least two inputs (got {len(input_paths)}).",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        rem_policy = remainder.lower().strip()
        if rem_policy not in ("append", "error"):
            raise PDFToolsError(
                f"Invalid --remainder policy '{remainder}'. Allowed values: append, error.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        doc_policy = document_policy.lower().strip()
        if doc_policy not in ("none", "first"):
            raise PDFToolsError(
                f"Invalid --document-policy '{document_policy}'. Allowed values: none, first.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        out_res = Path(output_path).resolve()
        for p in input_paths:
            assert_distinct_files(p, out_res, operation_name="interleave")

        opened_docs: list[pikepdf.Pdf] = []
        pages_lists: list[list[pikepdf.Page]] = []

        try:
            for p in input_paths:
                pdf = pikepdf.open(p, password=password or "")
                opened_docs.append(pdf)
                pages_lists.append(list(pdf.pages))

            # Check lengths if remainder == error
            lengths = [len(pl) for pl in pages_lists]
            if rem_policy == "error" and len(set(lengths)) > 1:
                raise PDFToolsError(
                    f"Interleave inputs have unequal page counts: {lengths}.",
                    code="E_PAGE_COUNT_MISMATCH",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                    hint="Use '--remainder append' to interleave documents of different lengths.",
                )

            # If reverse_even_inputs, reverse pages of 2nd, 4th, ... (index 1, 3, 5...)
            if reverse_even_inputs:
                for i in range(1, len(pages_lists), 2):
                    pages_lists[i].reverse()

            out_pdf = pikepdf.new()
            if doc_policy == "first" and opened_docs:
                with contextlib.suppress(Exception):
                    out_pdf.docinfo.update(opened_docs[0].docinfo)

            max_len = max(lengths)
            total_interleaved = 0
            for step in range(max_len):
                for pl in pages_lists:
                    if step < len(pl):
                        out_pdf.pages.append(pl[step])
                        total_interleaved += 1

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="interleave-", suffix=".pdf")
                handle_out = PikepdfDocumentHandle(path=None, pdf=out_pdf)
                self.backend.save(handle_out, scratch)
                handle_out.close()
                published = AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)
        finally:
            for d in opened_docs:
                with contextlib.suppress(Exception):
                    d.close()

        return {
            "command": "interleave",
            "inputs": [str(p.resolve()) for p in input_paths],
            "output": str(published.resolve()),
            "total_pages": total_interleaved,
            "remainder": rem_policy,
            "reverse_even_inputs": reverse_even_inputs,
            "document_policy": doc_policy,
        }
