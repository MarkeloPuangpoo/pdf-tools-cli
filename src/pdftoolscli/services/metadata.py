"""Document metadata service conforming to PLAN.md §12.6 C31-C34 (CMD-007, CMD-012)."""

from __future__ import annotations

import contextlib
import re
import xml.etree.ElementTree
from datetime import datetime
from pathlib import Path
from typing import Any

import pikepdf

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.domain.errors import ExitCode, FileSafetyError, PDFToolsError
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace

STANDARD_METADATA_KEYS: dict[str, tuple[str, str]] = {
    "title": ("/Title", "dc:title"),
    "author": ("/Author", "dc:creator"),
    "subject": ("/Subject", "dc:description"),
    "keywords": ("/Keywords", "pdf:Keywords"),
    "creator": ("/Creator", "xmp:CreatorTool"),
    "producer": ("/Producer", "pdf:Producer"),
    "creation-date": ("/CreationDate", "xmp:CreateDate"),
    "modification-date": ("/ModDate", "xmp:ModifyDate"),
}


def rfc3339_to_pdf_date(rfc_str: str) -> str:
    """Validate RFC3339 date string and convert to PDF date string format."""
    s = rfc_str.strip()
    try:
        dt = datetime.fromisoformat(s)
    except Exception as err:
        raise PDFToolsError(
            f"Invalid RFC3339 date format '{rfc_str}'. "
            "Expected format like '2023-08-15T12:00:00Z' or '2023-08-15T12:00:00+02:00'.",
            code="E_DATE_FORMAT",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint="Provide a valid ISO8601/RFC3339 timestamp with timezone offset.",
        ) from err

    tz_str = "Z"
    if dt.tzinfo is not None:
        offset = dt.utcoffset()
        if offset is not None:
            total_seconds = int(offset.total_seconds())
            if total_seconds != 0:
                sign = "+" if total_seconds >= 0 else "-"
                total_mins = abs(total_seconds) // 60
                h = total_mins // 60
                m = total_mins % 60
                tz_str = f"{sign}{h:02d}'{m:02d}'"

    return (
        f"D:{dt.year:04d}{dt.month:02d}{dt.day:02d}"
        f"{dt.hour:02d}{dt.minute:02d}{dt.second:02d}{tz_str}"
    )


def validate_xmp_xml(raw_bytes: bytes) -> None:
    """Validate that XMP byte stream is well-formed XML without XXE / entity bombs."""
    if b"<!ENTITY" in raw_bytes or b"<!DOCTYPE" in raw_bytes:
        raise PDFToolsError(
            "XMP XML contains forbidden DOCTYPE or ENTITY declaration.",
            code="E_XML_INVALID",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint="Remove DTD and ENTITY definitions from XMP file.",
        )
    try:
        # We explicitly verify no DOCTYPE or ENTITY tags exist above before parsing
        xml.etree.ElementTree.fromstring(raw_bytes)  # noqa: S314
    except Exception as err:
        raise PDFToolsError(
            f"Invalid XMP XML file: {err}",
            code="E_XML_INVALID",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint="Ensure the XMP file is well-formed UTF-8 XML.",
        ) from err


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

    def set_metadata(
        self,
        input_path: Path,
        output_path: Path,
        set_items: list[tuple[str, str]] | None = None,
        xmp_file: Path | None = None,
        source: str = "both",
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Modify document metadata fields or replace XMP packet."""
        out_res = output_path.resolve()
        assert_distinct_files(input_path, out_res, operation_name="metadata set")

        source_clean = source.strip().lower()
        if source_clean not in ("both", "info", "xmp"):
            raise PDFToolsError(
                f"Invalid --source '{source}'. Allowed: both, info, xmp.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if xmp_file is not None and set_items:
            raise PDFToolsError(
                "Cannot specify both --set and --xmp-file.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )
        if xmp_file is None and not set_items:
            raise PDFToolsError(
                "Must provide at least one --set KEY=VALUE or --xmp-file.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )
        if xmp_file is not None and source_clean == "info":
            raise PDFToolsError(
                "--xmp-file cannot be used with --source info.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if out_res.exists() and not overwrite:
            raise FileSafetyError(
                f"Destination file '{out_res}' already exists.",
                code="E_OUTPUT_EXISTS",
                hint="Use --overwrite to allow replacing existing files.",
            )

        # Validate set_items keys
        parsed_fields: dict[str, str] = {}
        if set_items:
            seen_keys: set[str] = set()
            for k, v in set_items:
                clean_k = k.strip().lower()
                if clean_k not in STANDARD_METADATA_KEYS:
                    allowed = ", ".join(STANDARD_METADATA_KEYS.keys())
                    raise PDFToolsError(
                        f"Unknown metadata key '{k}'. Allowed: {allowed}.",
                        code="E_CLI_INVALID_OPTION",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    )
                if clean_k in seen_keys:
                    raise PDFToolsError(
                        f"Duplicate metadata key '{k}' provided.",
                        code="E_CLI_INVALID_OPTION",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    )
                seen_keys.add(clean_k)
                parsed_fields[clean_k] = v

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf

            if xmp_file is not None:
                if not xmp_file.is_file():
                    raise PDFToolsError(
                        f"XMP file not found: '{xmp_file}'.",
                        code="E_IO_NOT_FOUND",
                        exit_code=ExitCode.IO_ERROR,
                    )
                xmp_bytes = xmp_file.read_bytes()
                validate_xmp_xml(xmp_bytes)
                pdf.Root.Metadata = pdf.make_stream(xmp_bytes)
                pdf.Root.Metadata["/Type"] = pikepdf.Name("/Metadata")
                pdf.Root.Metadata["/Subtype"] = pikepdf.Name("/XML")
            else:
                # Update Info dictionary
                if source_clean in ("both", "info"):
                    for clean_k, val in parsed_fields.items():
                        info_key, _ = STANDARD_METADATA_KEYS[clean_k]
                        if clean_k in ("creation-date", "modification-date"):
                            pdf.docinfo[info_key] = rfc3339_to_pdf_date(val)
                        else:
                            pdf.docinfo[info_key] = val

                # Update XMP metadata
                if source_clean in ("both", "xmp"):
                    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
                        for clean_k, val in parsed_fields.items():
                            _, xmp_key = STANDARD_METADATA_KEYS[clean_k]
                            if clean_k == "author":
                                meta[xmp_key] = [val]
                            else:
                                meta[xmp_key] = val

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="meta-set-", suffix=".pdf")
                pdf.save(scratch, fix_metadata_version=False)
                AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "input": str(input_path.resolve()),
            "output": str(out_res),
            "source": source_clean,
            "fields_set": parsed_fields,
            "xmp_replaced": xmp_file is not None,
        }

    def remove_metadata(
        self,
        input_path: Path,
        output_path: Path,
        keys: list[str] | None = None,
        all_metadata: bool = False,
        source: str = "both",
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Delete specific metadata keys or all document metadata containers."""
        out_res = output_path.resolve()
        assert_distinct_files(input_path, out_res, operation_name="metadata remove")

        source_clean = source.strip().lower()
        if source_clean not in ("both", "info", "xmp"):
            raise PDFToolsError(
                f"Invalid --source '{source}'. Allowed: both, info, xmp.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if all_metadata and keys:
            raise PDFToolsError(
                "Cannot specify both --key and --all.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )
        if not all_metadata and not keys:
            raise PDFToolsError(
                "Must specify either --key or --all.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if out_res.exists() and not overwrite:
            raise FileSafetyError(
                f"Destination file '{out_res}' already exists.",
                code="E_OUTPUT_EXISTS",
                hint="Use --overwrite to allow replacing existing files.",
            )

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf

            if all_metadata:
                if source_clean in ("both", "info"):
                    for k in list(pdf.docinfo.keys()):
                        del pdf.docinfo[k]
                    if "/Info" in pdf.trailer:
                        del pdf.trailer["/Info"]
                if source_clean in ("both", "xmp") and "/Metadata" in pdf.Root:
                    del pdf.Root["/Metadata"]
            else:
                if keys is None:
                    keys = []
                clean_keys = []
                for k in keys:
                    ck = k.strip().lower()
                    if ck not in STANDARD_METADATA_KEYS:
                        allowed = ", ".join(STANDARD_METADATA_KEYS.keys())
                        raise PDFToolsError(
                            f"Unknown metadata key '{k}'. Allowed: {allowed}.",
                            code="E_CLI_INVALID_OPTION",
                            exit_code=ExitCode.USAGE_OR_SELECTION,
                        )
                    clean_keys.append(ck)

                if source_clean in ("both", "info"):
                    for ck in clean_keys:
                        info_k, _ = STANDARD_METADATA_KEYS[ck]
                        if info_k in pdf.docinfo:
                            del pdf.docinfo[info_k]

                if source_clean in ("both", "xmp") and "/Metadata" in pdf.Root:
                    with (
                        contextlib.suppress(Exception),
                        pdf.open_metadata(set_pikepdf_as_editor=False) as meta,
                    ):
                        for ck in clean_keys:
                            _, xmp_k = STANDARD_METADATA_KEYS[ck]
                            if xmp_k in meta:
                                del meta[xmp_k]

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="meta-rem-", suffix=".pdf")
                pdf.save(scratch, fix_metadata_version=False)
                AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "input": str(input_path.resolve()),
            "output": str(out_res),
            "source": source_clean,
            "all_removed": all_metadata,
            "keys_removed": keys or [],
        }

    def sanitize_metadata(
        self,
        input_path: Path,
        output_path: Path,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Perform deep recursive metadata sanitization and full file rewrite."""
        out_res = output_path.resolve()
        assert_distinct_files(input_path, out_res, operation_name="metadata sanitize")

        if out_res.exists() and not overwrite:
            raise FileSafetyError(
                f"Destination file '{out_res}' already exists.",
                code="E_OUTPUT_EXISTS",
                hint="Use --overwrite to allow replacing existing files.",
            )

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf

            # 1. Clear Info dictionary and trailer reference
            for k in list(pdf.docinfo.keys()):
                del pdf.docinfo[k]
            if "/Info" in pdf.trailer:
                del pdf.trailer["/Info"]

            # 2. Remove Catalog XMP
            had_catalog_xmp = "/Metadata" in pdf.Root
            if had_catalog_xmp:
                del pdf.Root["/Metadata"]

            # 3. Bounded traversal of indirect objects to delete object-level /Metadata streams
            removed_object_streams = 0
            for obj in list(pdf.objects):
                with contextlib.suppress(Exception):
                    if isinstance(obj, (pikepdf.Dictionary, pikepdf.Stream)) and "/Metadata" in obj:
                        del obj["/Metadata"]
                        removed_object_streams += 1

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="meta-san-", suffix=".pdf")
                # Full rewrite destroys historical incremental revisions
                pdf.save(scratch, fix_metadata_version=False)
                AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "input": str(input_path.resolve()),
            "output": str(out_res),
            "info_removed": True,
            "catalog_xmp_removed": had_catalog_xmp,
            "object_metadata_streams_removed": removed_object_streams,
        }
