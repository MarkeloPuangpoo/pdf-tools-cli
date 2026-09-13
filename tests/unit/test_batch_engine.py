"""Unit tests for runtime/batch.py conforming to PLAN.md §29, §30."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pikepdf
import pytest

from pdftoolscli.domain.errors import (
    BatchError,
    FileSafetyError,
    PDFToolsError,
    UsageError,
)
from pdftoolscli.runtime.batch import (
    BatchEngine,
    collect_batch_inputs,
    plan_batch_destinations,
)


@pytest.fixture
def sample_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "sample.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(p)
    pdf.close()
    return p


@pytest.fixture
def pdf_tree(tmp_path: Path) -> tuple[Path, list[Path]]:
    root = tmp_path / "pdf_collection"
    root.mkdir()
    sub1 = root / "sub1"
    sub1.mkdir()
    sub2 = root / "sub2"
    sub2.mkdir()

    files: list[Path] = []
    for idx, d in enumerate([root, sub1, sub2], start=1):
        p = d / f"doc_{idx}.pdf"
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.save(p)
        pdf.close()
        files.append(p)

    # Also add a non-pdf file and a hidden file
    (root / "notes.txt").write_text("not a pdf")
    (root / ".hidden.pdf").write_text("%PDF-fake")

    return root, files


def test_collect_batch_inputs_explicit_files(pdf_tree: tuple[Path, list[Path]]) -> None:
    _, files = pdf_tree
    collected = collect_batch_inputs([files[0], files[1]])
    assert len(collected) == 2
    assert collected[0] == files[0].resolve()
    assert collected[1] == files[1].resolve()


def test_collect_batch_inputs_directory_shallow(pdf_tree: tuple[Path, list[Path]]) -> None:
    root, files = pdf_tree
    collected = collect_batch_inputs([root], recursive=False)
    # Only doc_1.pdf is in the root directory (notes.txt, .hidden.pdf, and subdirs ignored)
    assert len(collected) == 1
    assert collected[0] == files[0].resolve()


def test_collect_batch_inputs_directory_recursive(pdf_tree: tuple[Path, list[Path]]) -> None:
    root, files = pdf_tree
    collected = collect_batch_inputs([root], recursive=True)
    assert len(collected) == 3
    collected_resolved = {p.resolve() for p in collected}
    expected_resolved = {f.resolve() for f in files}
    assert collected_resolved == expected_resolved


def test_collect_batch_inputs_globs(pdf_tree: tuple[Path, list[Path]]) -> None:
    root, _ = pdf_tree
    collected = collect_batch_inputs(globs=["*.pdf"], input_root=root)
    assert len(collected) == 1

    collected_rec = collect_batch_inputs(globs=["**/*.pdf"], input_root=root, recursive=True)
    assert len(collected_rec) == 3


def test_collect_batch_inputs_deduplication(sample_pdf: Path) -> None:
    collected = collect_batch_inputs([sample_pdf, sample_pdf])
    assert len(collected) == 1


def test_collect_batch_inputs_empty(tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    with pytest.raises(UsageError):
        collect_batch_inputs([empty_dir])


def test_collect_batch_inputs_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"
    with pytest.raises(UsageError):
        collect_batch_inputs([missing])


def test_plan_batch_destinations_flat(tmp_path: Path, sample_pdf: Path) -> None:
    out_dir = tmp_path / "out"
    planned = plan_batch_destinations(
        [sample_pdf],
        output_dir=out_dir,
        operation_name="optimize",
    )
    assert len(planned) == 1
    inp, out = planned[0]
    assert inp == sample_pdf
    assert out is not None
    assert out.name == "sample-optimize.pdf"
    assert out.parent == out_dir.resolve()


def test_plan_batch_destinations_hierarchical(
    pdf_tree: tuple[Path, list[Path]], tmp_path: Path
) -> None:
    root, files = pdf_tree
    out_dir = tmp_path / "batch_out"

    planned = plan_batch_destinations(
        files,
        output_dir=out_dir,
        input_root=root,
        operation_name="cleaned",
    )
    assert len(planned) == 3
    # doc_1 is in root -> out_dir / doc_1-cleaned.pdf
    assert planned[0][1] == out_dir.resolve() / "doc_1-cleaned.pdf"
    # doc_2 is in sub1 -> out_dir / sub1 / doc_2-cleaned.pdf
    assert planned[1][1] == out_dir.resolve() / "sub1" / "doc_2-cleaned.pdf"


def test_plan_batch_destinations_collision_detection(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    # Two files in different directories with same name mapping flat into out_dir
    f1 = tmp_path / "dir1" / "doc.pdf"
    f2 = tmp_path / "dir2" / "doc.pdf"
    f1.parent.mkdir()
    f2.parent.mkdir()
    f1.write_bytes(b"%PDF-1")
    f2.write_bytes(b"%PDF-2")

    with pytest.raises(FileSafetyError) as exc_info:
        plan_batch_destinations([f1, f2], output_dir=out_dir, operation_name="opt")
    assert "collision" in str(exc_info.value).lower()


def test_plan_batch_destinations_nested_safety(tmp_path: Path, sample_pdf: Path) -> None:
    in_root = tmp_path / "inputs"
    in_root.mkdir()
    out_nested = in_root / "outputs"
    out_nested.mkdir()

    with pytest.raises(FileSafetyError):
        plan_batch_destinations(
            [sample_pdf],
            output_dir=out_nested,
            input_root=in_root,
            operation_name="opt",
        )


def test_batch_engine_all_success(tmp_path: Path, sample_pdf: Path) -> None:
    out_dir = tmp_path / "out"
    planned = plan_batch_destinations([sample_pdf], output_dir=out_dir, operation_name="dummy")

    def dummy_worker(in_p: Path, out_p: Path | None) -> dict[str, Any]:
        assert out_p is not None
        out_p.write_text("done")
        return {"bytes": 4}

    engine = BatchEngine(jobs=1)
    report = engine.execute(planned, dummy_worker)
    assert report.total == 1
    assert report.succeeded == 1
    assert report.failed == 0
    assert report.skipped == 0
    assert len(report.items) == 1
    assert report.items[0].status == "success"
    assert (out_dir / "sample-dummy.pdf").read_text() == "done"


def test_batch_engine_continue_on_error(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    files = [tmp_path / f"file_{i}.pdf" for i in range(3)]
    for f in files:
        f.write_text("fake pdf")

    planned = plan_batch_destinations(files, output_dir=out_dir, operation_name="dummy")

    def flaky_worker(in_p: Path, out_p: Path | None) -> dict[str, Any]:
        if "file_1" in in_p.name:
            raise PDFToolsError("Simulated failure on file 1", code="E_FAIL")
        if out_p is not None:
            out_p.write_text("done")
        return {"ok": True}

    engine = BatchEngine(jobs=2, fail_fast=False)
    with pytest.raises(BatchError) as exc_info:
        engine.execute(planned, flaky_worker)

    assert exc_info.value.failed_count == 1
    report_dict = exc_info.value.details
    assert isinstance(report_dict, dict)
    assert report_dict["succeeded"] == 2
    assert report_dict["failed"] == 1


def test_batch_engine_fail_fast(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    files = [tmp_path / f"file_{i}.pdf" for i in range(4)]
    for f in files:
        f.write_text("fake")

    planned = plan_batch_destinations(files, output_dir=out_dir, operation_name="dummy")

    def fail_on_first(in_p: Path, out_p: Path | None) -> dict[str, Any]:
        if "file_0" in in_p.name:
            raise PDFToolsError("Failed fast", code="E_FIRST_FAIL")
        return {"ok": True}

    engine = BatchEngine(jobs=1, fail_fast=True)
    with pytest.raises(BatchError) as exc_info:
        engine.execute(planned, fail_on_first)

    report_dict = exc_info.value.details
    assert isinstance(report_dict, dict)
    assert report_dict["failed"] == 1
    assert report_dict["skipped"] == 3


def test_batch_engine_dry_run(tmp_path: Path, sample_pdf: Path) -> None:
    out_dir = tmp_path / "out"
    planned = plan_batch_destinations([sample_pdf], output_dir=out_dir, operation_name="dummy")

    engine = BatchEngine(dry_run=True)
    report = engine.execute(planned, lambda *a, **kw: None)
    assert report.total == 1
    assert report.succeeded == 0
    assert report.items[0].status == "planned"
    # Ensure destination file was NOT created
    assert not (out_dir / "sample-dummy.pdf").exists()


def test_batch_engine_atomic_report(tmp_path: Path, sample_pdf: Path) -> None:
    out_dir = tmp_path / "out"
    report_file = tmp_path / "reports" / "batch_report.json"
    planned = plan_batch_destinations([sample_pdf], output_dir=out_dir, operation_name="dummy")

    def dummy_worker(in_p: Path, out_p: Path | None) -> dict[str, Any]:
        if out_p:
            out_p.write_text("ok")
        return {"status": "ok"}

    engine = BatchEngine(report_path=report_file)
    engine.execute(planned, dummy_worker)

    assert report_file.exists()
    data = json.loads(report_file.read_text())
    assert data["status"] == "success"
    assert data["data"]["succeeded"] == 1
    assert data["data"]["failed"] == 0


def test_collect_batch_inputs_glob_requires_recursive(pdf_tree: tuple[Path, list[Path]]) -> None:
    root, _ = pdf_tree
    with pytest.raises(UsageError) as exc_info:
        collect_batch_inputs(globs=["**/*.pdf"], input_root=root, recursive=False)
    assert "--recursive" in str(exc_info.value)


def test_collect_batch_inputs_unmatched_glob(pdf_tree: tuple[Path, list[Path]]) -> None:
    root, _ = pdf_tree
    with pytest.raises(UsageError) as exc_info:
        collect_batch_inputs(globs=["nonexistent*.pdf"], input_root=root)
    assert "did not match" in str(exc_info.value)


def test_batch_engine_stress_500_files(tmp_path: Path) -> None:
    # Stress test processing directory tree of 500 PDF files with varying worker counts
    source_dir = tmp_path / "stress_in"
    source_dir.mkdir()
    for i in range(5):
        sub = source_dir / f"folder_{i}"
        sub.mkdir()
        for j in range(100):
            p = sub / f"doc_{i}_{j}.pdf"
            p.write_bytes(b"%PDF-1.4 header dummy")

    collected = collect_batch_inputs([source_dir], recursive=True)
    assert len(collected) == 500

    out_dir_1 = tmp_path / "stress_out_1"
    planned_1 = plan_batch_destinations(
        collected, output_dir=out_dir_1, input_root=source_dir, operation_name="proc"
    )

    def fast_worker(in_p: Path, out_p: Path | None) -> dict[str, Any]:
        assert out_p is not None
        out_p.write_bytes(b"%PDF-1.4 processed")
        return {"size": 18}

    # Run with jobs=1
    engine_1 = BatchEngine(jobs=1)
    rep_1 = engine_1.execute(planned_1, fast_worker)
    assert rep_1.total == 500
    assert rep_1.succeeded == 500
    assert rep_1.failed == 0

    # Run with jobs=4
    out_dir_4 = tmp_path / "stress_out_4"
    planned_4 = plan_batch_destinations(
        collected, output_dir=out_dir_4, input_root=source_dir, operation_name="proc"
    )
    engine_4 = BatchEngine(jobs=4)
    rep_4 = engine_4.execute(planned_4, fast_worker)
    assert rep_4.total == 500
    assert rep_4.succeeded == 500
    assert rep_4.failed == 0
