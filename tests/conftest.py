"""Pytest fixtures and configuration for pdftoolscli test suite (TEST-001)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Return the absolute path to the generated fixtures directory."""
    path = Path(__file__).resolve().parent / "fixtures" / "generated"
    assert path.is_dir(), f"Fixtures directory missing at {path}"
    return path


@pytest.fixture(scope="session")
def fixtures_manifest() -> dict[str, Any]:
    """Return the parsed fixtures manifest."""
    manifest_path = Path(__file__).resolve().parent / "fixtures" / "manifest.json"
    assert manifest_path.is_file(), f"Manifest missing at {manifest_path}"
    data: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data


@pytest.fixture
def scratch_dir(tmp_path: Path) -> Path:
    """Return an isolated temporary scratch directory for test artifacts."""
    return tmp_path
