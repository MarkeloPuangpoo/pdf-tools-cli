"""Document inspection service conforming to PLAN.md §12.2 (CMD-001)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.domain.errors import (
    PDFEncryptedError,
    PDFInvalidError,
)


class InspectService:
    """Provides document structure, geometry, security, and catalog inspection."""

    def __init__(self, backend: PikepdfBackend | None = None) -> None:
        self.backend = backend or PikepdfBackend()

    def inspect(
        self,
        path: Path,
        password: str | None = None,
        detail: str = "basic",
        section: str | None = None,
    ) -> dict[str, Any]:
        """Inspect a PDF document, returning detailed or basic catalog metrics.

        If document is encrypted and no password was supplied, returns partial
        header/encryption information with locked=True.
        """
        if not path.is_file():
            raise PDFInvalidError(f"PDF file not found: {path}")

        file_size = path.stat().st_size

        try:
            with self.backend.open_document(path, password=password) as handle:
                info = self.backend.get_document_info(handle)

                # Page summaries
                pages_data: list[dict[str, Any]] = []
                for p_idx in range(info.page_count):
                    p_info = self.backend.get_page_info(handle, p_idx)
                    pages_data.append(
                        {
                            "page": p_info.page_number,
                            "mediabox": [
                                p_info.mediabox.x0,
                                p_info.mediabox.y0,
                                p_info.mediabox.x1,
                                p_info.mediabox.y1,
                            ],
                            "cropbox": [
                                p_info.cropbox.x0,
                                p_info.cropbox.y0,
                                p_info.cropbox.x1,
                                p_info.cropbox.y1,
                            ],
                            "rotation": p_info.rotation,
                        }
                    )

                result: dict[str, Any] = {
                    "filename": path.name,
                    "path": str(path.resolve()),
                    "file_size_bytes": file_size,
                    "pdf_version": info.pdf_version,
                    "page_count": info.page_count,
                    "is_encrypted": info.is_encrypted,
                    "encryption_algorithm": info.encryption_algorithm,
                    "is_linearized": info.is_linearized,
                    "has_signatures": info.has_signatures,
                    "has_acroforms": info.has_acroforms,
                    "is_tagged": info.is_tagged,
                    "locked": False,
                    "metadata": info.metadata,
                    "pages": pages_data,
                }

                if detail == "all":
                    pdf = handle.pdf
                    fonts_set: set[str] = set()
                    image_count = 0

                    for page in pdf.pages:
                        res: Any = page.get("/Resources", {})
                        # Font extraction
                        if "/Font" in res:
                            for font_name in res["/Font"]:
                                fonts_set.add(str(font_name).lstrip("/"))
                        # Image count
                        if "/XObject" in res:
                            xobj_dict: Any = res["/XObject"]
                            for x_key in xobj_dict:
                                with contextlib.suppress(Exception):
                                    if xobj_dict[x_key].get("/Subtype") == "/Image":
                                        image_count += 1

                    # Outlines
                    outlines = self.backend.get_outlines(handle)
                    outlines_data = [{"title": o.title, "page": o.page_number} for o in outlines]

                    result["fonts"] = sorted(fonts_set)
                    result["image_count"] = image_count
                    result["outlines"] = outlines_data

                if section:
                    sec = section.lower()
                    if sec in result:
                        return {sec: result[sec]}

                return result

        except PDFEncryptedError as enc_err:
            if password:
                # Password was passed but invalid
                raise enc_err

            # Password was missing: extract partial unencrypted header info
            version_str = "Unknown"
            with open(path, "rb") as f:
                header = f.read(1024)
                if b"%PDF-" in header:
                    with contextlib.suppress(Exception):
                        pos = header.find(b"%PDF-")
                        version_str = header[pos + 5 : pos + 8].decode("ascii", errors="ignore")

            partial: dict[str, Any] = {
                "filename": path.name,
                "path": str(path.resolve()),
                "file_size_bytes": file_size,
                "pdf_version": version_str,
                "page_count": None,
                "is_encrypted": True,
                "encryption_algorithm": "Unknown (Password required)",
                "is_linearized": False,
                "has_signatures": False,
                "has_acroforms": False,
                "is_tagged": False,
                "locked": True,
                "metadata": {},
                "pages": [],
            }
            if section:
                sec = section.lower()
                if sec in partial:
                    return {sec: partial[sec]}
            return partial
