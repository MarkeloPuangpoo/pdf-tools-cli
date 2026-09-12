"""Atomic file and directory publication conforming to PLAN.md §18."""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path

from pdftoolscli.domain.errors import FileSafetyError
from pdftoolscli.storage.identity import assert_distinct_files


def _fsync_file(path: Path) -> None:
    """Flush and fsync an existing file to persistent disk."""
    with contextlib.suppress(OSError), open(path, "rb") as f:
        f.flush()
        os.fsync(f.fileno())


def _fsync_dir(dir_path: Path) -> None:
    """Fsync the parent directory on POSIX platforms where supported."""
    if sys.platform != "win32" and hasattr(os, "O_DIRECTORY"):
        with contextlib.suppress(OSError):
            dir_fd = os.open(str(dir_path), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)


def _replace_with_windows_retry(
    staged_path: Path, destination_path: Path, timeout: float = 2.0
) -> None:
    """Atomically replace a file with bounded retry on Windows for file sharing violations."""
    start_time = time.monotonic()
    while True:
        try:
            os.replace(staged_path, destination_path)
            return
        except PermissionError as e:
            if sys.platform == "win32" and (time.monotonic() - start_time) < timeout:
                time.sleep(0.05)
                continue
            raise OSError(
                f"Could not overwrite destination {destination_path} within {timeout}s: {e}"
            ) from e


class AtomicPublisher:
    """Publishes staged artifacts to final destination paths with safety guarantees."""

    @staticmethod
    def publish_file(
        staged_path: Path | str,
        destination_path: Path | str,
        overwrite: bool = False,
    ) -> Path:
        """Publish a staged file to destination atomically.

        Safety guarantees:
          - Refuses symlink or reparse point destinations.
          - Never allows staged == destination or input == output.
          - Default: no-clobber (refuses if destination already exists).
          - With overwrite=True: atomic replacement on same filesystem with bounded Windows retry.
        """
        staged = Path(staged_path).resolve()
        dest = Path(destination_path)

        if not staged.is_file():
            raise FileNotFoundError(f"Staged file not found: {staged}")

        # Ensure destination parent directory exists
        dest_parent = dest.parent.resolve()
        if not dest_parent.exists():
            dest_parent.mkdir(parents=True, exist_ok=True)

        # Refuse symlink or reparse point targets
        if dest.is_symlink():
            raise FileSafetyError(
                f"Refusing to publish over symlink destination: {dest}",
                code="E_SAFETY_CONFLICT",
                hint="Remove the destination symlink or specify a regular file path.",
            )

        # Check that staged file is not the destination file
        if dest.exists():
            assert_distinct_files(staged, dest, operation_name="publication")

        # Flush and fsync staged content before publication
        _fsync_file(staged)

        if dest.exists():
            if not overwrite:
                raise FileSafetyError(
                    f"Destination file already exists: {dest}",
                    code="E_OUTPUT_EXISTS",
                    hint="Specify --overwrite to replace the existing file.",
                )

            # Atomic overwrite
            _replace_with_windows_retry(staged, dest)
            _fsync_dir(dest_parent)
            return dest.resolve()

        # Destination does not exist: perform atomic no-clobber publication
        if sys.platform != "win32":
            try:
                # Use hardlink for strict atomic no-clobber
                os.link(staged, dest)
                with contextlib.suppress(OSError):
                    os.unlink(staged)
                _fsync_dir(dest_parent)
                return dest.resolve()
            except FileExistsError:
                raise FileSafetyError(
                    f"Destination file already exists: {dest}",
                    code="E_OUTPUT_EXISTS",
                    hint="Specify --overwrite to replace the existing file.",
                ) from None
            except OSError:
                # Filesystem doesn't support hardlinks (e.g. FAT/exFAT), fallback to rename
                pass

        # Platform rename or hardlink fallback
        if dest.exists():
            raise FileSafetyError(
                f"Destination file already exists: {dest}",
                code="E_OUTPUT_EXISTS",
                hint="Specify --overwrite to replace the existing file.",
            )

        _replace_with_windows_retry(staged, dest)
        _fsync_dir(dest_parent)
        return dest.resolve()

    @staticmethod
    def publish_directory(
        staged_dir: Path | str,
        destination_dir: Path | str,
        overwrite: bool = False,
    ) -> Path:
        """Publish a staged directory to destination atomically."""
        staged = Path(staged_dir).resolve()
        dest = Path(destination_dir)

        if not staged.is_dir():
            raise NotADirectoryError(f"Staged directory not found: {staged}")

        if dest.is_symlink():
            raise FileSafetyError(
                f"Refusing to publish over symlink destination: {dest}",
                code="E_SAFETY_CONFLICT",
            )

        if dest.exists():
            if not overwrite:
                raise FileSafetyError(
                    f"Destination directory already exists: {dest}",
                    code="E_OUTPUT_EXISTS",
                    hint="Specify --overwrite to replace the existing directory.",
                )
            # Safe replacement: rename existing to backup, rename staged to dest, delete backup
            backup = dest.parent / f"{dest.name}.old-{time.time_ns()}"
            try:
                os.replace(dest, backup)
            except OSError as e:
                raise OSError(f"Could not move existing directory for overwrite: {e}") from e

            try:
                os.replace(staged, dest)
            except OSError as e:
                # Rollback
                os.replace(backup, dest)
                raise e

            # Remove old directory after successful swap
            import shutil

            shutil.rmtree(backup, ignore_errors=True)
            return dest.resolve()

        # Destination does not exist: rename staged to destination
        dest_parent = dest.parent.resolve()
        if not dest_parent.exists():
            dest_parent.mkdir(parents=True, exist_ok=True)

        os.replace(staged, dest)
        _fsync_dir(dest_parent)
        return dest.resolve()
