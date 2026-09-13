"""Lossless PDF stream and object optimization service conforming to PLAN.md §12.4 C20 (CMD-005)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pikepdf

from pdftoolscli.backends.pikepdf_backend import PikepdfBackend
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import assert_distinct_files
from pdftoolscli.storage.workspace import InvocationWorkspace


class OptimizationService:
    """Service providing lossless stream and object optimization."""

    def __init__(self, backend: PikepdfBackend | None = None) -> None:
        self.backend = backend or PikepdfBackend()

    def optimize(
        self,
        input_path: Path,
        output_path: Path,
        object_streams: str = "preserve",
        linearize: bool = False,
        keep_larger: bool = False,
        password: str | None = None,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Perform lossless stream recompression and serialization tuning."""
        assert_distinct_files(input_path, output_path, operation_name="optimize")

        mode_str = object_streams.lower().strip()
        if mode_str == "preserve":
            obj_mode = pikepdf.ObjectStreamMode.preserve
        elif mode_str == "generate":
            obj_mode = pikepdf.ObjectStreamMode.generate
        elif mode_str == "disable":
            obj_mode = pikepdf.ObjectStreamMode.disable
        else:
            raise PDFToolsError(
                f"Invalid --object-streams '{object_streams}' (preserve, generate, disable).",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        original_size = input_path.stat().st_size

        with (
            self.backend.open_document(input_path, password=password) as handle,
            InvocationWorkspace() as ws,
        ):
            scratch = ws.create_scratch_file(prefix="opt-", suffix=".pdf")

            # Recompress eligible streams, recompress flate, adjust object streams
            handle.pdf.save(
                scratch,
                compress_streams=True,
                recompress_flate=True,
                object_stream_mode=obj_mode,
                linearize=linearize,
            )

            candidate_size = scratch.stat().st_size
            rep_changed = linearize or (mode_str != "preserve")

            if candidate_size >= original_size and not keep_larger and not rep_changed:
                # If candidate is not smaller and no representation change mandated,
                # publish a byte-copy of the original
                shutil.copyfile(input_path, scratch)
                final_size = original_size
                changed = False
                delta_bytes = 0
            else:
                final_size = candidate_size
                changed = True
                delta_bytes = candidate_size - original_size

            published = AtomicPublisher.publish_file(scratch, output_path, overwrite=overwrite)

        savings_pct = (
            round(((original_size - final_size) / original_size) * 100, 2)
            if original_size > 0
            else 0.0
        )

        return {
            "command": "optimize",
            "input": str(input_path.resolve()),
            "output": str(published.resolve()),
            "original_size_bytes": original_size,
            "output_size_bytes": final_size,
            "delta_bytes": delta_bytes,
            "savings_percent": savings_pct,
            "changed": changed,
            "linearized": linearize,
            "object_streams": mode_str,
        }
