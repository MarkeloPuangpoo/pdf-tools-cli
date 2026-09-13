"""CLI command for page rasterization conforming to PLAN.md §12.4 C22 (CMD-010)."""

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
from pdftoolscli.services.rendering import RenderService


@click.command("render", help="Render PDF pages to image files (PNG, JPEG, WebP, TIFF).")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    help="Directory to save rendered page images.",
)
@click.option(
    "-o",
    "--output",
    "output_file",
    help="Output file path (or '-' for stdout). Allowed only when 1 page is selected.",
)
@click.option(
    "--to",
    type=click.Choice(["png", "jpeg", "jpg", "webp", "tiff"], case_sensitive=False),
    default="png",
    show_default=True,
    help="Output image format.",
)
@click.option(
    "--dpi",
    type=click.IntRange(36, 2400),
    default=150,
    show_default=True,
    help="Rendering resolution in DPI (36-2400).",
)
@click.option(
    "--quality",
    type=click.IntRange(0, 100),
    default=None,
    help="Encoding quality for JPEG/WebP (default: 85). Not supported for PNG/TIFF.",
)
@click.option(
    "--background",
    default="white",
    show_default=True,
    help="Page background color (e.g. white, black, #FFFFFF, or transparent).",
)
@click.option(
    "--colorspace",
    type=click.Choice(["rgb", "gray"], case_sensitive=False),
    default="rgb",
    show_default=True,
    help="Output image colorspace.",
)
@click.option(
    "--pages",
    "pages_range",
    default=None,
    help="Page range to render (e.g. 1-3, 5, odd, even). Default: all.",
)
@click.option(
    "--template",
    default=None,
    help="Filename template for multi-page output (e.g. '{stem}-p{page:03d}.{ext}').",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite existing output files.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.pass_context
def render_cmd(
    ctx: click.Context,
    input_path: Path,
    output_dir: Path | None,
    output_file: str | None,
    to: str,
    dpi: int,
    quality: int | None,
    background: str,
    colorspace: str,
    pages_range: str | None,
    template: str | None,
    overwrite: bool,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
) -> None:
    """Render PDF pages to raster image files."""
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
        service = RenderService()
        manifest = service.render(
            input_path=input_path,
            output_dir=output_dir,
            output_file=output_file,
            to=to,
            dpi=dpi,
            quality=quality,
            background=background,
            colorspace=colorspace,
            pages_range=pages_range,
            template=template,
            password=password,
            overwrite=overwrite,
        )

        if output_file == "-":
            return

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="render",
                status="ok",
                data={"rendered_pages": manifest, "count": len(manifest)},
                elapsed_ms=elapsed_ms,
            )
        else:
            if not opts.quiet:
                target_desc = str(output_dir) if output_dir else str(output_file)
                msg = (
                    f"Successfully rendered {len(manifest)} page(s) to '{target_desc}' "
                    f"({dpi} DPI, {to.upper()})."
                )
                presenter.render_success(msg)
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="render",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)
