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
