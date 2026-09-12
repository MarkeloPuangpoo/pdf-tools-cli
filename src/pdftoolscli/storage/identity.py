"""Filesystem identity sniffing, same-file prevention, and magic bytes detection.

Conforms to PLAN.md §14, §18.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import NamedTuple

from pdftoolscli.domain.errors import FileSafetyError


class FileIdentity(NamedTuple):
    device: int
    inode: int


def get_file_identity(path: Path | str) -> FileIdentity:
    """Return the filesystem identity tuple for a path.

    On POSIX: (st_dev, st_ino).
    On Windows: (VolumeSerialNumber, FileIndex) via Win32 API or stat fallback.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")

    st = p.stat()

    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            import ctypes
            from ctypes import wintypes

            class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
                _fields_ = [
                    ("dwFileAttributes", wintypes.DWORD),
                    ("ftCreationTime", wintypes.FILETIME),
                    ("ftLastAccessTime", wintypes.FILETIME),
                    ("ftLastWriteTime", wintypes.FILETIME),
                    ("dwVolumeSerialNumber", wintypes.DWORD),
                    ("nFileSizeHigh", wintypes.DWORD),
                    ("nFileSizeLow", wintypes.DWORD),
                    ("nNumberOfLinks", wintypes.DWORD),
                    ("nFileIndexHigh", wintypes.DWORD),
                    ("nFileIndexLow", wintypes.DWORD),
                ]

            GENERIC_READ = 0x80000000
            FILE_SHARE_READ = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            OPEN_EXISTING = 3
            FILE_FLAG_BACKUP_SEMANTICS = 0x02000000

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.CreateFileW(
                str(p),
                GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS,
                None,
            )
            if handle != -1:
                try:
                    info = BY_HANDLE_FILE_INFORMATION()
                    if kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
                        vol = info.dwVolumeSerialNumber
                        idx = (info.nFileIndexHigh << 32) | info.nFileIndexLow
                        return FileIdentity(device=vol, inode=idx)
                finally:
                    kernel32.CloseHandle(handle)

    return FileIdentity(device=st.st_dev, inode=st.st_ino)


def is_same_file(path_a: Path | str, path_b: Path | str) -> bool:
    """Return True if path_a and path_b refer to the exact same filesystem object."""
    p_a = Path(path_a).resolve()
    p_b = Path(path_b).resolve()

    # Exact canonical path match (case-normalizing where appropriate)
    if os.path.normcase(str(p_a)) == os.path.normcase(str(p_b)):
        return True

    # Check device/inode identity if both files exist on disk
    if p_a.exists() and p_b.exists():
        try:
            return get_file_identity(p_a) == get_file_identity(p_b)
        except OSError:
            return False

    return False


def assert_distinct_files(
    input_path: Path | str,
    output_path: Path | str,
    operation_name: str = "operation",
) -> None:
    """Assert that input and output do not refer to the same file.

    Strict safety invariant: NEVER allow input == output, even with --overwrite.
    """
    in_p = Path(input_path).resolve()
    out_p = Path(output_path).resolve()

    if is_same_file(in_p, out_p):
        raise FileSafetyError(
            f"Cannot perform {operation_name}: input and output refer to the same file ({in_p}). "
            "In-place modifications are strictly prohibited.",
            code="E_SAME_FILE",
            hint="Specify a distinct destination filename, or use a temporary output file.",
        )


def sniff_magic_bytes(header: bytes) -> str | None:
    """Sniff format from raw header bytes (at least 1024 bytes recommended).

    Returns 'pdf', 'png', 'jpeg', 'tiff', 'webp', or None.
    """
    if len(header) < 4:
        return None

    # PDF: %PDF- within the first 1024 bytes
    if b"%PDF-" in header[:1024]:
        return "pdf"

    # PNG: \x89PNG\r\n\x1a\n
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    # JPEG: \xff\xd8\xff
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"

    # TIFF: II*\x00 (little endian) or MM\x00* (big endian)
    if header.startswith(b"II*\x00") or header.startswith(b"MM\x00*"):
        return "tiff"

    # WebP: RIFF....WEBP
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"

    return None


def sniff_file_format(path: Path | str) -> str | None:
    """Sniff format from file header bytes."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        with open(p, "rb") as f:
            chunk = f.read(1024)
            return sniff_magic_bytes(chunk)
    except OSError:
        return None
