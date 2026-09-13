"""Plain text extraction service conforming to PLAN.md §12.5 C26 (CMD-006)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pdftoolscli.backends.pdfium_backend import PdfiumBackend
from pdftoolscli.contracts.text import TextExtractSpec, TextPageResult
from pdftoolscli.domain.errors import ExitCode, PageBoundsError, PDFToolsError
from pdftoolscli.domain.ranges import resolve_range
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace


class TextService:
    """Service providing plain text extraction using PDFium engine."""

    def __init__(self, backend: PdfiumBackend | None = None) -> None:
        self.backend = backend or PdfiumBackend()

    def extract(
        self,
        input_path: Path,
        range_expr: str | None = None,
        output_path: Path | None = None,
        require_text: bool = False,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Extract clean UTF-8 text from document pages."""
        if output_path is not None:
            assert_distinct_files(input_path, output_path, operation_name="text extract")

        # Open doc using pdfium to determine total page count
        doc = self.backend._open_doc(input_path, password=password)
        try:
            total_pages = len(doc)
        finally:
            doc.close()

        if total_pages == 0:
            raise PageBoundsError("Cannot extract text from 0-page document.", page_count=0)

        if range_expr is not None:
            pages_1based = resolve_range(range_expr, total_pages, context="sequence")
            if not pages_1based:
                raise PageBoundsError(
                    "No pages selected for text extraction.",
                    page_count=total_pages,
                )
            indices_0based = [p - 1 for p in pages_1based]
        else:
            pages_1based = list(range(1, total_pages + 1))
            indices_0based = list(range(total_pages))

        spec = TextExtractSpec(include_page_breaks=False, include_boxes=False)
        page_results: list[TextPageResult] = self.backend.extract_document_text(
            input_path, indices_0based, spec, password=password
        )

        full_text = "\x0c".join(r.text for r in page_results)
        has_any_text = any(bool(r.text.strip()) for r in page_results)

        if require_text and not has_any_text:
            raise PDFToolsError(
                f"Document '{input_path.name}' contains no extractable text layer.",
                code="E_PDF_INVALID",
                exit_code=ExitCode.INVALID_DOCUMENT,
                hint="Document may be a scanned image. Use OCR toolchain to extract text.",
            )

        published_path: Path | None = None
        if output_path is not None:
            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="text-", suffix=".txt")
                scratch.write_text(full_text, encoding="utf-8", newline="\n")

                published_path = AtomicPublisher.publish_file(
                    scratch, output_path, overwrite=overwrite
                )

        page_records = [
            {
                "page": r.page_number,
                "text": r.text,
                "char_count": r.char_count,
                "has_text": bool(r.text.strip()),
            }
            for r in page_results
        ]

        return {
            "command": "text extract",
            "input": str(input_path.resolve()),
            "output": str(published_path.resolve()) if published_path else None,
            "total_pages": len(page_results),
            "pages": pages_1based,
            "char_count": len(full_text),
            "has_text": has_any_text,
            "text": full_text,
            "page_records": page_records,
        }
