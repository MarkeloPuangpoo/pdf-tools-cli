"""Metadata inspection CLI commands conforming to PLAN.md §12.6 C31 (CMD-007)."""

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
from pdftoolscli.services.metadata import MetadataService


@click.group("metadata")
def metadata_group() -> None:
    """Inspect and manage document metadata, Info dictionary, and XMP packets."""


@metadata_group.command("show")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--source",
    type=click.Choice(["all", "info", "xmp"], case_sensitive=False),
    default="all",
    help="Metadata source to display: all, info, or xmp (default: all).",
)
@click.option(
    "--raw-xmp",
    is_flag=True,
    default=False,
    help="Output unprocessed raw XMP XML stream directly to stdout.",
)
@click.option("--password-file", type=click.Path(exists=True), help="Read password from file.")
@click.option("--password-env", metavar="VAR", help="Read password from environment variable.")
@click.option(
    "--password-stdin", is_flag=True, default=False, help="Read password from standard input."
)
@click.pass_context
def show_metadata_cmd(
    ctx: click.Context,
    input_path: Path,
    source: str,
    raw_xmp: bool,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
) -> None:
    """Inspect document Info dictionary, XMP metadata streams, and discrepancies."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    try:
        if raw_xmp and opts.json:
            raise PDFToolsError(
                "Cannot combine '--raw-xmp' and '--json'. Raw XMP outputs pure XML to stdout.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
                hint="Choose either '--raw-xmp' for XML or '--json' for structured JSON.",
            )

        password = resolve_password_source(
            password_file=password_file,
            password_env=password_env,
            password_stdin=password_stdin,
            prompt_if_tty=False,
        )

        service = MetadataService()

        if raw_xmp:
            raw_xml = service.get_raw_xmp(input_path, password=password)
            if raw_xml:
                sys.stdout.write(raw_xml)
                if not raw_xml.endswith("\n"):
                    sys.stdout.write("\n")
                sys.stdout.flush()
            else:
                if not opts.quiet:
                    presenter.stdout_console.print(
                        f"[yellow]Notice:[/yellow] Document '{input_path.name}' "
                        "has no XMP metadata stream."
                    )
            return

        result = service.show(
            input_path=input_path,
            source=source,
            password=password,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        if opts.json:
            render_json(
                command="metadata show",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            # 1. Info table
            if result.get("info"):
                info_table = Table(
                    title=f"Info Dictionary ({input_path.name})",
                    show_header=True,
                    header_style="bold cyan",
                )
                info_table.add_column("Key", style="dim", width=22)
                info_table.add_column("Value")

                for k, v in result["info"].items():
                    if isinstance(v, dict):
                        val_str = f"{v.get('raw')} (normalized: {v.get('normalized')})"
                    else:
                        val_str = str(v)
                    info_table.add_row(k, val_str)

                presenter.stdout_console.print(info_table)

            # 2. XMP table
            if result.get("xmp"):
                xmp_table = Table(
                    title=f"XMP Metadata ({input_path.name})",
                    show_header=True,
                    header_style="bold cyan",
                )
                xmp_table.add_column("Property", style="dim", width=26)
                xmp_table.add_column("Value")

                for k, v in result["xmp"].items():
                    val_str = ", ".join(v) if isinstance(v, list) else str(v)
                    xmp_table.add_row(k, val_str)

                presenter.stdout_console.print(xmp_table)

            # 3. Discrepancies
            discrepancies = result.get("discrepancies", [])
            if discrepancies:
                d_table = Table(
                    title="[bold yellow]Metadata Discrepancies (Info vs XMP)[/bold yellow]",
                    show_header=True,
                    header_style="bold yellow",
                )
                d_table.add_column("Field", width=18)
                d_table.add_column("Info Value")
                d_table.add_column("XMP Value")

                for d in discrepancies:
                    d_table.add_row(d["field"], d["info_value"], d["xmp_value"])

                presenter.stdout_console.print(d_table)

    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="metadata show",
                status="error",
                errors=[err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(err)
        ctx.exit(int(err.exit_code))
    except Exception as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        u_err = PDFToolsError(
            str(err),
            code="E_INTERNAL",
            exit_code=ExitCode.INTERNAL_ERROR,
        )
        if opts.json:
            render_json(
                command="metadata show",
                status="error",
                errors=[u_err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(u_err)
        ctx.exit(int(ExitCode.INTERNAL_ERROR))
