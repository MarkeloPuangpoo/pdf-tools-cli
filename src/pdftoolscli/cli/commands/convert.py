"""CLI command group for conversion operations conforming to PLAN.md §12.4 C23, C24 (CMD-010)."""

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
from pdftoolscli.services.conversion import ConversionService


@click.group("convert")
def convert_group() -> None:
    """Convert raster images to PDF or flatten vector PDFs into raster image PDFs."""


@convert_group.command("images")
@click.argument(
    "images",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Output destination path for the converted PDF.",
)
@click.option(
    "--size",
    default="auto",
    show_default=True,
    help="Target page size (auto, A4, Letter, or WIDTHxHEIGHT e.g. 595ptx842pt).",
)
@click.option(
    "--dpi",
    type=click.IntRange(36, 2400),
    default=None,
    help="Image resolution in DPI for auto-sizing fallback.",
)
@click.option(
    "--fit",
    type=click.Choice(["contain", "exact"], case_sensitive=False),
    default="contain",
    show_default=True,
    help="Image fitting strategy when custom size is used.",
)
@click.option(
    "--background",
    default=None,
    help="Background color for transparent images (e.g. white, #FFFFFF).",
)
@click.option(
    "--all-frames",
    is_flag=True,
    default=False,
    help="Expand all animation or multi-page TIFF frames into separate pages.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite existing output file.",
)
@click.pass_context
def images_cmd(
    ctx: click.Context,
    images: tuple[Path, ...],
    output_path: Path,
    size: str,
    dpi: int | None,
    fit: str,
    background: str | None,
    all_frames: bool,
    overwrite: bool,
) -> None:
    """Convert an ordered list of raster images into a clean PDF."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions()) if ctx.obj else GlobalOptions()
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic()) if ctx.obj else time.monotonic()

    try:
        service = ConversionService()
        result = service.convert_images(
            image_paths=list(images),
            output_path=output_path,
            size=size,
            dpi=dpi,
            fit=fit,
            background=background,
            all_frames=all_frames,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="convert images",
                status="ok",
                data=result,
                elapsed_ms=elapsed_ms,
            )
        else:
            if not opts.quiet:
                presenter.render_success(
                    f"Converted {result['images_converted']} image(s) to '{output_path}' "
                    f"({result['page_count']} page(s), {result['size_bytes']:,} bytes)."
                )
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="convert images",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)


@convert_group.command("rasterize")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Output destination path for the rasterized PDF.",
)
@click.option(
    "--pages",
    "pages_range",
    default=None,
    help="Page range to rasterize (e.g. 1-3, odd, even). Default: all.",
)
@click.option(
    "--dpi",
    type=click.IntRange(36, 2400),
    default=150,
    show_default=True,
    help="Rendering resolution in DPI (36-2400).",
)
@click.option(
    "--colorspace",
    type=click.Choice(["rgb", "gray"], case_sensitive=False),
    default="rgb",
    show_default=True,
    help="Output image colorspace.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite existing output file.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.pass_context
def rasterize_cmd(
    ctx: click.Context,
    input_path: Path,
    output_path: Path,
    pages_range: str | None,
    dpi: int,
    colorspace: str,
    overwrite: bool,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
) -> None:
    """Rasterize a vector/text PDF into an image-only flattened PDF."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions()) if ctx.obj else GlobalOptions()
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic()) if ctx.obj else time.monotonic()

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        service = ConversionService()
        result = service.convert_rasterize(
            input_path=input_path,
            output_path=output_path,
            pages_range=pages_range,
            dpi=dpi,
            colorspace=colorspace,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="convert rasterize",
                status="ok",
                data=result,
                elapsed_ms=elapsed_ms,
            )
        else:
            if not opts.quiet:
                presenter.render_success(
                    f"Rasterized {result['pages_rasterized']} page(s) into '{output_path}' "
                    f"({dpi} DPI, {colorspace.upper()}, {result['size_bytes']:,} bytes)."
                )
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="convert rasterize",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)
