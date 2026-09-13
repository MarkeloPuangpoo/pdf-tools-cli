"""CLI commands for PDF annotation management conforming to PLAN.md §12.7 C42-C43 (CMD-014)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click
from rich.table import Table

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.annotations import AnnotationsService


@click.group(name="annotations")
def annotations_group() -> None:
    """Inspect and remove non-widget annotations (highlights, text notes, popups, links)."""


@annotations_group.command(name="list")
@click.argument("input", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--pages",
    default="all",
    help="Page range specification (default: all).",
)
@click.option(
    "--include-content",
    is_flag=True,
    default=False,
    help="Include annotation body text, author, and modification date.",
)
@click.option(
    "--password",
    default=None,
    envvar="PDFTOOLS_PASSWORD",
    help="Document password for encrypted inputs.",
)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    input: Path,
    pages: str,
    include_content: bool,
    password: str | None,
) -> None:
    """List page annotations with stable IDs, subtypes, bounding rectangles, and flags."""
    opts = ctx.obj.get("options") if ctx.obj else None
    if not isinstance(opts, GlobalOptions):
        opts = GlobalOptions()
    presenter = HumanPresenter(color=opts.color)
    start_time = time.monotonic()

    try:
        resolved_pw = resolve_password_source(password)
        service = AnnotationsService()
        items = service.list_annotations(
            input_path=input,
            page_selection=pages,
            include_content=include_content,
            password=resolved_pw,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="annotations list",
                status="ok",
                data={"annotations": items, "count": len(items)},
                elapsed_ms=elapsed_ms,
            )
        else:
            if not items:
                presenter.render_data(f"No annotations found in '{input}'.")
                return

            table = Table(title=f"Annotations in {input.name} ({len(items)} found)")
            table.add_column("ID", style="cyan")
            table.add_column("Page", justify="right")
            table.add_column("Subtype", style="green")
            table.add_column("Rect [LLX, LLY, URX, URY]")
            table.add_column("Flags", justify="right")

            if include_content:
                table.add_column("Author", style="yellow")
                table.add_column("Content")

            for item in items:
                rect_str = (
                    f"[{item['rect'][0]:.1f}, {item['rect'][1]:.1f}, "
                    f"{item['rect'][2]:.1f}, {item['rect'][3]:.1f}]"
                )
                row = [
                    item["id"],
                    str(item["page"]),
                    item["subtype"],
                    rect_str,
                    str(item["flags"]),
                ]
                if include_content:
                    row.append(item.get("author") or "")
                    row.append((item.get("content") or "").replace("\n", " ")[:60])

                table.add_row(*row)

            presenter.stdout_console.print(table)
    except (click.exceptions.Exit, SystemExit):
        raise
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="annotations list",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)


@annotations_group.command(name="remove")
@click.argument("input", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--all",
    "all_annotations",
    is_flag=True,
    default=False,
    help="Remove all non-widget annotations across selected pages.",
)
@click.option(
    "--type",
    "types",
    multiple=True,
    help="Annotation subtype to remove (e.g. Text, Highlight). Repeatable.",
)
@click.option(
    "--id",
    "ids",
    multiple=True,
    help="Specific annotation ID to remove (e.g. ann-p1-0). Repeatable.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Output PDF destination path.",
)
@click.option(
    "--pages",
    default="all",
    help="Page range specification (default: all).",
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
def remove_cmd(
    ctx: click.Context,
    input: Path,
    all_annotations: bool,
    types: tuple[str, ...],
    ids: tuple[str, ...],
    output_path: Path,
    pages: str,
    password: str | None,
    overwrite: bool,
) -> None:
    """Remove matching non-widget annotations and reconcile popup/reply linkages."""
    opts = ctx.obj.get("options") if ctx.obj else None
    if not isinstance(opts, GlobalOptions):
        opts = GlobalOptions()
    presenter = HumanPresenter(color=opts.color)
    start_time = time.monotonic()

    try:
        resolved_pw = resolve_password_source(password)
        service = AnnotationsService()
        result = service.remove_annotations(
            input_path=input,
            output_path=output_path,
            all_annotations=all_annotations,
            types=list(types) if types else None,
            ids=list(ids) if ids else None,
            page_selection=pages,
            password=resolved_pw,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="annotations remove",
                status="ok",
                data=result,
                elapsed_ms=elapsed_ms,
            )
        else:
            if not opts.quiet:
                msg = (
                    f"Successfully removed {result['removed_count']} annotation(s) across "
                    f"{result['pages_affected']} page(s) ({result['widgets_preserved']} widget(s) "
                    f"preserved): '{result['output']}'."
                )
                presenter.render_success(msg)
    except (click.exceptions.Exit, SystemExit):
        raise
    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="annotations remove",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        sys.exit(err.exit_code)
