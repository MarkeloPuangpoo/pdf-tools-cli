"""Embedded image asset inventory and extraction service conforming to PLAN.md §12.5 (CMD-009)."""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pikepdf
import PIL.Image

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.domain.errors import ExitCode, FileSafetyError, PDFToolsError
from pdftoolscli.domain.ranges import resolve_range
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.naming import sanitize_filename
from pdftoolscli.storage.workspace import InvocationWorkspace


class ImageService:
    """Service providing embedded image inventory and extraction."""

    def __init__(self, backend: PikepdfBackend | None = None) -> None:
        self.backend = backend or PikepdfBackend()

    def list_images(
        self,
        input_path: Path,
        pages_range: str | None = None,
        password: str | None = None,
    ) -> dict[str, Any]:
        """Scan document and list all embedded image XObjects."""
        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            total_pages = len(pdf.pages)
            if pages_range is not None:
                pages_1based = resolve_range(pages_range, total_pages, context="selection")
            else:
                pages_1based = list(range(1, total_pages + 1))

            unique_images: dict[str, dict[str, Any]] = {}
            occurrences: list[dict[str, Any]] = []

            for p_num in pages_1based:
                page = pdf.pages[p_num - 1]
                res = getattr(page, "Resources", None)
                if res is None or not hasattr(res, "XObject"):
                    continue

                xobjects = res.XObject
                for res_name, xobj in xobjects.items():
                    with contextlib.suppress(Exception):
                        if getattr(xobj, "Subtype", None) != pikepdf.Name("/Image"):
                            continue

                        objgen = getattr(xobj, "objgen", None)
                        if objgen is not None:
                            asset_id = f"obj-{objgen[0]}-{objgen[1]}"
                        else:
                            asset_id = f"p{p_num:04d}-{sanitize_filename(str(res_name))}"

                        # Extract metadata
                        w = int(xobj.Width) if hasattr(xobj, "Width") else 0
                        h = int(xobj.Height) if hasattr(xobj, "Height") else 0
                        bpc = (
                            int(xobj.BitsPerComponent)
                            if hasattr(xobj, "BitsPerComponent")
                            else None
                        )

                        cs = None
                        if hasattr(xobj, "ColorSpace"):
                            cs_obj = xobj.ColorSpace
                            cs = (
                                str(cs_obj)
                                if not isinstance(cs_obj, (list, pikepdf.Array))
                                else str(cs_obj[0])
                            )

                        filters: list[str] = []
                        if hasattr(xobj, "Filter"):
                            f_obj = xobj.Filter
                            if isinstance(f_obj, (list, pikepdf.Array)):
                                filters = [str(f) for f in f_obj]
                            else:
                                filters = [str(f_obj)]

                        # Mask relation
                        mask_rel = "none"
                        if hasattr(xobj, "SMask") and xobj.SMask is not None:
                            mask_rel = "smask"
                        elif hasattr(xobj, "Mask") and xobj.Mask is not None:
                            mask_rel = "mask"

                        raw_bytes_len = 0
                        with contextlib.suppress(Exception):
                            raw_bytes_len = len(xobj.read_raw_bytes())

                        occ = {
                            "page": p_num,
                            "resource_name": str(res_name),
                            "asset_id": asset_id,
                            "width": w,
                            "height": h,
                            "colorspace": cs,
                            "filters": filters,
                            "mask_relation": mask_rel,
                        }
                        occurrences.append(occ)

                        if asset_id not in unique_images:
                            unique_images[asset_id] = {
                                "asset_id": asset_id,
                                "object_id": f"{objgen[0]} {objgen[1]}" if objgen else None,
                                "width": w,
                                "height": h,
                                "bits_per_component": bpc,
                                "colorspace": cs,
                                "filters": filters,
                                "encoded_bytes": raw_bytes_len,
                                "mask_relation": mask_rel,
                                "pages": [p_num],
                            }
                        else:
                            if p_num not in unique_images[asset_id]["pages"]:
                                unique_images[asset_id]["pages"].append(p_num)

            return {
                "command": "images list",
                "input": str(input_path.resolve()),
                "total_unique_images": len(unique_images),
                "total_occurrences": len(occurrences),
                "images": list(unique_images.values()),
                "occurrences": occurrences,
            }

    def extract_images(
        self,
        input_path: Path,
        output_dir: Path,
        pages_range: str | None = None,
        mode: str = "original",
        to_format: str = "png",
        quality: int = 85,
        asset_ids: list[str] | None = None,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Extract embedded image assets to directory."""
        clean_mode = mode.lower().strip()
        if clean_mode not in ("original", "decoded"):
            raise PDFToolsError(
                f"Invalid --mode '{mode}'. Allowed values: original, decoded.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        clean_to = to_format.lower().strip().lstrip(".")
        if clean_to not in ("png", "jpeg", "jpg", "webp", "tiff"):
            raise PDFToolsError(
                f"Unsupported format '{to_format}'. Supported: png, jpeg, webp, tiff.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )
        if clean_to == "jpg":
            clean_to = "jpeg"

        out_res = Path(output_dir).resolve()
        assert_distinct_files(input_path, out_res, operation_name="images extract")
        try:
            input_path.resolve().relative_to(out_res)
            msg = f"Input file ({input_path.resolve()}) cannot be inside output dir ({out_res})."
            raise FileSafetyError(
                msg,
                code="E_NESTED_PATH",
                hint="Specify an output directory that does not contain the input file.",
            )
        except ValueError:
            pass

        if out_res.exists() and not overwrite and any(out_res.iterdir()):
            raise FileSafetyError(
                f"Output directory '{output_dir}' already exists and is not empty.",
                code="E_FILE_COLLISION",
                hint="Specify an empty directory or use --overwrite.",
            )

        with self.backend.open_document(input_path, password=password) as handle:
            pdf = handle.pdf
            total_pages = len(pdf.pages)
            if pages_range is not None:
                pages_1based = resolve_range(pages_range, total_pages, context="selection")
            else:
                pages_1based = list(range(1, total_pages + 1))

            target_assets = set(asset_ids) if asset_ids else None

            # Collect streams to extract
            images_to_extract: dict[str, tuple[Any, list[int]]] = {}
            for p_num in pages_1based:
                page = pdf.pages[p_num - 1]
                res = getattr(page, "Resources", None)
                if res is None or not hasattr(res, "XObject"):
                    continue
                for res_name, xobj in res.XObject.items():
                    with contextlib.suppress(Exception):
                        if getattr(xobj, "Subtype", None) != pikepdf.Name("/Image"):
                            continue
                        objgen = getattr(xobj, "objgen", None)
                        asset_id = (
                            f"obj-{objgen[0]}-{objgen[1]}"
                            if objgen
                            else f"p{p_num:04d}-{sanitize_filename(str(res_name))}"
                        )
                        if target_assets is not None and asset_id not in target_assets:
                            continue

                        if asset_id not in images_to_extract:
                            images_to_extract[asset_id] = (xobj, [p_num])
                        else:
                            if p_num not in images_to_extract[asset_id][1]:
                                images_to_extract[asset_id][1].append(p_num)

            with InvocationWorkspace() as ws:
                staging = ws.create_scratch_dir(prefix="img-extract-")
                extracted_manifest: list[dict[str, Any]] = []

                stem = input_path.stem
                for asset_id, (xobj, pages_list) in images_to_extract.items():
                    try:
                        pi = pikepdf.PdfImage(xobj)
                    except Exception as e:
                        raise PDFToolsError(
                            f"Failed to inspect image asset '{asset_id}': {e}",
                            code="E_PDF_INVALID",
                            exit_code=ExitCode.INVALID_DOCUMENT,
                        ) from e

                    file_prefix = str(staging / f"{stem}-{asset_id}")
                    if clean_mode == "original":
                        # Native extraction without transcoding
                        try:
                            saved_path_str = pi.extract_to(fileprefix=file_prefix)
                            saved_path = Path(saved_path_str)
                        except Exception:
                            # Fallback: export decoded png if original container unsupported
                            saved_path = Path(f"{file_prefix}.png")
                            pil_im = pi.as_pil_image()
                            pil_im.save(saved_path, format="PNG")
                            pil_im.close()
                    else:
                        # Decoded conversion via Pillow
                        saved_path = Path(f"{file_prefix}.{clean_to}")
                        pil_im = pi.as_pil_image()
                        if clean_to == "jpeg" and pil_im.mode in ("RGBA", "LA", "P"):
                            # JPEG does not support alpha transparency
                            bg = PIL.Image.new("RGB", pil_im.size, (255, 255, 255))
                            if pil_im.mode == "P":
                                pil_im = pil_im.convert("RGBA")
                            bg.paste(pil_im, mask=pil_im.split()[-1])
                            bg.save(saved_path, format="JPEG", quality=quality)
                            bg.close()
                        elif clean_to in ("jpeg", "webp"):
                            pil_im.save(saved_path, format=clean_to.upper(), quality=quality)
                        else:
                            pil_im.save(saved_path, format=clean_to.upper())
                        pil_im.close()

                    # Calculate SHA-256
                    hasher = hashlib.sha256()
                    with open(saved_path, "rb") as sf:
                        hasher.update(sf.read())
                    file_sha = hasher.hexdigest()

                    extracted_manifest.append(
                        {
                            "asset_id": asset_id,
                            "filename": saved_path.name,
                            "format": saved_path.suffix.lstrip("."),
                            "width": pi.width,
                            "height": pi.height,
                            "colorspace": str(pi.colorspace),
                            "sha256": file_sha,
                            "pages": pages_list,
                        }
                    )

                # Write manifest.json
                manifest_doc = {
                    "document": str(input_path.resolve()),
                    "mode": clean_mode,
                    "total_extracted": len(extracted_manifest),
                    "images": extracted_manifest,
                }
                manifest_path = staging / "manifest.json"
                manifest_path.write_text(json.dumps(manifest_doc, indent=2), encoding="utf-8")

                # Atomically publish to output_dir
                out_res.mkdir(parents=True, exist_ok=True)
                for item in staging.iterdir():
                    dest_file = out_res / item.name
                    if dest_file.exists() and overwrite:
                        if dest_file.is_dir():
                            shutil.rmtree(dest_file)
                        else:
                            dest_file.unlink()
                    shutil.move(str(item), str(dest_file))

            return {
                "command": "images extract",
                "input": str(input_path.resolve()),
                "output_dir": str(out_res),
                "mode": clean_mode,
                "total_extracted": len(extracted_manifest),
                "manifest": str(out_res / "manifest.json"),
            }
