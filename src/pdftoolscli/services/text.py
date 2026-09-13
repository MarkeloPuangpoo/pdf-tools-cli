from __future__ import annotations

import multiprocessing
import re
from pathlib import Path
from typing import Any

from pdftoolscli.backends.pdfium_backend import PdfiumBackend
from pdftoolscli.contracts.text import TextExtractSpec, TextPageResult
from pdftoolscli.domain.errors import ExitCode, PageBoundsError, PDFToolsError, ResourceLimitError
from pdftoolscli.domain.ranges import resolve_range
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace


def _regex_worker(pattern_str: str, flags: int, text: str, queue: Any) -> None:
    """Worker process target for isolated regex search execution."""
    try:
        pat = re.compile(pattern_str, flags)
        matches = [(m.start(), m.end()) for m in pat.finditer(text)]
        queue.put((True, matches))
    except Exception as e:
        queue.put((False, str(e)))


class TextService:
    """Service providing plain text extraction and in-document pattern matching."""

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

    def search(
        self,
        input_path: Path,
        pattern: str,
        regex: bool = False,
        ignore_case: bool = False,
        pages_range: str | None = None,
        max_matches: int = 10000,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Search text across document pages with optional regex and isolated timeout."""
        if not input_path.is_file():
            raise PDFToolsError(
                f"Input file not found: '{input_path}'.",
                code="E_IO_NOT_FOUND",
                exit_code=ExitCode.IO_ERROR,
            )

        flags = re.IGNORECASE if ignore_case else 0
        if regex:
            try:
                re.compile(pattern, flags)
            except re.error as err:
                raise PDFToolsError(
                    f"Invalid regular expression pattern '{pattern}': {err}",
                    code="E_REGEX_SYNTAX",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                    hint="Check regular expression syntax for errors.",
                ) from err
            pattern_to_run = pattern
        else:
            pattern_to_run = re.escape(pattern)

        doc = self.backend._open_doc(input_path, password=password)
        try:
            total_pages = len(doc)
        finally:
            doc.close()

        if total_pages == 0:
            return {
                "input": str(input_path.resolve()),
                "pattern": pattern,
                "regex": regex,
                "ignore_case": ignore_case,
                "count": 0,
                "matches": [],
                "truncated": False,
            }

        if pages_range:
            pages_1based = resolve_range(pages_range, total_pages, context="selection")
            indices_0based = [p - 1 for p in pages_1based]
        else:
            indices_0based = list(range(total_pages))

        spec = TextExtractSpec(include_page_breaks=False, include_boxes=False)
        page_results = self.backend.extract_document_text(
            input_path, indices_0based, spec, password=password
        )

        all_matches: list[dict[str, Any]] = []
        total_count = 0
        truncated = False

        for r in page_results:
            page_text = r.text
            if not page_text:
                continue

            if regex:
                ctx = multiprocessing.get_context("spawn")
                q: Any = ctx.Queue()
                p = ctx.Process(
                    target=_regex_worker,
                    args=(pattern_to_run, flags, page_text, q),
                )
                p.start()
                p.join(timeout=2.0)
                if p.is_alive():
                    p.kill()
                    p.join()
                    raise ResourceLimitError(
                        f"Regular expression matching timed out (> 2.0s) on page {r.page_number}.",
                        hint="Simplify regular expression pattern to avoid backtracking.",
                    )
                try:
                    ok, raw_matches = q.get_nowait()
                except Exception:
                    ok, raw_matches = False, []
                if not ok:
                    continue
            else:
                pat = re.compile(pattern_to_run, flags)
                raw_matches = [(m.start(), m.end()) for m in pat.finditer(page_text)]

            for start, end in raw_matches:
                total_count += 1
                if max_matches == 0 or len(all_matches) < max_matches:
                    snippet = (
                        page_text[max(0, start - 30) : min(len(page_text), end + 30)]
                        .replace("\n", " ")
                        .strip()
                    )
                    all_matches.append(
                        {
                            "page": r.page_number,
                            "start": start,
                            "end": end,
                            "snippet": snippet,
                        }
                    )
                else:
                    truncated = True

        return {
            "input": str(input_path.resolve()),
            "pattern": pattern,
            "regex": regex,
            "ignore_case": ignore_case,
            "count": total_count,
            "matches": all_matches,
            "truncated": truncated,
        }
