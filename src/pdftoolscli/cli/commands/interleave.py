"""CLI command for round-robin interleaving of PDFs conforming to PLAN.md §12.3 C08 (CMD-008)."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.assembly import AssemblyService


@click.command("interleave", help="Round-robin interleave pages from multiple PDF documents.")
@click.argument(
    "inputs", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
@click.option(
    "-o",
    "--output",
    "output_path",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="Output destination path for the interleaved PDF.",
)
@click.option(
    "--remainder",
    type=click.Choice(["append", "error"], case_sensitive=False),
    default="append",
    show_default=True,
    help="Policy when input documents have unequal page counts: append or error.",
)
@click.option(
    "--reverse-even-inputs",
    is_flag=True,
    default=False,
    help="Reverse page order of even-indexed inputs (2nd, 4th, ...) for duplex scanner merging.",
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
def interleave_cmd(
    ctx: click.Context,
    inputs: tuple[Path, ...],
    output_path: Path,
    remainder: str,
    reverse_even_inputs: bool,
    document_policy: str,
    overwrite: bool,
) -> None:
    """Round-robin interleave pages from multiple PDF documents."""
    global_opts = ctx.obj.get("options", GlobalOptions()) if ctx.obj else GlobalOptions()

    try:
        service = AssemblyService()
        result = service.interleave(
            input_paths=list(inputs),
            output_path=output_path,
            remainder=remainder,
            reverse_even_inputs=reverse_even_inputs,
            document_policy=document_policy,
            overwrite=overwrite,
        )

        if global_opts.json:
            render_json(command="interleave", status="ok", data=result)
        elif not global_opts.quiet:
            presenter = HumanPresenter()
            presenter.render_success(
                f"Interleaved {result['total_pages']} page(s) across {len(inputs)} input(s) "
                f"into [bold]{output_path}[/bold]."
            )
        ctx.exit(ExitCode.SUCCESS)
    except PDFToolsError as err:
        if global_opts.json:
            render_json(command="interleave", status="error", errors=[err.as_detail()])
        else:
            presenter = HumanPresenter()
            presenter.render_error(err)
            if global_opts.debug:
                import traceback

                traceback.print_exc(file=sys.stderr)
        ctx.exit(int(err.exit_code))
