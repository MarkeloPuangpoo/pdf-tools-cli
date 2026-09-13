"""CLI command for visual stamping and watermarking conforming to PLAN.md §12.7 C37 (CMD-013)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.decoration import (
    DecorationService,
    parse_offset_pair,
    parse_tile_pair,
)


@click.command(name="stamp")
@click.argument("input", type=click.Path(path_type=Path))
@click.option("--text", default=None, help="Text string to stamp.")
@click.option(
    "--image",
    "image_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Image file to stamp.",
)
@click.option(
    "--pdf",
    "pdf_path",
    type=click.Path(path_type=Path),
    default=None,
    help="PDF file to stamp as watermark.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Output PDF path.",
)
@click.option(
    "--layer",
    type=click.Choice(["foreground", "background"]),
    default="foreground",
    help="Layer placement (default: foreground).",
)
@click.option(
    "--position",
    type=click.Choice(
        [
            "center",
            "top-left",
            "top",
            "top-right",
            "left",
            "right",
            "bottom-left",
            "bottom",
            "bottom-right",
            "custom",
        ]
    ),
    default="center",
    help="Stamp position (default: center).",
)
@click.option(
    "--offset",
    default=None,
    help="Offset 'X,Y' in points or units (e.g. 10pt,20pt or 0,0).",
)
@click.option(
    "--opacity",
    type=float,
    default=0.25,
    help="Opacity (0.0 to 1.0, default: 0.25).",
)
@click.option(
    "--rotation",
    type=float,
    default=0.0,
    help="Clockwise rotation degrees (default: 0).",
)
@click.option(
    "--scale",
    type=float,
    default=1.0,
    help="Positive scale factor (default: 1.0).",
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
    default=36.0,
    help="Font size in points (default: 36.0).",
)
@click.option(
    "--color",
    default="#808080",
    help="Color hex format #RRGGBB (default: #808080).",
)
@click.option(
    "--tile",
    default=None,
    help="Tile step 'XSTEP,YSTEP' (e.g. 100pt,100pt).",
)
@click.option(
    "--pages",
    default="all",
    help="Page range specification (default: all).",
)
@click.option(
    "--source-page",
    type=int,
    default=1,
    help="1-indexed source page when stamping with --pdf (default: 1).",
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
def stamp_cmd(
    ctx: click.Context,
    input: Path,
    text: str | None,
    image_path: Path | None,
    pdf_path: Path | None,
    output_path: Path,
    layer: str,
    position: str,
    offset: str | None,
    opacity: float,
    rotation: float,
    scale: float,
    font_path: Path | None,
    font_size: float,
    color: str,
    tile: str | None,
    pages: str,
    source_page: int,
    password: str | None,
    overwrite: bool,
) -> None:
    """Apply foreground stamps or background watermarks using text, image, or PDF."""
    opts = ctx.obj.get("options") if ctx.obj else None
    if not isinstance(opts, GlobalOptions):
        opts = GlobalOptions()
    presenter = HumanPresenter(color=opts.color)
    start_time = time.monotonic()

    try:
        resolved_pw = resolve_password_source(password)

        if source_page != 1 and pdf_path is None:
            raise PDFToolsError(
                "--source-page is only valid when --pdf is specified.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

        parsed_offset = parse_offset_pair(offset)
        parsed_tile = parse_tile_pair(tile)
        is_custom_offset = offset is not None

        service = DecorationService()
        result = service.stamp(
            input_path=input,
            output_path=output_path,
            text=text,
            image_path=image_path,
            pdf_path=pdf_path,
            layer=layer,
            position=position,
            offset=parsed_offset,
            opacity=opacity,
            rotation=rotation,
            scale=scale,
            font_path=font_path,
            font_size=font_size,
            color=color,
            tile=parsed_tile,
            page_selection=pages,
            source_page=source_page,
            password=resolved_pw,
            overwrite=overwrite,
            is_custom_offset=is_custom_offset,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(command="stamp", status="ok", data=result, elapsed_ms=elapsed_ms)
        else:
            if not opts.quiet:
                presenter.render_success(
                    f"Successfully applied {result['layer']} stamp to "
                    f"{result['pages_modified']} page(s): '{result['output']}'."
                )
    except (click.exceptions.Exit, SystemExit):
        raise
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="stamp",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)
