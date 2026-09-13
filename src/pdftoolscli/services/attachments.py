"""Document attachments management service conforming to PLAN.md §12.7 C45-C48 (CMD-015)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import pikepdf

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.domain.errors import ExitCode, FileSafetyError, PDFToolsError
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace


def sanitize_attachment_filename(raw_name: str) -> str:
    """Sanitize raw attachment filename to strictly prevent path traversal.

    Neutralizes ../, ..\\, absolute paths, slashes, null bytes, and non-printable characters.
    """
    clean = raw_name.replace("\\", "/").strip()
    name = Path(clean).name
    # Strip null bytes and non-printable characters
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    # Replace dangerous characters with underscore
    name = re.sub(r"[^a-zA-Z0-9_.-]", "_", name)
    # Strip leading dots to prevent hidden/relative traversal names
    name = name.lstrip(".")
    if not name:
        name = "attachment"
    return name


class AttachmentsService:
    """Service for listing, extracting, adding, and removing PDF document attachments."""

    def __init__(self, backend: PikepdfBackend | None = None) -> None:
        self.backend = backend or PikepdfBackend()

    def list_attachments(
        self,
        input_path: Path,
        password: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all catalog embedded files and file-attachment annotations."""
        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            items: list[dict[str, Any]] = []
            index = 1
            seen_stream_objgens: set[tuple[int, int]] = set()

            # 1. Catalog NameTree (/Names /EmbeddedFiles) via pdf.attachments
            for name, att_spec in pdf.attachments.items():
                try:
                    att_file = att_spec.get_file()
                    data = att_file.read_bytes()
                    size = att_file.size or len(data)
                    mime = att_file.mime_type or "application/octet-stream"
                    sha256 = hashlib.sha256(data).hexdigest()
                    desc = att_spec.description or None
                    stream_objgen = getattr(att_file.obj, "objgen", (0, 0))
                    if stream_objgen[0] != 0:
                        seen_stream_objgens.add(stream_objgen)
                except Exception:
                    size = 0
                    mime = "application/octet-stream"
                    sha256 = None
                    desc = None

                items.append(
                    {
                        "id": f"att-{index:04d}",
                        "name": name,
                        "size": size,
                        "mime": mime,
                        "relation": "EmbeddedFiles",
                        "description": desc,
                        "sha256": sha256,
                    }
                )
                index += 1

            # 2. Page-level /Subtype /FileAttachment annotations
            for page_num, page in enumerate(pdf.pages, start=1):
                if "/Annots" not in page or not isinstance(page.Annots, pikepdf.Array):
                    continue

                for annot in page.Annots:
                    if not isinstance(annot, (pikepdf.Dictionary, pikepdf.Stream)):
                        continue
                    if annot.get("/Subtype") != pikepdf.Name.FileAttachment:
                        continue

                    fs = annot.get("/FS")
                    if fs is None or not isinstance(fs, pikepdf.Dictionary):
                        continue

                    raw_name = str(fs.get("/UF", fs.get("/F", "attachment")))
                    desc = str(annot.get("/Contents", fs.get("/Desc", ""))) or None

                    # Extract stream data if present
                    ef = fs.get("/EF")
                    stream = None
                    if isinstance(ef, pikepdf.Dictionary):
                        stream = ef.get("/UF", ef.get("/F"))

                    stream_og = getattr(stream, "objgen", (0, 0))
                    if stream_og[0] != 0 and stream_og in seen_stream_objgens:
                        continue
                    if stream_og[0] != 0:
                        seen_stream_objgens.add(stream_og)

                    size = 0
                    sha256 = None
                    mime = "application/octet-stream"
                    if isinstance(stream, pikepdf.Stream):
                        with contextlib.suppress(Exception):
                            data = stream.read_bytes()
                            size = len(data)
                            sha256 = hashlib.sha256(data).hexdigest()
                            if "/Subtype" in stream:
                                mime = str(stream["/Subtype"]).lstrip("/")

                    items.append(
                        {
                            "id": f"att-{index:04d}",
                            "name": raw_name,
                            "size": size,
                            "mime": mime,
                            "relation": f"FileAttachment (page {page_num})",
                            "description": desc,
                            "sha256": sha256,
                        }
                    )
                    index += 1

            return items

    def extract_attachments(
        self,
        input_path: Path,
        output_dir: Path,
        ids: list[str] | None = None,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Extract attachments to directory with sanitized names and mode 0600."""
        output_dir.mkdir(parents=True, exist_ok=True)
        all_items = self.list_attachments(input_path, password=password)

        if ids:
            known_ids = {item["id"] for item in all_items}
            unmatched = set(ids) - known_ids
            if unmatched:
                missing_str = ", ".join(sorted(unmatched))
                raise PDFToolsError(
                    f"Attachment ID(s) not found: {missing_str}.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )
            target_items = [it for it in all_items if it["id"] in ids]
        else:
            target_items = all_items

        extracted_manifest: list[dict[str, Any]] = []

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            index = 1

            # Extract from pdf.attachments
            for name, att_spec in pdf.attachments.items():
                att_id = f"att-{index:04d}"
                index += 1

                matching_target = next((t for t in target_items if t["id"] == att_id), None)
                if not matching_target:
                    continue

                att_file = att_spec.get_file()
                data = att_file.read_bytes()
                safe_name = sanitize_attachment_filename(name)
                dest_filename = f"attachment-{index - 1:04d}-{safe_name}"
                dest_path = output_dir / dest_filename

                if dest_path.exists() and not overwrite:
                    raise FileSafetyError(
                        f"Extracted attachment file '{dest_path}' already exists.",
                        code="E_OUTPUT_EXISTS",
                        hint="Use --overwrite to allow replacing existing files.",
                    )

                dest_path.write_bytes(data)
                # Ensure extracted files are non-executable (read/write by owner only)
                os.chmod(dest_path, 0o600)

                sha256_hash = hashlib.sha256(data).hexdigest()
                extracted_manifest.append(
                    {
                        "id": att_id,
                        "original_name": name,
                        "extracted_name": dest_filename,
                        "path": str(dest_path.resolve()),
                        "size": len(data),
                        "sha256": sha256_hash,
                        "mime": att_file.mime_type or "application/octet-stream",
                    }
                )

            # Extract from page annotations
            for page in pdf.pages:
                if "/Annots" not in page or not isinstance(page.Annots, pikepdf.Array):
                    continue

                for annot in page.Annots:
                    if not isinstance(annot, (pikepdf.Dictionary, pikepdf.Stream)):
                        continue
                    if annot.get("/Subtype") != pikepdf.Name.FileAttachment:
                        continue

                    fs = annot.get("/FS")
                    if fs is None or not isinstance(fs, pikepdf.Dictionary):
                        continue

                    att_id = f"att-{index:04d}"
                    index += 1

                    matching_target = next((t for t in target_items if t["id"] == att_id), None)
                    if not matching_target:
                        continue

                    raw_name = str(fs.get("/UF", fs.get("/F", "attachment")))
                    ef = fs.get("/EF")
                    stream = None
                    if isinstance(ef, pikepdf.Dictionary):
                        stream = ef.get("/UF", ef.get("/F"))

                    data = stream.read_bytes() if isinstance(stream, pikepdf.Stream) else b""
                    safe_name = sanitize_attachment_filename(raw_name)
                    dest_filename = f"attachment-{index - 1:04d}-{safe_name}"
                    dest_path = output_dir / dest_filename

                    if dest_path.exists() and not overwrite:
                        raise FileSafetyError(
                            f"Extracted attachment file '{dest_path}' already exists.",
                            code="E_OUTPUT_EXISTS",
                            hint="Use --overwrite to allow replacing existing files.",
                        )

                    dest_path.write_bytes(data)
                    os.chmod(dest_path, 0o600)

                    sha256_hash = hashlib.sha256(data).hexdigest()
                    extracted_manifest.append(
                        {
                            "id": att_id,
                            "original_name": raw_name,
                            "extracted_name": dest_filename,
                            "path": str(dest_path.resolve()),
                            "size": len(data),
                            "sha256": sha256_hash,
                            "mime": "application/octet-stream",
                        }
                    )

        # Write manifest.json inside output directory
        manifest_path = output_dir / "manifest.json"
        manifest_data = {
            "source": str(input_path.resolve()),
            "extracted_count": len(extracted_manifest),
            "attachments": extracted_manifest,
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
        os.chmod(manifest_path, 0o600)

        return {
            "input": str(input_path.resolve()),
            "output_dir": str(output_dir.resolve()),
            "manifest_file": str(manifest_path.resolve()),
            "extracted_count": len(extracted_manifest),
            "attachments": extracted_manifest,
        }

    def add_attachments(
        self,
        input_path: Path,
        files: list[Path],
        output_path: Path,
        description: str | None = None,
        replace_name: str | None = None,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Attach local files to document catalog /Names /EmbeddedFiles."""
        out_res = output_path.resolve()
        assert_distinct_files(input_path, out_res, operation_name="attachments add")

        if out_res.exists() and not overwrite:
            raise FileSafetyError(
                f"Destination file '{out_res}' already exists.",
                code="E_OUTPUT_EXISTS",
                hint="Use --overwrite to allow replacing existing files.",
            )

        if not files:
            raise PDFToolsError(
                "At least one file must be specified to attach.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        if replace_name is not None and len(files) != 1:
            raise PDFToolsError(
                "--replace-name requires exactly one incoming file.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        # Validate incoming files
        for f in files:
            if f.is_symlink() or f.is_dir() or not f.is_file():
                raise PDFToolsError(
                    f"Attachment candidate '{f}' is not a regular file (symlinks/dirs rejected).",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf

            if replace_name is not None:
                if replace_name not in pdf.attachments:
                    raise PDFToolsError(
                        f"Attachment '{replace_name}' to replace was not found in document.",
                        code="E_CLI_INVALID_OPTION",
                        exit_code=ExitCode.USAGE_OR_SELECTION,
                    )
                # Delete existing before replacing
                del pdf.attachments[replace_name]
                incoming = files[0]
                spec = pikepdf.AttachedFileSpec.from_filepath(
                    pdf, incoming, description=description or ""
                )
                pdf.attachments[replace_name] = spec
                added_names = [replace_name]
            else:
                added_names = []
                for incoming in files:
                    name = incoming.name
                    if name in pdf.attachments:
                        raise PDFToolsError(
                            f"Attachment '{name}' already exists in document. "
                            "Use --replace-name to replace.",
                            code="E_CLI_INVALID_OPTION",
                            exit_code=ExitCode.USAGE_OR_SELECTION,
                        )
                    spec = pikepdf.AttachedFileSpec.from_filepath(
                        pdf, incoming, description=description or ""
                    )
                    pdf.attachments[name] = spec
                    added_names.append(name)

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="att-add-", suffix=".pdf")
                pdf.save(scratch)
                AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "input": str(input_path.resolve()),
            "output": str(out_res),
            "added_count": len(added_names),
            "attachments_added": added_names,
        }

    def remove_attachments(
        self,
        input_path: Path,
        output_path: Path,
        all_attachments: bool = False,
        names: list[str] | None = None,
        ids: list[str] | None = None,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Remove matching embedded files and file-attachment annotations."""
        out_res = output_path.resolve()
        assert_distinct_files(input_path, out_res, operation_name="attachments remove")

        if out_res.exists() and not overwrite:
            raise FileSafetyError(
                f"Destination file '{out_res}' already exists.",
                code="E_OUTPUT_EXISTS",
                hint="Use --overwrite to allow replacing existing files.",
            )

        active = sum([bool(all_attachments), bool(names), bool(ids)])
        if active != 1:
            raise PDFToolsError(
                "Exactly one of --all, --name, or --id must be specified.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        all_items = self.list_attachments(input_path, password=password)

        if ids:
            known_ids = {it["id"] for it in all_items}
            unmatched = set(ids) - known_ids
            if unmatched:
                missing_str = ", ".join(sorted(unmatched))
                raise PDFToolsError(
                    f"Attachment ID(s) not found: {missing_str}.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )
            target_names = {it["name"] for it in all_items if it["id"] in ids}
        elif names:
            known_names = {it["name"] for it in all_items}
            unmatched = set(names) - known_names
            if unmatched:
                missing_str = ", ".join(sorted(unmatched))
                raise PDFToolsError(
                    f"Attachment name(s) not found: {missing_str}.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )
            target_names = set(names)
        else:
            target_names = set()

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            removed_names: list[str] = []

            # 1. Remove from pdf.attachments
            for att_name in list(pdf.attachments.keys()):
                if all_attachments or att_name in target_names:
                    del pdf.attachments[att_name]
                    removed_names.append(att_name)

            # 2. Remove matching /Subtype /FileAttachment annotations from pages
            for page in pdf.pages:
                if "/Annots" not in page or not isinstance(page.Annots, pikepdf.Array):
                    continue

                surviving = []
                for annot in page.Annots:
                    if (
                        isinstance(annot, (pikepdf.Dictionary, pikepdf.Stream))
                        and annot.get("/Subtype") == pikepdf.Name.FileAttachment
                    ):
                        fs = annot.get("/FS")
                        fn = (
                            str(fs.get("/UF", fs.get("/F", "")))
                            if isinstance(fs, pikepdf.Dictionary)
                            else ""
                        )
                        if all_attachments or fn in target_names:
                            removed_names.append(fn or "unnamed-attachment")
                            continue
                    surviving.append(annot)

                if len(surviving) < len(page.Annots):
                    if surviving:
                        page.Annots = pdf.make_indirect(pikepdf.Array(surviving))
                    else:
                        del page["/Annots"]

            with InvocationWorkspace() as ws:
                scratch = ws.create_scratch_file(prefix="att-rem-", suffix=".pdf")
                pdf.save(scratch)
                AtomicPublisher.publish_file(scratch, out_res, overwrite=overwrite)

        return {
            "input": str(input_path.resolve()),
            "output": str(out_res),
            "removed_count": len(removed_names),
            "attachments_removed": removed_names,
        }
