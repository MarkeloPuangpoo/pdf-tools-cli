"""Pages command group conforming to PLAN.md §12.3 (C10-C14)."""

from __future__ import annotations

import time
from pathlib import Path

import click

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.pages import PageService


@click.group("pages")
def pages_group() -> None:
    """Manipulate document pages, topology, ordering, and rotation."""


def _handle_error(
    ctx: click.Context,
    err: Exception,
    command: str,
    opts: GlobalOptions,
    presenter: HumanPresenter,
    start_time: float,
) -> None:
    elapsed_ms = int((time.monotonic() - start_time) * 1000)
    if isinstance(err, PDFToolsError):
        if opts.json:
            render_json(
                command=command,
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        ctx.exit(int(err.exit_code))
    else:
        u_err = PDFToolsError(
            str(err),
            code="E_INTERNAL",
            exit_code=ExitCode.INTERNAL_ERROR,
        )
        if opts.json:
            render_json(
                command=command,
                status="error",
                errors=[u_err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(u_err)
        ctx.exit(int(ExitCode.INTERNAL_ERROR))


# ---------------------------------------------------------------------------
# C10: pages extract
# ---------------------------------------------------------------------------
@pages_group.command("extract")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("range_expr", type=str)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination PDF file.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Allow overwriting existing destination files."
)
@click.pass_context
def extract_cmd(
    ctx: click.Context,
    input_path: Path,
    range_expr: str,
    output_path: Path,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Extract specified sequence of pages into a new PDF document."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        service = PageService()
        result = service.extract(
            input_path=input_path,
            range_expr=range_expr,
            output_path=output_path,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="pages extract",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Extracted [bold]{result['page_count']}[/bold] pages "
                f"from [bold]{input_path.name}[/bold] to [bold]{output_path}[/bold]"
            )
    except Exception as err:
        _handle_error(ctx, err, "pages extract", opts, presenter, start_time)


# ---------------------------------------------------------------------------
# C11: pages remove
# ---------------------------------------------------------------------------
@pages_group.command("remove")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("range_expr", type=str)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination PDF file.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Allow overwriting existing destination files."
)
@click.pass_context
def remove_cmd(
    ctx: click.Context,
    input_path: Path,
    range_expr: str,
    output_path: Path,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Remove specified page selection from document."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        service = PageService()
        result = service.remove(
            input_path=input_path,
            range_expr=range_expr,
            output_path=output_path,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="pages remove",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Removed [bold]{result['removed_count']}[/bold] pages. "
                f"Remaining [bold]{result['remaining_count']}[/bold] pages "
                f"written to [bold]{output_path}[/bold]"
            )
    except Exception as err:
        _handle_error(ctx, err, "pages remove", opts, presenter, start_time)


# ---------------------------------------------------------------------------
# C12: pages reorder
# ---------------------------------------------------------------------------
@pages_group.command("reorder")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("order_expr", type=str)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination PDF file.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Allow overwriting existing destination files."
)
@click.pass_context
def reorder_cmd(
    ctx: click.Context,
    input_path: Path,
    order_expr: str,
    output_path: Path,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Reorder pages according to a complete permutation."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        service = PageService()
        result = service.reorder(
            input_path=input_path,
            order_expr=order_expr,
            output_path=output_path,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="pages reorder",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Reordered [bold]{result['page_count']}[/bold] pages "
                f"in [bold]{output_path}[/bold]"
            )
    except Exception as err:
        _handle_error(ctx, err, "pages reorder", opts, presenter, start_time)


# ---------------------------------------------------------------------------
# C13: pages reverse
# ---------------------------------------------------------------------------
@pages_group.command("reverse")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination PDF file.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Allow overwriting existing destination files."
)
@click.pass_context
def reverse_cmd(
    ctx: click.Context,
    input_path: Path,
    output_path: Path,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Reverse entire physical page sequence."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        service = PageService()
        result = service.reverse(
            input_path=input_path,
            output_path=output_path,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="pages reverse",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Reversed [bold]{result['page_count']}[/bold] pages "
                f"into [bold]{output_path}[/bold]"
            )
    except Exception as err:
        _handle_error(ctx, err, "pages reverse", opts, presenter, start_time)


# ---------------------------------------------------------------------------
# C14: pages rotate
# ---------------------------------------------------------------------------
@pages_group.command("rotate")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("angle", type=int)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination PDF file.",
)
@click.option(
    "--pages",
    "pages_range",
    type=str,
    default=None,
    help="Range expression of pages to rotate (defaults to all pages).",
)
@click.option(
    "--absolute",
    is_flag=True,
    default=False,
    help="Set rotation angle absolutely instead of adding to existing rotation.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Allow overwriting existing destination files."
)
@click.pass_context
def rotate_cmd(
    ctx: click.Context,
    input_path: Path,
    angle: int,
    output_path: Path,
    pages_range: str | None,
    absolute: bool,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Rotate selected document pages by a multiple of 90 degrees."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        service = PageService()
        result = service.rotate(
            input_path=input_path,
            angle=angle,
            output_path=output_path,
            range_expr=pages_range,
            absolute=absolute,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="pages rotate",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            mode_str = "absolute" if absolute else "relative"
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Rotated [bold]{result['rotated_pages_count']}[/bold] "
                f"pages by [bold]{result['angle']}°[/bold] ({mode_str}) "
                f"into [bold]{output_path}[/bold]"
            )
    except Exception as err:
        _handle_error(ctx, err, "pages rotate", opts, presenter, start_time)


# ---------------------------------------------------------------------------
# C15: pages duplicate
# ---------------------------------------------------------------------------
@pages_group.command("duplicate")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("range_expr", type=str)
@click.option(
    "--after",
    "after_page",
    required=True,
    help="Target anchor page: 0 (before first), 'last', or 1-based page number.",
)
@click.option(
    "--copies",
    type=int,
    default=1,
    show_default=True,
    help="Number of times to duplicate the page sequence.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination PDF file.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Allow overwriting existing destination files."
)
@click.pass_context
def duplicate_cmd(
    ctx: click.Context,
    input_path: Path,
    range_expr: str,
    after_page: str,
    output_path: Path,
    copies: int,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Duplicate a sequence of pages N times at a designated anchor."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        service = PageService()
        result = service.duplicate(
            input_path=input_path,
            range_expr=range_expr,
            after_page=after_page,
            output_path=output_path,
            copies=copies,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="pages duplicate",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Duplicated {result['duplicated_pages_count']} "
                f"page(s) ({copies} copy/copies) into [bold]{output_path}[/bold] "
                f"(total pages: {result['total_pages']})"
            )
    except Exception as err:
        _handle_error(ctx, err, "pages duplicate", opts, presenter, start_time)


# ---------------------------------------------------------------------------
# C16: pages crop
# ---------------------------------------------------------------------------
@pages_group.command("crop")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--margins",
    required=True,
    help="Crop margins LEFT,TOP,RIGHT,BOTTOM with units pt/mm/in (e.g. 10mm,10mm,10mm,10mm).",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination PDF file.",
)
@click.option(
    "--pages",
    "pages_range",
    default=None,
    help="Page range to crop (default: all).",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Allow overwriting existing destination files."
)
@click.pass_context
def crop_cmd(
    ctx: click.Context,
    input_path: Path,
    margins: str,
    output_path: Path,
    pages_range: str | None,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Apply margin offsets to displayed CropBox coordinates of selected pages."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        service = PageService()
        result = service.crop(
            input_path=input_path,
            margins_str=margins,
            output_path=output_path,
            range_expr=pages_range,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="pages crop",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Cropped [bold]{result['cropped_pages_count']}[/bold] "
                f"page(s) with margins [bold]{margins}[/bold] into [bold]{output_path}[/bold]"
            )
    except Exception as err:
        _handle_error(ctx, err, "pages crop", opts, presenter, start_time)


# ---------------------------------------------------------------------------
# C17: pages resize
# ---------------------------------------------------------------------------
@pages_group.command("resize")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--size",
    required=True,
    help="Target dimensions: A4, Letter, or WIDTHxHEIGHT with units (e.g. 210mmx297mm).",
)
@click.option(
    "--fit",
    type=click.Choice(["none", "contain"], case_sensitive=False),
    default="none",
    show_default=True,
    help="Fit mode: none (re-canvas) or contain (uniform scaling).",
)
@click.option(
    "--anchor",
    default="center",
    show_default=True,
    help="Canvas placement anchor (default: center).",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination PDF file.",
)
@click.option(
    "--pages",
    "pages_range",
    default=None,
    help="Page range to resize (default: all).",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Allow overwriting existing destination files."
)
@click.pass_context
def resize_cmd(
    ctx: click.Context,
    input_path: Path,
    size: str,
    fit: str,
    anchor: str,
    output_path: Path,
    pages_range: str | None,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Resize selected pages to standard dimensions or explicit width/height."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        service = PageService()
        result = service.resize(
            input_path=input_path,
            size_str=size,
            output_path=output_path,
            fit=fit,
            anchor=anchor,
            range_expr=pages_range,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="pages resize",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Resized [bold]{result['resized_pages_count']}[/bold] "
                f"page(s) to [bold]{size}[/bold] (fit: {fit}) into [bold]{output_path}[/bold]"
            )
    except Exception as err:
        _handle_error(ctx, err, "pages resize", opts, presenter, start_time)


# ---------------------------------------------------------------------------
# C18: pages boxes
# ---------------------------------------------------------------------------
@pages_group.command("boxes")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--set",
    "set_boxes",
    multiple=True,
    required=True,
    help="Set unrotated box coordinates: BOX=LLX,LLY,URX,URY (e.g. crop=0pt,0pt,500pt,700pt).",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination PDF file.",
)
@click.option(
    "--pages",
    "pages_range",
    default=None,
    help="Page range to update boxes on (default: all).",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.option(
    "--overwrite", is_flag=True, default=False, help="Allow overwriting existing destination files."
)
@click.pass_context
def boxes_cmd(
    ctx: click.Context,
    input_path: Path,
    set_boxes: tuple[str, ...],
    output_path: Path,
    pages_range: str | None,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """View or set raw unrotated PDF bounding boxes (media, crop, trim, bleed, art)."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    try:
        parsed_boxes: list[tuple[str, str]] = []
        for item in set_boxes:
            if "=" not in item:
                raise PDFToolsError(
                    f"Invalid --set format '{item}'. Expected format: BOX=LLX,LLY,URX,URY.",
                    code="E_CLI_INVALID_OPTION",
                    exit_code=ExitCode.USAGE_OR_SELECTION,
                )
            b_name, coords = item.split("=", 1)
            parsed_boxes.append((b_name.strip(), coords.strip()))

        service = PageService()
        result = service.boxes(
            input_path=input_path,
            set_boxes=parsed_boxes,
            output_path=output_path,
            range_expr=pages_range,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="pages boxes",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Updated page boxes on "
                f"[bold]{result['modified_pages_count']}[/bold] page(s) "
                f"into [bold]{output_path}[/bold]"
            )

    except Exception as err:
        _handle_error(ctx, err, "pages boxes", opts, presenter, start_time)
