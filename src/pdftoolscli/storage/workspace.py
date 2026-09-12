"""Safe invocation scratch workspaces conforming to PLAN.md §18."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from types import TracebackType


class InvocationWorkspace:
    """Manages an isolated, private temporary workspace for a CLI invocation."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else None
        self._workspace_dir: Path | None = None

    @property
    def path(self) -> Path:
        """Return the initialized workspace path, creating it if needed."""
        if self._workspace_dir is None:
            self._init_workspace()
        if self._workspace_dir is None:
            raise RuntimeError("Failed to initialize workspace directory")
        return self._workspace_dir

    def _init_workspace(self) -> None:
        prefix = f"ptc-{uuid.uuid4().hex[:8]}-"
        parent = str(self.base_dir) if self.base_dir else None

        # Create temporary directory with secure permissions
        created_dir = tempfile.mkdtemp(prefix=prefix, dir=parent)
        self._workspace_dir = Path(created_dir).resolve()

        if sys.platform != "win32":
            # POSIX: enforce 0700 (user only read/write/execute)
            import contextlib

            with contextlib.suppress(OSError):
                os.chmod(self._workspace_dir, 0o700)

    def create_scratch_file(self, prefix: str = "stage-", suffix: str = ".tmp") -> Path:
        """Create a private scratch file with 0600 permissions in this workspace."""
        fd, scratch_path = tempfile.mkstemp(
            prefix=prefix,
            suffix=suffix,
            dir=str(self.path),
        )
        os.close(fd)
        p = Path(scratch_path)
        if sys.platform != "win32":
            import contextlib

            with contextlib.suppress(OSError):
                os.chmod(p, 0o600)
        return p

    def cleanup(self) -> None:
        """Safely remove the workspace directory and all contained scratch files."""
        if self._workspace_dir is not None and self._workspace_dir.exists():
            try:
                shutil.rmtree(self._workspace_dir, ignore_errors=True)
            finally:
                self._workspace_dir = None

    def __enter__(self) -> InvocationWorkspace:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.cleanup()
