"""Tests for repository scaffolding and package metadata (ARCH-001)."""

from __future__ import annotations

import subprocess
import sys

from pdftoolscli import __product_name__, __version__


def test_package_metadata() -> None:
    """Test package version and product name are properly defined."""
    assert __version__ == "0.1.0.dev0"
    assert __product_name__ == "PDF Tools CLI"


def test_cli_version_flag() -> None:
    """Test pdftoolscli --version outputs the correct version."""
    res = subprocess.run(
        [sys.executable, "-m", "pdftoolscli", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "pdftoolscli" in res.stdout
    assert __version__ in res.stdout


def test_cli_help_flag() -> None:
    """Test pdftoolscli --help outputs usage information."""
    res = subprocess.run(
        [sys.executable, "-m", "pdftoolscli", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "Usage:" in res.stdout
    assert "pdftoolscli" in res.stdout


def test_ptc_alias_entrypoint() -> None:
    """Test that the ptc alias entrypoint is wired to cli."""
    res = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pdftoolscli.cli.main import cli; import sys; sys.exit(cli(['--help']))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Usage:" in res.stdout
