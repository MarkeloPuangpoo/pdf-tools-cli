"""Global CLI options and mutual exclusion validations conforming to PLAN.md §10, §16."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pdftoolscli.domain.errors import ConfigError


@dataclass(frozen=True)
class GlobalOptions:
    """Parsed global options container."""

    ui: bool = False
    json: bool = False
    quiet: bool = False
    verbose: bool = False
    debug: bool = False
    color: str = "auto"
    config: str | None = None
    no_config: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GlobalOptions:
        color_val = "auto"
        if data.get("color"):
            color_val = "always"
        elif data.get("no_color"):
            color_val = "never"

        return cls(
            ui=bool(data.get("ui", False)),
            json=bool(data.get("json", False)),
            quiet=bool(data.get("quiet", False)),
            verbose=bool(data.get("verbose", False)),
            debug=bool(data.get("debug", False)),
            color=color_val,
            config=data.get("config"),
            no_config=bool(data.get("no_config", False)),
        )


def validate_mutual_exclusions(
    json_mode: bool = False,
    quiet: bool = False,
    color: bool = False,
    no_color: bool = False,
    config: str | None = None,
    no_config: bool = False,
) -> None:
    """Validate that mutually exclusive global flags are not used simultaneously."""
    if json_mode and quiet:
        raise ConfigError(
            "Cannot combine '--json' and '--quiet'. JSON mode requires structured output.",
            hint="Choose either '--json' for machine output or '--quiet' for silent mode.",
        )

    if color and no_color:
        raise ConfigError(
            "Cannot combine '--color' and '--no-color'.",
            hint="Choose either '--color' to force color or '--no-color' to disable it.",
        )

    if config and no_config:
        raise ConfigError(
            "Cannot combine '--config' and '--no-config'.",
            hint="Remove '--no-config' to use the specified configuration file.",
        )
