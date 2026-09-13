"""CLI command group for embedded image management conforming to PLAN.md §12.5 (CMD-009)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click
from rich.table import Table

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.images import ImageService


@click.group("images")
def images_group() -> None:
    """Inspect and extract embedded raster image assets."""


@images_group.command("list")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--pages", "pages_range", default=None, help="Page range to inspect (default: all).")
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    input_path: Path,
    pages_range: str | None,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
) -> None:
    """List all embedded image XObjects with dimensions, colorspace, and filters."""
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
        service = ImageService()
        result = service.list_images(input_path, pages_range=pages_range, password=password)

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(command="images list", status="ok", data=result, elapsed_ms=elapsed_ms)
            return

        if not opts.quiet:
            table = Table(title=f"Embedded Images in {input_path.name}")
            table.add_column("Asset ID", style="bold cyan")
            table.add_column("Dimensions", justify="right")
            table.add_column("Colorspace")
            table.add_column("Filters")
            table.add_column("Bytes", justify="right")
            table.add_column("Pages")

            for img in result["images"]:
                dim_str = f"{img['width']}x{img['height']}"
                cs_str = str(img["colorspace"] or "Unknown")
                filt_str = ", ".join(img["filters"]) or "None"
                bytes_str = f"{img['encoded_bytes']:,}"
                pages_str = ", ".join(str(p) for p in img["pages"])
                table.add_row(img["asset_id"], dim_str, cs_str, filt_str, bytes_str, pages_str)

            presenter.stdout_console.print(table)
            presenter.stdout_console.print(
                f"Found [bold]{result['total_unique_images']}[/bold] unique image(s) across "
                f"[bold]{result['total_occurrences']}[/bold] occurrence(s)."
            )
        ctx.exit(ExitCode.SUCCESS)
    except PDFToolsError as err:
        if opts.json:
            render_json(command="images list", status="error", errors=[err.as_detail()])
        else:
            presenter.render_error(err)
            if opts.debug:
                import traceback

                traceback.print_exc(file=sys.stderr)
        ctx.exit(int(err.exit_code))


@images_group.command("extract")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--output-dir",
    "output_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Target directory to export extracted images.",
)
@click.option(
    "--pages", "pages_range", default=None, help="Page range to extract from (default: all)."
)
@click.option(
    "--mode",
    type=click.Choice(["original", "decoded"], case_sensitive=False),
    default="original",
    show_default=True,
    help="Extraction mode: original (lossless stream) or decoded (converted).",
)
@click.option(
    "--to",
    "to_format",
    type=click.Choice(["png", "jpeg", "webp", "tiff"], case_sensitive=False),
    default="png",
    show_default=True,
    help="Output image format when using --mode decoded.",
)
@click.option(
    "--quality",
    type=click.IntRange(1, 95),
    default=85,
    show_default=True,
    help="Image quality for JPEG/WebP formats.",
)
@click.option(
    "--asset",
    "asset_ids",
    multiple=True,
    help="Filter extraction to specific asset ID(s).",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Allow overwriting existing files in directory.",
)
@click.pass_context
def extract_cmd(
    ctx: click.Context,
    input_path: Path,
    output_dir: Path,
    pages_range: str | None,
    mode: str,
    to_format: str,
    quality: int,
    asset_ids: tuple[str, ...],
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Extract embedded images to a directory with a structured manifest.json."""
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
        service = ImageService()
        result = service.extract_images(
            input_path=input_path,
            output_dir=output_dir,
            pages_range=pages_range,
            mode=mode,
            to_format=to_format,
            quality=quality,
            asset_ids=list(asset_ids) if asset_ids else None,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(command="images extract", status="ok", data=result, elapsed_ms=elapsed_ms)
            return

        if not opts.quiet:
            presenter.render_success(
                f"Extracted [bold]{result['total_extracted']}[/bold] image(s) ({mode} mode) "
                f"into [bold]{output_dir}[/bold] (manifest: manifest.json)"
            )
        ctx.exit(ExitCode.SUCCESS)
    except PDFToolsError as err:
        if opts.json:
            render_json(command="images extract", status="error", errors=[err.as_detail()])
        else:
            presenter.render_error(err)
            if opts.debug:
                import traceback

                traceback.print_exc(file=sys.stderr)
        ctx.exit(int(err.exit_code))
