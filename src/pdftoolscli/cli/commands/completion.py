"""Shell completion script generator conforming to PLAN.md §10, CLI-002."""

from __future__ import annotations

import sys

import click
from click.shell_completion import get_completion_class

from pdftoolscli.domain.errors import ConfigError

SUPPORTED_SHELLS = ("bash", "zsh", "fish", "powershell")


@click.command("completion")
@click.argument("shell", type=click.Choice(list(SUPPORTED_SHELLS), case_sensitive=False))
@click.pass_context
def completion_cmd(ctx: click.Context, shell: str) -> None:
    """Generate tab-completion script for the specified shell (bash, zsh, fish, powershell)."""
    # Reject --json flag on completion command per PLAN.md CLI-002
    root_obj = ctx.find_root().obj or {}
    global_opts = root_obj.get("options")
    if (global_opts and global_opts.json) or "--json" in sys.argv:
        raise click.UsageError(
            "The '--json' flag is not supported for shell completion generation."
        )

    shell_name = shell.lower()
    comp_cls = get_completion_class(shell_name)
    if comp_cls is None:
        raise ConfigError(
            f"Unsupported shell: '{shell}'. Supported shells: {', '.join(SUPPORTED_SHELLS)}."
        )

    # Click completion class uses root command
    root_cmd = ctx.find_root().command
    comp_obj_ptc = comp_cls(root_cmd, ctx_args={}, prog_name="ptc", complete_var="_PTC_COMPLETE")
    comp_obj_pdf = comp_cls(
        root_cmd,
        ctx_args={},
        prog_name="pdftoolscli",
        complete_var="_PDFTOOLSCLI_COMPLETE",
    )

    # Generate source script for both aliases
    script_ptc = comp_obj_ptc.source()
    script_pdf = comp_obj_pdf.source()
    combined_script = f"{script_ptc}\n\n{script_pdf}"

    click.echo(combined_script)

    # Informational instructions on stderr
    hints = {
        "bash": 'eval "$(_PTC_COMPLETE=bash_source ptc)"',
        "zsh": 'eval "$(_PTC_COMPLETE=zsh_source ptc)"',
        "fish": "ptc completion fish | source",
        "powershell": "ptc completion powershell | Out-String | Invoke-Expression",
    }
    hint = hints.get(shell_name, f"ptc completion {shell_name}")
    sys.stderr.write(f"# To activate {shell_name} completion, run:\n# {hint}\n")
