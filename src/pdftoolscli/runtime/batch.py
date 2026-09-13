"""Batch Execution Engine, multi-file dispatcher, and concurrency supervisor.

Conforms to PLAN.md §29, §30.
"""

from __future__ import annotations

import concurrent.futures
import contextlib
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pdftoolscli.domain.errors import (
    BatchError,
    ExitCode,
    PDFToolsError,
    UsageError,
)
from pdftoolscli.presentation.json import render_json_bytes
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import (
    FileIdentity,
    assert_distinct_files,
    get_file_identity,
    sniff_file_format,
)
from pdftoolscli.storage.naming import (
    CollisionTracker,
    assert_not_nested,
    default_batch_output_name,
    render_template,
)


@dataclass(frozen=True)
class BatchItemResult:
    """Outcome of a single item processed within a batch."""

    input_path: str
    output_path: str | None
    status: str  # "success" | "failure" | "skipped" | "planned"
    exit_code: int = 0
    error: dict[str, Any] | None = None
    elapsed_ms: int = 0
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_path": self.input_path,
            "output_path": self.output_path,
            "status": self.status,
            "exit_code": self.exit_code,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "details": self.details,
        }


@dataclass
class BatchSummaryReport:
    """Summary of batch execution across all planned items."""

    total: int
    succeeded: int
    failed: int
    skipped: int
    elapsed_ms: int
    items: list[BatchItemResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "skipped": self.skipped,
            "elapsed_ms": self.elapsed_ms,
            "items": [item.to_dict() for item in self.items],
        }


def collect_batch_inputs(
    inputs: Sequence[str | Path] = (),
    *,
    globs: Sequence[str] = (),
    recursive: bool = False,
    input_root: Path | None = None,
) -> list[Path]:
    """Collect, deduplicate, and deterministically sort batch input PDF files.

    Conforms to PLAN.md §29:
    - Explicit file arguments preserve order.
    - Directories and glob matches sort by normalized relative path.
    - Deduplicate identical files via FileIdentity while retaining first occurrence.
    - Exclude hidden directories (.*) by default.
    - Do not follow symlinks/reparse points.
    - Verify PDF format.
    """
    visited_identities: set[FileIdentity] = set()
    collected_files: list[Path] = []

    def _add_file(path: Path) -> None:
        p = path.resolve()
        if not p.is_file():
            return
        # Ensure it's a PDF file
        if p.suffix.lower() == ".pdf" or sniff_file_format(p) == "pdf":
            try:
                ident = get_file_identity(p)
                if ident in visited_identities:
                    return
                visited_identities.add(ident)
            except OSError:
                pass
            collected_files.append(p)

    # 1. Process explicit inputs
    for raw_inp in inputs:
        inp_p = Path(raw_inp)
        if not inp_p.exists():
            raise UsageError(
                f"Batch input path not found: {raw_inp}",
                hint="Verify that the path exists and is readable.",
            )

        if inp_p.is_file():
            _add_file(inp_p)
        elif inp_p.is_dir():
            dir_files: list[Path] = []
            if recursive:
                for root, dirs, files in os.walk(inp_p, followlinks=False):
                    # Exclude hidden directories in-place
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for f in files:
                        if not f.startswith("."):
                            dir_files.append(Path(root) / f)
            else:
                for entry in inp_p.iterdir():
                    if not entry.name.startswith(".") and entry.is_file():
                        dir_files.append(entry)

            # Sort directory matches deterministically by normalized relative path
            dir_files.sort(key=lambda p: str(p.relative_to(inp_p)).casefold())
            for df in dir_files:
                _add_file(df)

    # 2. Process glob patterns
    if globs:
        search_root = (input_root or Path.cwd()).resolve()
        for pattern in globs:
            if "**" in pattern and not recursive:
                raise UsageError(
                    f"Recursive glob pattern '{pattern}' requires '--recursive' flag.",
                    code="E_USAGE",
                    hint="Add '--recursive' or use a non-recursive pattern.",
                )

            matched: list[Path] = []
            try:
                for matched_p in search_root.glob(pattern):
                    rel_parts = matched_p.relative_to(search_root).parts
                    # Exclude hidden files or directories
                    if any(part.startswith(".") for part in rel_parts):
                        continue
                    if matched_p.is_file():
                        matched.append(matched_p)
            except Exception as e:
                raise UsageError(
                    f"Invalid glob pattern '{pattern}': {e}",
                    code="E_USAGE",
                ) from e

            if not matched:
                raise UsageError(
                    f"Glob pattern '{pattern}' did not match any files.",
                    code="E_USAGE",
                    hint="Check glob pattern syntax or input root directory.",
                )

            matched.sort(key=lambda p: str(p.relative_to(search_root)).casefold())
            for mf in matched:
                _add_file(mf)

    if not collected_files:
        raise UsageError(
            "No valid PDF files found for batch processing.",
            hint="Check that input paths, directories, or glob patterns contain valid .pdf files.",
        )

    return collected_files


def plan_batch_destinations(
    input_files: Sequence[Path],
    *,
    output_dir: Path | None,
    input_root: Path | None = None,
    operation_name: str,
    output_ext: str = ".pdf",
    template: str | None = None,
) -> list[tuple[Path, Path | None]]:
    """Plan destination paths for batch processing with collision detection and safety verification.

    Conforms to PLAN.md §29:
    - Multiple W inputs require output_dir.
    - Preserve structure relative to input_root when provided.
    - Output directory cannot be inside input tree and vice versa.
    - Check for naming collisions preflight using CollisionTracker.
    """
    if output_dir is None:
        # Read-only operations produce no file outputs
        return [(inp, None) for inp in input_files]

    out_root = Path(output_dir).resolve()
    if input_root is not None:
        in_root = Path(input_root).resolve()
        assert_not_nested(in_root, out_root)
    else:
        in_root = None

    tracker = CollisionTracker()
    planned: list[tuple[Path, Path | None]] = []

    for idx, inp in enumerate(input_files, start=1):
        relparent = ""
        if in_root is not None:
            try:
                rel_p = inp.resolve().relative_to(in_root)
                relparent = str(rel_p.parent) if rel_p.parent != Path(".") else ""
            except ValueError:
                relparent = ""

        if template is not None:
            filename = render_template(
                template,
                stem=inp.stem,
                index=idx,
                ext=output_ext.lstrip("."),
                relparent=relparent,
            )
            dest = out_root / filename
        else:
            filename = default_batch_output_name(inp.stem, operation_name, ext=output_ext)
            dest = out_root / relparent / filename if relparent else out_root / filename

        # Safety check: input != output

        assert_distinct_files(inp, dest, operation_name=operation_name)
        # Collision check across batch planned items
        tracker.register(dest)
        planned.append((inp, dest))

    return planned


def _run_single_item(
    worker_fn: Callable[..., dict[str, Any] | None],
    input_path: Path,
    output_path: Path | None,
    kwargs: dict[str, Any],
) -> BatchItemResult:
    """Execute a single batch item and capture timing and error results."""
    t0 = time.monotonic()
    in_str = str(input_path)
    out_str = str(output_path) if output_path else None

    # Ensure parent directory of output exists if output_path is defined
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if output_path is not None:
            res = worker_fn(input_path, output_path, **kwargs)
        else:
            res = worker_fn(input_path, **kwargs)

        elapsed = int((time.monotonic() - t0) * 1000)
        return BatchItemResult(
            input_path=in_str,
            output_path=out_str,
            status="success",
            exit_code=0,
            elapsed_ms=elapsed,
            details=res,
        )
    except PDFToolsError as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        return BatchItemResult(
            input_path=in_str,
            output_path=out_str,
            status="failure",
            exit_code=int(e.exit_code),
            error=e.as_detail().to_dict(),
            elapsed_ms=elapsed,
        )
    except Exception as e:
        elapsed = int((time.monotonic() - t0) * 1000)
        return BatchItemResult(
            input_path=in_str,
            output_path=out_str,
            status="failure",
            exit_code=int(ExitCode.INTERNAL_ERROR),
            error={
                "code": "E_INTERNAL",
                "category": "internal",
                "message": str(e),
            },
            elapsed_ms=elapsed,
        )


class BatchEngine:
    """Concurrently executes typed operations across multiple documents."""

    def __init__(
        self,
        jobs: int = 1,
        fail_fast: bool = False,
        dry_run: bool = False,
        report_path: Path | str | None = None,
    ) -> None:
        self.jobs = max(1, jobs)
        self.fail_fast = fail_fast
        self.dry_run = dry_run
        self.report_path = Path(report_path) if report_path else None

    def execute(
        self,
        planned_items: Sequence[tuple[Path, Path | None]],
        worker_fn: Callable[..., dict[str, Any] | None],
        **worker_kwargs: Any,
    ) -> BatchSummaryReport:
        """Execute all planned batch items conforming to PLAN.md §29, §30."""
        t_start = time.monotonic()
        results: list[BatchItemResult] = []

        if self.dry_run:
            for inp, out in planned_items:
                results.append(
                    BatchItemResult(
                        input_path=str(inp),
                        output_path=str(out) if out else None,
                        status="planned",
                        exit_code=0,
                    )
                )
            summary = BatchSummaryReport(
                total=len(results),
                succeeded=0,
                failed=0,
                skipped=0,
                elapsed_ms=int((time.monotonic() - t_start) * 1000),
                items=results,
            )
            self._write_report_if_requested(summary)
            return summary

        # Execution loop
        if self.jobs == 1 or len(planned_items) == 1:
            for idx, (inp, out) in enumerate(planned_items):
                item_res = _run_single_item(worker_fn, inp, out, worker_kwargs)
                results.append(item_res)
                if item_res.status == "failure" and self.fail_fast:
                    # Skip remaining items
                    for rem_inp, rem_out in planned_items[idx + 1 :]:
                        results.append(
                            BatchItemResult(
                                input_path=str(rem_inp),
                                output_path=str(rem_out) if rem_out else None,
                                status="skipped",
                                exit_code=0,
                            )
                        )
                    break
        else:
            # Multi-worker execution via ThreadPoolExecutor for lightweight coordination
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.jobs) as executor:
                future_to_item = {
                    executor.submit(_run_single_item, worker_fn, inp, out, worker_kwargs): (
                        inp,
                        out,
                    )
                    for inp, out in planned_items
                }
                for future in concurrent.futures.as_completed(future_to_item):
                    item_res = future.result()
                    results.append(item_res)
                    if item_res.status == "failure" and self.fail_fast:
                        # Cancel any not-yet-started futures
                        for f in future_to_item:
                            f.cancel()
                        break

            # If fail_fast triggered, ensure count matches planned_items
            completed_inputs = {r.input_path for r in results}
            for inp, out in planned_items:
                if str(inp) not in completed_inputs:
                    results.append(
                        BatchItemResult(
                            input_path=str(inp),
                            output_path=str(out) if out else None,
                            status="skipped",
                            exit_code=0,
                        )
                    )

            # Sort results back into original planned order
            order_map = {str(inp): i for i, (inp, _) in enumerate(planned_items)}
            results.sort(key=lambda r: order_map.get(r.input_path, 999999))

        succeeded = sum(1 for r in results if r.status == "success")
        failed = sum(1 for r in results if r.status == "failure")
        skipped = sum(1 for r in results if r.status == "skipped")
        elapsed_total = int((time.monotonic() - t_start) * 1000)

        summary = BatchSummaryReport(
            total=len(planned_items),
            succeeded=succeeded,
            failed=failed,
            skipped=skipped,
            elapsed_ms=elapsed_total,
            items=results,
        )

        self._write_report_if_requested(summary)

        if failed > 0:
            raise BatchError(
                f"Batch execution finished with {failed} failure(s) out of "
                f"{len(planned_items)} item(s).",
                failed_count=failed,
                details=summary.to_dict(),
            )

        return summary

    def _write_report_if_requested(self, summary: BatchSummaryReport) -> None:
        """Atomically write batch execution report JSON to disk if report_path is configured."""
        if self.report_path is None:
            return

        publisher = AtomicPublisher()
        # Render JSON bytes matching schema v1
        data_bytes = render_json_bytes(
            command="batch",
            status="success" if summary.failed == 0 else "error",
            data=summary.to_dict(),
            elapsed_ms=summary.elapsed_ms,
        )

        # Write to staging file and atomically publish
        staging_dir = self.report_path.parent
        staging_dir.mkdir(parents=True, exist_ok=True)
        temp_file = staging_dir / f".tmp_{self.report_path.name}_{os.getpid()}"
        try:
            with open(temp_file, "wb") as f:
                f.write(data_bytes)
            publisher.publish_file(temp_file, self.report_path, overwrite=True)
        finally:
            if temp_file.exists():
                with contextlib.suppress(OSError):
                    temp_file.unlink()
