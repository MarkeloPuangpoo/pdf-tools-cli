"""CLI command for multi-source PDF assembly conforming to PLAN.md §12.3 C06 (CMD-008)."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.assembly import AssemblyService


@click.command("assemble", help="Assemble a new PDF from multiple source PDFs and page ranges.")
@click.option(
    "--source",
    "sources",
    multiple=True,
    type=(click.Path(exists=True, dir_okay=False, path_type=Path), str),
    required=True,
    help="Source PDF path and page range (e.g. --source doc.pdf 1-5). Can be repeated.",
)
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output destination path for the assembled PDF.",
)
@click.option(
    "--document-policy",
    type=click.Choice(["none", "first"], case_sensitive=False),
    default="none",
    show_default=True,
    help="Metadata and outline transfer policy across sources.",
)
@click.option("--overwrite", is_flag=True, default=False, help="Overwrite existing output file.")
@click.pass_context
def assemble_cmd(
    ctx: click.Context,
    sources: tuple[tuple[Path, str], ...],
    output_path: Path,
    document_policy: str,
    overwrite: bool,
) -> None:
    """Assemble a new PDF from multiple source PDFs and page ranges."""
    global_opts = ctx.obj.get("options", GlobalOptions()) if ctx.obj else GlobalOptions()

    try:
        service = AssemblyService()
        result = service.assemble(
            sources=list(sources),
            output_path=output_path,
            document_policy=document_policy,
            overwrite=overwrite,
        )

        if global_opts.json:
            render_json(command="assemble", status="ok", data=result)
        elif not global_opts.quiet:
            presenter = HumanPresenter()
            presenter.render_success(
                f"Assembled {result['total_pages']} page(s) into [bold]{output_path}[/bold] "
                f"from {len(sources)} source(s)."
            )
        ctx.exit(ExitCode.SUCCESS)
    except PDFToolsError as err:
        if global_opts.json:
            render_json(command="assemble", status="error", errors=[err.as_detail()])
        else:
            presenter = HumanPresenter()
            presenter.render_error(err)
            if global_opts.debug:
                import traceback

                traceback.print_exc(file=sys.stderr)
        ctx.exit(int(err.exit_code))
