"""Entrypoint for python -m pdftoolscli."""

from __future__ import annotations

import sys

from pdftoolscli.cli.main import cli

if __name__ == "__main__":
    sys.exit(cli())
