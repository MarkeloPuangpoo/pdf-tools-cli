"""Encryption and decryption CLI commands conforming to PLAN.md §12.6 C35, C36 (CMD-004)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import click

from pdftoolscli.cli.options import GlobalOptions
from pdftoolscli.config.secrets import resolve_password_source
from pdftoolscli.domain.errors import ExitCode, PDFToolsError
from pdftoolscli.presentation.human import HumanPresenter
from pdftoolscli.presentation.json import render_json
from pdftoolscli.services.encryption import EncryptionService


# ---------------------------------------------------------------------------
# C35: encrypt
# ---------------------------------------------------------------------------
@click.command("encrypt")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination encrypted PDF file.",
)
@click.option(
    "--owner-password-file",
    type=click.Path(exists=True),
    help="Read owner password from file.",
)
@click.option(
    "--owner-password-env",
    metavar="VAR",
    help="Read owner password from environment variable.",
)
@click.option(
    "--owner-password-stdin",
    is_flag=True,
    default=False,
    help="Read owner password from standard input.",
)
@click.option(
    "--user-password-file",
    type=click.Path(exists=True),
    help="Read user password from file.",
)
@click.option(
    "--user-password-env",
    metavar="VAR",
    help="Read user password from environment variable.",
)
@click.option(
    "--user-password-stdin",
    is_flag=True,
    default=False,
    help="Read user password from standard input.",
)
@click.option(
    "--allow-empty-user",
    is_flag=True,
    default=False,
    help="Allow empty user password (document opens without password but retains owner security).",
)
@click.option(
    "--print",
    "print_permission",
    type=click.Choice(["full", "low", "none"], case_sensitive=False),
    default="full",
    help="Printing permission level (default: full).",
)
@click.option(
    "--modify",
    "modify_permission",
    type=click.Choice(["all", "annotate", "form", "none"], case_sensitive=False),
    default="all",
    help="Modification permission level (default: all).",
)
@click.option(
    "--copy",
    "copy_permission",
    type=click.Choice(["allow", "deny"], case_sensitive=False),
    default="allow",
    help="Content copying permission (default: allow).",
)
@click.option(
    "--password-file",
    type=click.Path(exists=True),
    help="Input unlock password file (if input is already encrypted).",
)
@click.option(
    "--password-env",
    metavar="VAR",
    help="Input unlock password from environment variable.",
)
@click.option(
    "--password-stdin",
    is_flag=True,
    default=False,
    help="Input unlock password from stdin.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Allow overwriting existing destination files.",
)
@click.pass_context
def encrypt_cmd(
    ctx: click.Context,
    input_path: Path,
    output_path: Path,
    owner_password_file: str | None,
    owner_password_env: str | None,
    owner_password_stdin: bool,
    user_password_file: str | None,
    user_password_env: str | None,
    user_password_stdin: bool,
    allow_empty_user: bool,
    print_permission: str,
    modify_permission: str,
    copy_permission: str,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Encrypt document using AES-256 with granular permissions."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    # Resolve input password if source is encrypted
    input_pw = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=False,
    )

    # Resolve owner password
    owner_pw = resolve_password_source(
        password_file=owner_password_file,
        password_env=owner_password_env,
        password_stdin=owner_password_stdin,
        prompt_if_tty=False,
    )
    if not owner_pw:
        if sys.stdin.isatty():
            owner_pw = click.prompt(
                "Enter owner password", hide_input=True, confirmation_prompt=True
            )
        else:
            raise PDFToolsError(
                "Owner password required for encryption. Provide via --owner-password-* options.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

    # Resolve user password
    user_pw = resolve_password_source(
        password_file=user_password_file,
        password_env=user_password_env,
        password_stdin=user_password_stdin,
        prompt_if_tty=False,
    )
    if not user_pw and not allow_empty_user:
        if sys.stdin.isatty():
            user_pw = click.prompt("Enter user password", hide_input=True, confirmation_prompt=True)
        else:
            raise PDFToolsError(
                "User password required. Provide via --user-password-* or pass --allow-empty-user.",
                code="E_CLI_INVALID_OPTION",
                exit_code=ExitCode.USAGE_OR_SELECTION,
            )

    try:
        service = EncryptionService()
        result = service.encrypt(
            input_path=input_path,
            output_path=output_path,
            owner_password=owner_pw,
            user_password=user_pw,
            allow_empty_user=allow_empty_user,
            print_permission=print_permission,
            modify_permission=modify_permission,
            copy_permission=copy_permission,
            input_password=input_pw,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="encrypt",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Encrypted [bold]{input_path.name}[/bold] "
                f"(AES-256) into [bold]{output_path}[/bold]"
            )

    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="encrypt",
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
                command="encrypt",
                status="error",
                errors=[u_err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(u_err)
        ctx.exit(int(ExitCode.INTERNAL_ERROR))


# ---------------------------------------------------------------------------
# C36: decrypt
# ---------------------------------------------------------------------------
@click.command("decrypt")
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    required=True,
    help="Target destination decrypted PDF file.",
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
    help="Allow overwriting existing destination files.",
)
@click.pass_context
def decrypt_cmd(
    ctx: click.Context,
    input_path: Path,
    output_path: Path,
    password_file: str | None,
    password_env: str | None,
    password_stdin: bool,
    overwrite: bool,
) -> None:
    """Remove encryption security from document using valid credentials."""
    opts: GlobalOptions = ctx.obj.get("options", GlobalOptions())
    presenter = HumanPresenter(color=opts.color, quiet=opts.quiet, verbose=opts.verbose)
    start_time = ctx.obj.get("start_time", time.monotonic())

    password = resolve_password_source(
        password_file=password_file,
        password_env=password_env,
        password_stdin=password_stdin,
        prompt_if_tty=True,
    )

    try:
        service = EncryptionService()
        result = service.decrypt(
            input_path=input_path,
            output_path=output_path,
            password=password,
            overwrite=overwrite,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="decrypt",
                status="success",
                data=result,
                elapsed_ms=elapsed_ms,
            )
            return

        if not opts.quiet:
            presenter.stdout_console.print(
                f"[bold green]✓[/bold green] Decrypted [bold]{input_path.name}[/bold] "
                f"into [bold]{output_path}[/bold]"
            )

    except PDFToolsError as err:
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        if opts.json:
            render_json(
                command="decrypt",
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
                command="decrypt",
                status="error",
                errors=[u_err.as_detail()],
                elapsed_ms=elapsed_ms,
            )
        else:
            presenter.render_error(u_err)
        ctx.exit(int(ExitCode.INTERNAL_ERROR))
