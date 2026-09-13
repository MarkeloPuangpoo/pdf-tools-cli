"""Root Click entrypoint, global options, and top-level exception boundary.

Conforms to PLAN.md §10, §16, §17.
"""

from __future__ import annotations

import sys
import time
import traceback

import click

from pdftoolscli import __version__
from pdftoolscli.cli.options import GlobalOptions, validate_mutual_exclusions
from pdftoolscli.cli.registry import LazyGroup
from pdftoolscli.config.load import load_config
from pdftoolscli.config.secrets import assert_no_raw_password_cli_argument
from pdftoolscli.domain.errors import (
    ErrorDetail,
    ExitCode,
    PDFToolsError,
)
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json


@click.group(
    cls=LazyGroup,
    invoke_without_command=True,
    context_settings={"help_option_names": ["--help"]},
)
@click.option("--ui", is_flag=True, default=False, help="Launch interactive Terminal UI mode.")
@click.option(
    "--json", "json_mode", is_flag=True, default=False, help="Emit output as JSON v1 on stdout."
)
@click.option("-q", "--quiet", is_flag=True, default=False, help="Quiet mode: suppress non-errors.")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Enable verbose diagnostics.")
@click.option("--debug", is_flag=True, default=False, help="Include stack tracebacks on error.")
@click.option("--color", is_flag=True, default=False, help="Force colored terminal output.")
@click.option("--no-color", is_flag=True, default=False, help="Disable colored terminal output.")
@click.option(
    "--config", "config_path", type=click.Path(exists=False), help="Path to configuration file."
)
@click.option(
    "--no-config", is_flag=True, default=False, help="Disable loading configuration files."
)
@click.version_option(__version__, "-V", "--version", message="pdftoolscli %(version)s")
@click.pass_context
def cli(
    ctx: click.Context,
    ui: bool,
    json_mode: bool,
    quiet: bool,
    verbose: bool,
    debug: bool,
    color: bool,
    no_color: bool,
    config_path: str | None,
    no_config: bool,
) -> None:
    """PDF Tools CLI (ptc) — Fast, safe, offline PDF toolkit."""
    try:
        validate_mutual_exclusions(
            json_mode=json_mode,
            quiet=quiet,
            color=color,
            no_color=no_color,
            config=config_path,
            no_config=no_config,
        )

        color_choice = "auto"
        if color:
            color_choice = "always"
        elif no_color:
            color_choice = "never"

        # Store resolved global options in context
        global_opts = GlobalOptions(
            ui=ui,
            json=json_mode,
            quiet=quiet,
            verbose=verbose,
            debug=debug,
            color=color_choice,
            config=config_path,
            no_config=no_config,
        )
        ctx.ensure_object(dict)
        ctx.obj["options"] = global_opts
        ctx.obj["start_time"] = time.monotonic()

        # Load effective configuration
        cfg = load_config(
            explicit_config_path=config_path,
            no_config=no_config,
            cli_overrides={
                "color": color_choice if (color or no_color) else None,
                "quiet": quiet,
                "json": json_mode,
            },
        )
        ctx.obj["config"] = cfg

        # If no subcommand was supplied:
        if ctx.invoked_subcommand is None:
            # Check if interactive TUI was requested or bare command run in interactive TTY
            is_interactive_tty = sys.stdin.isatty() and sys.stdout.isatty()
            if ui or is_interactive_tty:
                from pdftoolscli.presentation.tui import launch_tui

                code = launch_tui()
                ctx.exit(code)
            else:
                # Non-interactive / CI / pipe fallback: print standard help
                click.echo(ctx.get_help())
                ctx.exit(0)
    except PDFToolsError as e:
        if json_mode:
            render_json(
                command="root",
                status="error",
                errors=[e.as_detail()],
            )
        else:
            presenter = HumanPresenter()
            presenter.render_error(e)
            if debug:
                traceback.print_exc(file=sys.stderr)
        ctx.exit(int(e.exit_code))


# Register subcommands lazily
cli.add_lazy_command("completion", "pdftoolscli.cli.commands.completion:completion_cmd")
cli.add_lazy_command("inspect", "pdftoolscli.cli.commands.inspect:inspect_cmd")
cli.add_lazy_command("validate", "pdftoolscli.cli.commands.validate:validate_cmd")
cli.add_lazy_command("doctor", "pdftoolscli.cli.commands.doctor:doctor_cmd")
cli.add_lazy_command("split", "pdftoolscli.cli.commands.split:split_cmd")
cli.add_lazy_command("pages", "pdftoolscli.cli.commands.pages:pages_group")
cli.add_lazy_command("merge", "pdftoolscli.cli.commands.merge:merge_cmd")
cli.add_lazy_command("encrypt", "pdftoolscli.cli.commands.encryption:encrypt_cmd")
cli.add_lazy_command("decrypt", "pdftoolscli.cli.commands.encryption:decrypt_cmd")
cli.add_lazy_command("optimize", "pdftoolscli.cli.commands.optimize:optimize_cmd")


def main() -> None:
    """Top-level executable boundary catching all unhandled exceptions and routing outputs."""
    raw_args = sys.argv[1:]
    is_json = "--json" in raw_args
    is_debug = "--debug" in raw_args
    start_time = time.monotonic()

    try:
        # Preflight safety check: assert no raw --password on argv
        assert_no_raw_password_cli_argument(raw_args)

        # Execute Click root group
        cli.main(args=raw_args, standalone_mode=False)
        sys.exit(0)
    except click.ClickException as e:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        exit_code = e.exit_code
        err_detail = ErrorDetail(
            code="E_USAGE",
            category="usage",
            message=e.format_message(),
        )

        if is_json:
            render_json(
                command="root",
                status="error",
                data=None,
                errors=[err_detail],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter = HumanPresenter()
            presenter.render_error(err_detail)
            if is_debug:
                traceback.print_exc(file=sys.stderr)
        sys.exit(exit_code)
    except PDFToolsError as e:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        exit_code = int(e.exit_code)
        err_detail = e.as_detail()

        if is_json:
            render_json(
                command="root",
                status="error",
                data=None,
                errors=[err_detail],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter = HumanPresenter()
            presenter.render_error(err_detail)
            if is_debug:
                traceback.print_exc(file=sys.stderr)
        sys.exit(exit_code)
    except SystemExit as e:
        # Natural exit from Click or subroutines
        code = e.code if isinstance(e.code, int) else 0
        sys.exit(code)
    except KeyboardInterrupt:
        if is_json:
            render_json(
                command="root",
                status="error",
                data=None,
                errors=[
                    ErrorDetail(
                        code="E_CANCELLED",
                        category="cancellation",
                        message="Operation cancelled by user (Ctrl+C).",
                    )
                ],
            )
        else:
            sys.stderr.write("\nOperation cancelled by user (Ctrl+C).\n")
        sys.exit(ExitCode.CANCELLED)
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        exit_code = ExitCode.INTERNAL_ERROR
        err_detail = ErrorDetail(
            code="E_INTERNAL",
            category="internal",
            message=f"Unhandled internal error: {e}",
            hint="Run with --debug to view complete stack traceback.",
        )

        if is_json:
            render_json(
                command="root",
                status="error",
                data=None,
                errors=[err_detail],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter = HumanPresenter()
            presenter.render_error(err_detail)
            if is_debug:
                traceback.print_exc(file=sys.stderr)
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
