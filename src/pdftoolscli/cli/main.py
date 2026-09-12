"""CLI entry point for pdftoolscli."""

from __future__ import annotations

import click

from pdftoolscli import __version__


@click.group(
    name="pdftoolscli",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.version_option(version=__version__, prog_name="pdftoolscli")
def cli() -> None:
    """PDF Tools CLI — Fast, safe, offline PDF toolkit for terminal and automation workflows."""
