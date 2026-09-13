"""CLI command for inserting pages into a base PDF conforming to PLAN.md §12.3 C07 (CMD-008)."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.assembly import AssemblyService


@click.command("insert", help="Insert a sequence of pages from a secondary PDF into a base PDF.")
@click.argument("base_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("insert_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--after",
    "after_page",
    required=True,
    help="Target anchor page in base PDF: 0 (before first page), positive page number, or 'last'.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output destination path for the updated PDF.",
)
@click.option(
    "--pages",
    "pages_range",
    default="all",
    show_default=True,
    help="Page range to extract from secondary PDF to insert.",
)
@click.option("--overwrite", is_flag=True, default=False, help="Overwrite existing output file.")
@click.pass_context
def insert_cmd(
    ctx: click.Context,
    base_path: Path,
    insert_path: Path,
    after_page: str,
    output_path: Path,
    pages_range: str,
    overwrite: bool,
) -> None:
    """Insert a sequence of pages from secondary PDF into base PDF at designated anchor."""
    global_opts = ctx.obj.get("options", GlobalOptions()) if ctx.obj else GlobalOptions()

    try:
        service = AssemblyService()
        result = service.insert(
            base_path=base_path,
            insert_path=insert_path,
            after_page=after_page,
            output_path=output_path,
            pages_range=pages_range,
            overwrite=overwrite,
        )

        if global_opts.json:
            render_json(command="insert", status="ok", data=result)
        elif not global_opts.quiet:
            presenter = HumanPresenter()
            presenter.render_success(
                f"Inserted {result['inserted_pages_count']} page(s) after page '{after_page}' "
                f"into [bold]{output_path}[/bold] (total pages: {result['total_pages']})."
            )
        ctx.exit(ExitCode.SUCCESS)
    except PDFToolsError as err:
        if global_opts.json:
            render_json(command="insert", status="error", errors=[err.as_detail()])
        else:
            presenter = HumanPresenter()
            presenter.render_error(err)
            if global_opts.debug:
                import traceback

                traceback.print_exc(file=sys.stderr)
        ctx.exit(int(err.exit_code))
