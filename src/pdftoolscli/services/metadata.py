"""Document metadata inspection service conforming to PLAN.md §12.6 C31 (CMD-007)."""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.domain.errors import ExitCode, PDFToolsError


def parse_pdf_date(date_str: str | None) -> str | None:
    """Parse a PDF date string (D:YYYYMMDDHHmmSS[Z|+-HH'mm']) to RFC3339."""
    if not date_str:
        return None
    s = str(date_str).strip()
    if s.startswith("D:"):
        s = s[2:]

    pattern = re.compile(
        r"^(\d{4})"
        r"(\d{2})?"
        r"(\d{2})?"
        r"(\d{2})?"
        r"(\d{2})?"
        r"(\d{2})?"
        r"(Z|[\+\-]\d{2}(?:'?\d{2}'?)?)?"
    )
    match = pattern.match(s)
    if not match:
        return s  # preserve raw unparsed string

    year, month, day, hour, minute, second, tz = match.groups()
    month = month or "01"
    day = day or "01"
    hour = hour or "00"
    minute = minute or "00"
    second = second or "00"

    tz_str = "Z"
    if tz and tz != "Z":
        tz_clean = tz.replace("'", "")
        sign = tz_clean[0]
        rest = tz_clean[1:]
        if len(rest) == 2:
            tz_str = f"{sign}{rest}:00"
        elif len(rest) >= 4:
            tz_str = f"{sign}{rest[:2]}:{rest[2:4]}"

    return f"{year}-{month}-{day}T{hour}:{minute}:{second}{tz_str}"


class MetadataService:
    """Service for inspecting standard document Info dictionary and XMP packets."""

    def __init__(self, backend: PikepdfBackend | None = None) -> None:
        self.backend = backend or PikepdfBackend()

    def show(
        self,
        input_path: Path,
        source: str = "all",
        password: str | None = None,
    ) -> dict[str, Any]:
        """Extract and compare Info dictionary and XMP metadata streams."""
        source_mode = source.lower().strip()
        if source_mode not in ("all", "info", "xmp"):
            raise PDFToolsError(
                f"Invalid --source '{source}'. Allowed: all, info, xmp.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        info_data: dict[str, Any] = {}
        xmp_data: dict[str, Any] = {}
        raw_xmp_str: str | None = None
        has_xmp = False

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf

            # 1. Read Info dictionary
            if source_mode in ("all", "info"):
                for k, v in pdf.docinfo.items():
                    clean_key = str(k).lstrip("/")
                    clean_val = str(v)
                    if clean_key in ("CreationDate", "ModDate"):
                        normalized = parse_pdf_date(clean_val)
                        info_data[clean_key] = {
                            "raw": clean_val,
                            "normalized": normalized,
                        }
                    else:
                        info_data[clean_key] = clean_val

            # 2. Read XMP packet
            if source_mode in ("all", "xmp") and "/Metadata" in pdf.Root:
                try:
                    raw_bytes = bytes(pdf.Root.Metadata.read_bytes())
                    raw_xmp_str = raw_bytes.decode("utf-8", errors="replace")
                    has_xmp = True
                except Exception:  # noqa: BLE001
                    raw_xmp_str = None

                with contextlib.suppress(Exception), pdf.open_metadata() as meta:
                    for k, v in meta.items():
                        # Simplify QNames (e.g. {dc_uri}title -> dc:title)
                        qname = str(k)
                        if "dc/elements/1.1/" in qname:
                            short_key = "dc:" + qname.split("}")[-1]
                        elif "pdf/1.3/" in qname:
                            short_key = "pdf:" + qname.split("}")[-1]
                        elif "xap/1.0/" in qname or "xmp/1.0/" in qname:
                            short_key = "xmp:" + qname.split("}")[-1]
                        else:
                            short_key = qname.split("}")[-1]

                        if isinstance(v, list):
                            xmp_data[short_key] = [str(item) for item in v]
                        else:
                            xmp_data[short_key] = str(v)

            # Check if source-specific failure 5 is needed when only xmp requested and missing
            if source_mode == "xmp" and not has_xmp:
                raise PDFToolsError(
                    f"Document '{input_path.name}' contains no XMP metadata stream.",
                    code="E_PDF_INVALID",
                    exit_code=ExitCode.INVALID_DOCUMENT,
                    hint="The document does not have an embedded XMP packet.",
                )

        # 3. Detect discrepancies between Info and XMP
        discrepancies: list[dict[str, Any]] = []
        if source_mode == "all" and info_data and xmp_data:
            key_mappings = [
                ("Title", "dc:title"),
                ("Author", "dc:creator"),
                ("Subject", "dc:description"),
                ("Producer", "pdf:Producer"),
                ("Keywords", "pdf:Keywords"),
            ]
            for info_k, xmp_k in key_mappings:
                if info_k in info_data and xmp_k in xmp_data:
                    i_val = info_data[info_k]
                    if isinstance(i_val, dict):
                        i_val = i_val.get("raw", "")
                    x_val = xmp_data[xmp_k]
                    if isinstance(x_val, list):
                        x_val = ", ".join(x_val)

                    if str(i_val).strip() != str(x_val).strip():
                        discrepancies.append(
                            {
                                "field": info_k,
                                "info_value": str(i_val),
                                "xmp_value": str(x_val),
                            }
                        )

        return {
            "command": "metadata show",
            "input": str(input_path.resolve()),
            "source": source_mode,
            "has_xmp": has_xmp,
            "info": info_data,
            "xmp": xmp_data,
            "raw_xmp": raw_xmp_str,
            "discrepancies": discrepancies,
        }

    def get_raw_xmp(self, input_path: Path, password: str | None = None) -> str:
        """Extract unprocessed XMP XML byte stream directly."""
        with self.backend.open_document(input_path, password=password) as handle:
            if "/Metadata" in handle.pdf.Root:
                try:
                    raw_bytes = bytes(handle.pdf.Root.Metadata.read_bytes())
                    return raw_bytes.decode("utf-8", errors="replace")
                except Exception as err:
                    raise PDFToolsError(
                        f"Failed to read raw XMP packet: {err}",
                        code="E_PDF_INVALID",
                        exit_code=ExitCode.INVALID_DOCUMENT,
                    ) from err
            return ""
