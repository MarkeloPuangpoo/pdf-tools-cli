"""CLI command for dynamic page numbering conforming to PLAN.md §12.7 C38 (CMD-013)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.decoration import DecorationService


@click.command(name="number")
@click.argument("input", type=click.Path(path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Output PDF path.",
)
@click.option(
    "--format",
    "format_template",
    default="{page} / {pages}",
    help="Page number format template (default: '{page} / {pages}').",
)
@click.option(
    "--start",
    type=int,
    default=1,
    help="Starting page number ordinal (default: 1).",
)
@click.option(
    "--style",
    type=click.Choice(["decimal", "roman", "ROMAN"]),
    default="decimal",
    help="Numbering style (default: decimal).",
)
@click.option(
    "--header",
    default=None,
    help="Header text template placed at top center.",
)
@click.option(
    "--footer",
    default=None,
    help="Footer text template placed at bottom center.",
)
@click.option(
    "--position",
    type=click.Choice(
        [
            "bottom",
            "top",
            "bottom-left",
            "bottom-right",
            "top-left",
            "top-right",
            "center",
            "left",
            "right",
        ]
    ),
    default="bottom",
    help="Position for format text (default: bottom).",
)
@click.option(
    "--font",
    "font_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Path to custom TTF/OTF font file.",
)
@click.option(
    "--font-size",
    type=float,
    default=10.0,
    help="Font size in points (default: 10.0).",
)
@click.option(
    "--color",
    default="#000000",
    help="Color hex format #RRGGBB (default: #000000).",
)
@click.option(
    "--pages",
    default="all",
    help="Page range specification (default: all).",
)
@click.option(
    "--date",
    "date_str",
    default=None,
    help="Explicit date string (YYYY-MM-DD) required if {date} is used.",
)
@click.option(
    "--password",
    default=None,
    envvar="PDFTOOLS_PASSWORD",
    help="Document password for encrypted inputs.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite output file if it exists.",
)
@click.pass_context
def number_cmd(
    ctx: click.Context,
    input: Path,
    output_path: Path,
    format_template: str,
    start: int,
    style: str,
    header: str | None,
    footer: str | None,
    position: str,
    font_path: Path | None,
    font_size: float,
    color: str,
    pages: str,
    date_str: str | None,
    password: str | None,
    overwrite: bool,
) -> None:
    """Add dynamic page numbers, headers, and footers to PDF documents."""
    opts = ctx.obj.get("options") if ctx.obj else None
    if not isinstance(opts, GlobalOptions):
        opts = GlobalOptions()
    presenter = HumanPresenter(color=opts.color)
    start_time = time.monotonic()

    try:
        resolved_pw = resolve_password_source(password)

        service = DecorationService()
        result = service.number(
            input_path=input,
            output_path=output_path,
            format_template=format_template,
            start=start,
            style=style,
            header=header,
            footer=footer,
            position=position,
            font_path=font_path,
            font_size=font_size,
            color=color,
            page_selection=pages,
            date_str=date_str,
            password=resolved_pw,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(command="number", status="ok", data=result, elapsed_ms=elapsed_ms)
        else:
            if not opts.quiet:
                presenter.render_success(
                    f"Successfully numbered {result['pages_numbered']} page(s) "
                    f"({result['style']} style starting at {result['start']}): "
                    f"'{result['output']}'."
                )
    except (click.exceptions.Exit, SystemExit):
        raise
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="number",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)
