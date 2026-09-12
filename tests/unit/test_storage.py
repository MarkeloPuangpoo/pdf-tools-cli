"""Unit tests for storage subsystem: identity, workspace, and atomic transactions.

Conforms to PLAN.md §14, §18.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from pdftoolscli.domain.errors import FileSafetyError
from pdftoolscli.storage.atomic import AtomicPublisher
from pdftoolscli.storage.identity import (
    assert_distinct_files,
    is_same_file,
    sniff_file_format,
    sniff_magic_bytes,
)
from pdftoolscli.storage.workspace import InvocationWorkspace


def test_file_identity_and_same_file(tmp_path: Path) -> None:
    f1 = tmp_path / "file1.pdf"
    f1.write_bytes(b"%PDF-1.7\ntest")

    f2 = tmp_path / "file2.pdf"
    f2.write_bytes(b"%PDF-1.7\ntest2")

    # Different files
    assert not is_same_file(f1, f2)
    assert_distinct_files(f1, f2)

    # Same file
    assert is_same_file(f1, f1)
    with pytest.raises(FileSafetyError) as exc_info:
        assert_distinct_files(f1, f1)
    assert exc_info.value.code == "E_SAME_FILE"
    assert exc_info.value.exit_code == 8

    # Hardlink to same file
    if sys.platform != "win32":
        f1_link = tmp_path / "file1_hardlink.pdf"
        try:
            os.link(f1, f1_link)
            assert is_same_file(f1, f1_link)
            with pytest.raises(FileSafetyError):
                assert_distinct_files(f1, f1_link)
        except OSError:
            pass


def test_sniff_magic_bytes() -> None:
    assert sniff_magic_bytes(b"%PDF-1.7\n...") == "pdf"
    assert sniff_magic_bytes(b"   %PDF-2.0") == "pdf"
    assert sniff_magic_bytes(b"\x89PNG\r\n\x1a\n...") == "png"
    assert sniff_magic_bytes(b"\xff\xd8\xff\xe0...") == "jpeg"
    assert sniff_magic_bytes(b"II*\x00...") == "tiff"
    assert sniff_magic_bytes(b"MM\x00*...") == "tiff"
    assert sniff_magic_bytes(b"RIFF\x00\x00\x00\x00WEBP...") == "webp"
    assert sniff_magic_bytes(b"") is None
    assert sniff_magic_bytes(b"GIF89a") is None
    assert sniff_magic_bytes(b"Plain text") is None


def test_sniff_file_format(tmp_path: Path) -> None:
    pdf_file = tmp_path / "sample.pdf"
    pdf_file.write_bytes(b"%PDF-1.5 test")
    assert sniff_file_format(pdf_file) == "pdf"

    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("just text")
    assert sniff_file_format(txt_file) is None

    assert sniff_file_format(tmp_path / "nonexistent.pdf") is None


def test_invocation_workspace(tmp_path: Path) -> None:
    with InvocationWorkspace(base_dir=tmp_path) as ws:
        ws_path = ws.path
        assert ws_path.is_dir()
        if sys.platform != "win32":
            mode = ws_path.stat().st_mode & 0o777
            assert mode == 0o700

        scratch = ws.create_scratch_file()
        assert scratch.is_file()
        scratch.write_text("staged content")

    # Workspace must be removed after exit
    assert not ws_path.exists()


def test_atomic_publisher_no_clobber(tmp_path: Path) -> None:
    staged = tmp_path / "staged.pdf"
    staged.write_bytes(b"%PDF-1.7 staged")

    dest = tmp_path / "dest.pdf"
    published = AtomicPublisher.publish_file(staged, dest, overwrite=False)
    assert published == dest.resolve()
    assert dest.read_bytes() == b"%PDF-1.7 staged"
    assert not staged.exists()

    # Publishing again without overwrite must fail safely with E_OUTPUT_EXISTS
    staged2 = tmp_path / "staged2.pdf"
    staged2.write_bytes(b"%PDF-1.7 staged 2")
    with pytest.raises(FileSafetyError) as exc_info:
        AtomicPublisher.publish_file(staged2, dest, overwrite=False)
    assert exc_info.value.code == "E_OUTPUT_EXISTS"
    assert exc_info.value.exit_code == 8
    # Destination must remain untouched!
    assert dest.read_bytes() == b"%PDF-1.7 staged"


def test_atomic_publisher_overwrite(tmp_path: Path) -> None:
    dest = tmp_path / "dest.pdf"
    dest.write_bytes(b"initial")

    staged = tmp_path / "staged.pdf"
    staged.write_bytes(b"new content")

    published = AtomicPublisher.publish_file(staged, dest, overwrite=True)
    assert published == dest.resolve()
    assert dest.read_bytes() == b"new content"
    assert not staged.exists()


def test_atomic_publisher_refuse_symlink(tmp_path: Path) -> None:
    if sys.platform == "win32":
        pytest.skip("Symlink tests skipped on Windows")

    real_dest = tmp_path / "real_dest.pdf"
    real_dest.write_bytes(b"original")

    symlink_dest = tmp_path / "symlink_dest.pdf"
    symlink_dest.symlink_to(real_dest)

    staged = tmp_path / "staged.pdf"
    staged.write_bytes(b"attacker content")

    with pytest.raises(FileSafetyError) as exc_info:
        AtomicPublisher.publish_file(staged, symlink_dest, overwrite=True)
    assert exc_info.value.code == "E_SAFETY_CONFLICT"
    # Target was NOT overwritten
    assert real_dest.read_bytes() == b"original"


def test_atomic_publisher_directory(tmp_path: Path) -> None:
    staged_dir = tmp_path / "staged_dir"
    staged_dir.mkdir()
    (staged_dir / "item.txt").write_text("item")

    dest_dir = tmp_path / "output_dir"
    AtomicPublisher.publish_directory(staged_dir, dest_dir, overwrite=False)
    assert (dest_dir / "item.txt").read_text() == "item"
    assert not staged_dir.exists()

    # Attempt publish again without overwrite fails
    staged_dir2 = tmp_path / "staged_dir2"
    staged_dir2.mkdir()
    with pytest.raises(FileSafetyError) as exc_info:
        AtomicPublisher.publish_directory(staged_dir2, dest_dir, overwrite=False)
    assert exc_info.value.code == "E_OUTPUT_EXISTS"

    # Publish with overwrite=True succeeds
    (staged_dir2 / "item2.txt").write_text("item2")
    AtomicPublisher.publish_directory(staged_dir2, dest_dir, overwrite=True)
    assert (dest_dir / "item2.txt").read_text() == "item2"


def test_atomic_publisher_error_paths(tmp_path: Path) -> None:
    # Non-existent staged file
    with pytest.raises(FileNotFoundError):
        AtomicPublisher.publish_file(tmp_path / "missing.pdf", tmp_path / "out.pdf")

    # Non-existent staged directory
    with pytest.raises(NotADirectoryError):
        AtomicPublisher.publish_directory(tmp_path / "missing_dir", tmp_path / "out_dir")

    # Destination in nested non-existent directory (auto-creates parent)
    staged = tmp_path / "staged.pdf"
    staged.write_bytes(b"content")
    nested_dest = tmp_path / "nested" / "sub" / "out.pdf"
    AtomicPublisher.publish_file(staged, nested_dest)
    assert nested_dest.is_file()
