"""Hierarchical configuration loader and precedence engine conforming to PLAN.md §27."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

import platformdirs

from pdftoolscli.config.model import (
    BatchConfig,
    CompressConfig,
    Config,
    LimitsConfig,
    OcrConfig,
    OutputConfig,
    PathsConfig,
    Provenance,
    ToolsConfig,
)
from pdftoolscli.domain.errors import ConfigError

PROHIBITED_KEYS = {
    "password",
    "passwords",
    "overwrite",
    "in_place",
    "inplace",
    "signature",
    "signature_acknowledgment",
    "hooks",
    "hook",
    "command",
    "commands",
    "url",
    "urls",
    "network",
    "symlinks",
    "allow_symlinks",
}

VALID_SECTIONS = {
    "output",
    "limits",
    "batch",
    "ocr",
    "compress",
    "paths",
    "tools",
}

VALID_PRESETS = {"screen", "ebook", "printer", "prepress", "archive"}
VALID_COLORS = {"auto", "always", "never"}


def get_default_user_config_path() -> Path:
    """Return the canonical platform user configuration file path."""
    return Path(platformdirs.user_config_dir("pdftoolscli", appauthor=False)) / "config.toml"


def _check_prohibited_and_unknown(raw_dict: dict[str, Any], file_path: Path | None = None) -> None:
    """Validate that raw TOML dict contains no forbidden keys or unknown sections."""
    prefix = f"In {file_path}: " if file_path else ""

    for key, value in raw_dict.items():
        if key == "config_version":
            continue

        if key in PROHIBITED_KEYS:
            raise ConfigError(
                f"{prefix}Prohibited security-sensitive key '{key}' is forbidden in config files."
            )

        if key not in VALID_SECTIONS:
            raise ConfigError(f"{prefix}Unknown configuration section: '{key}'.")

        if isinstance(value, dict):
            for sub_key in value:
                if sub_key in PROHIBITED_KEYS:
                    raise ConfigError(
                        f"{prefix}Prohibited security-sensitive key '{key}.{sub_key}' "
                        "is forbidden in config files."
                    )


def _parse_toml_file(path: Path) -> dict[str, Any]:
    """Safely read and parse a TOML file."""
    if not path.is_file():
        raise ConfigError(f"Configuration file not found: {path}")

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Syntax error in configuration file {path}: {e}") from e
    except OSError as e:
        raise ConfigError(f"Could not read configuration file {path}: {e}") from e

    _check_prohibited_and_unknown(data, file_path=path)
    return data


def load_config(
    explicit_config_path: Path | str | None = None,
    no_config: bool = False,
    cli_overrides: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> Config:
    """Load configuration according to the 5-tier precedence hierarchy:

    Built-in < User Config < Explicit Config < Environment Variables < CLI Options.
    """
    if env is None:
        env = dict(os.environ)

    provenance: dict[str, Provenance] = {}

    # 1. Base built-in defaults
    output = OutputConfig()
    limits = LimitsConfig()
    batch = BatchConfig()
    ocr = OcrConfig()
    compress = CompressConfig()
    paths = PathsConfig()
    tools = ToolsConfig()
    config_version = 1
    loaded_path: Path | None = None

    # Track defaults in provenance
    for section in VALID_SECTIONS:
        provenance[section] = Provenance.DEFAULT

    # Helper to apply dictionary values from a TOML source
    def apply_toml_data(data: dict[str, Any], prov: Provenance, source_path: Path) -> None:
        nonlocal output, limits, batch, ocr, compress, paths, tools, config_version, loaded_path
        loaded_path = source_path

        if "config_version" in data:
            ver = data["config_version"]
            if not isinstance(ver, int) or ver != 1:
                raise ConfigError(f"Unsupported config_version: {ver} (expected 1).")
            config_version = ver
            provenance["config_version"] = prov

        if "output" in data:
            sec = data["output"]
            if not isinstance(sec, dict):
                raise ConfigError("'output' section must be a table.")
            for k in sec:
                if k not in ("color", "progress", "default_json"):
                    raise ConfigError(f"Unknown key in 'output': '{k}'.")

            color = sec.get("color", output.color)
            if color not in VALID_COLORS:
                raise ConfigError(
                    f"Invalid output.color: '{color}'. Must be one of {sorted(VALID_COLORS)}."
                )

            progress = sec.get("progress", output.progress)
            if not isinstance(progress, bool):
                raise ConfigError("output.progress must be a boolean.")

            default_json = sec.get("default_json", output.default_json)
            if not isinstance(default_json, bool):
                raise ConfigError("output.default_json must be a boolean.")

            output = OutputConfig(color=color, progress=progress, default_json=default_json)
            provenance["output"] = prov

        if "limits" in data:
            sec = data["limits"]
            if not isinstance(sec, dict):
                raise ConfigError("'limits' section must be a table.")
            for k in sec:
                if k not in (
                    "timeout_seconds",
                    "memory_mib",
                    "max_input_bytes",
                    "max_temp_bytes",
                    "max_pixels",
                ):
                    raise ConfigError(f"Unknown key in 'limits': '{k}'.")

            timeout = float(sec.get("timeout_seconds", limits.timeout_seconds))
            if timeout <= 0:
                raise ConfigError("limits.timeout_seconds must be positive.")

            memory = int(sec.get("memory_mib", limits.memory_mib))
            if memory < 64:
                raise ConfigError("limits.memory_mib must be at least 64 MiB.")

            max_input = int(sec.get("max_input_bytes", limits.max_input_bytes))
            if max_input <= 0:
                raise ConfigError("limits.max_input_bytes must be positive.")

            max_temp = int(sec.get("max_temp_bytes", limits.max_temp_bytes))
            if max_temp <= 0:
                raise ConfigError("limits.max_temp_bytes must be positive.")

            max_pixels = int(sec.get("max_pixels", limits.max_pixels))
            if max_pixels <= 0:
                raise ConfigError("limits.max_pixels must be positive.")

            limits = LimitsConfig(
                timeout_seconds=timeout,
                memory_mib=memory,
                max_input_bytes=max_input,
                max_temp_bytes=max_temp,
                max_pixels=max_pixels,
            )
            provenance["limits"] = prov

        if "batch" in data:
            sec = data["batch"]
            if not isinstance(sec, dict):
                raise ConfigError("'batch' section must be a table.")
            for k in sec:
                if k not in ("jobs",):
                    raise ConfigError(f"Unknown key in 'batch': '{k}'.")

            jobs = int(sec.get("jobs", batch.jobs))
            if jobs < 1:
                raise ConfigError("batch.jobs must be at least 1.")
            batch = BatchConfig(jobs=jobs)
            provenance["batch"] = prov

        if "ocr" in data:
            sec = data["ocr"]
            if not isinstance(sec, dict):
                raise ConfigError("'ocr' section must be a table.")
            for k in sec:
                if k not in ("languages",):
                    raise ConfigError(f"Unknown key in 'ocr': '{k}'.")

            langs = sec.get("languages", ocr.languages)
            if not isinstance(langs, (list, tuple)):
                raise ConfigError("ocr.languages must be a list of strings.")
            ocr = OcrConfig(languages=tuple(str(lang) for lang in langs))
            provenance["ocr"] = prov

        if "compress" in data:
            sec = data["compress"]
            if not isinstance(sec, dict):
                raise ConfigError("'compress' section must be a table.")
            for k in sec:
                if k not in ("default_preset",):
                    raise ConfigError(f"Unknown key in 'compress': '{k}'.")

            preset = sec.get("default_preset", compress.default_preset)
            if preset is not None and preset not in VALID_PRESETS:
                raise ConfigError(
                    f"Invalid compress.default_preset: '{preset}'. "
                    f"Must be one of {sorted(VALID_PRESETS)}."
                )
            compress = CompressConfig(default_preset=preset)
            provenance["compress"] = prov

        if "paths" in data:
            sec = data["paths"]
            if not isinstance(sec, dict):
                raise ConfigError("'paths' section must be a table.")
            for k in sec:
                if k not in ("temp_dir",):
                    raise ConfigError(f"Unknown key in 'paths': '{k}'.")

            temp_dir = sec.get("temp_dir")
            if temp_dir:
                p = Path(temp_dir)
                if not p.is_absolute():
                    raise ConfigError(f"paths.temp_dir must be an absolute path: '{temp_dir}'.")
                paths = PathsConfig(temp_dir=p)
                provenance["paths"] = prov

        if "tools" in data:
            sec = data["tools"]
            if not isinstance(sec, dict):
                raise ConfigError("'tools' section must be a table.")
            for k in sec:
                if k not in ("ocrmypdf", "ghostscript", "verapdf", "unpaper"):
                    raise ConfigError(f"Unknown tool key: '{k}'.")

            def resolve_tool_path(tool_key: str) -> Path | None:
                val = sec.get(tool_key)
                if val is None:
                    return None
                p = Path(val)
                if not p.is_absolute():
                    raise ConfigError(f"tools.{tool_key} must be an absolute path: '{val}'.")
                return p

            tools = ToolsConfig(
                ocrmypdf=resolve_tool_path("ocrmypdf") or tools.ocrmypdf,
                ghostscript=resolve_tool_path("ghostscript") or tools.ghostscript,
                verapdf=resolve_tool_path("verapdf") or tools.verapdf,
                unpaper=resolve_tool_path("unpaper") or tools.unpaper,
            )
            provenance["tools"] = prov

    # 2. Load User Config & 3. Explicit Config (if no_config is False)
    if not no_config:
        # Determine explicit config target (either argument or env var)
        explicit_target = explicit_config_path or env.get("PDFTOOLSCLI_CONFIG")
        if explicit_target:
            exp_p = Path(explicit_target)
            exp_data = _parse_toml_file(exp_p)
            apply_toml_data(exp_data, Provenance.EXPLICIT_CONFIG, exp_p)
        else:
            # Check user config
            user_path = get_default_user_config_path()
            if user_path.is_file():
                user_data = _parse_toml_file(user_path)
                apply_toml_data(user_data, Provenance.USER_CONFIG, user_path)

    # 4. Environment Variables
    if "PDFTOOLSCLI_COLOR" in env:
        c = env["PDFTOOLSCLI_COLOR"]
        if c in VALID_COLORS:
            output = OutputConfig(
                color=c,
                progress=output.progress,
                default_json=output.default_json,
            )
            provenance["output.color"] = Provenance.ENV

    # NO_COLOR standard (https://no-color.org)
    if env.get("NO_COLOR"):
        output = OutputConfig(
            color="never",
            progress=output.progress,
            default_json=output.default_json,
        )
        provenance["output.color"] = Provenance.ENV

    # CI standard
    if env.get("CI"):
        output = OutputConfig(
            color=output.color,
            progress=False,
            default_json=output.default_json,
        )
        provenance["output.progress"] = Provenance.ENV

    if "PDFTOOLSCLI_JOBS" in env:
        try:
            j = int(env["PDFTOOLSCLI_JOBS"])
            if j >= 1:
                batch = BatchConfig(jobs=j)
                provenance["batch.jobs"] = Provenance.ENV
        except ValueError:
            pass

    if "PDFTOOLSCLI_TIMEOUT" in env:
        try:
            t = float(env["PDFTOOLSCLI_TIMEOUT"])
            if t > 0:
                limits = LimitsConfig(
                    timeout_seconds=t,
                    memory_mib=limits.memory_mib,
                    max_input_bytes=limits.max_input_bytes,
                    max_temp_bytes=limits.max_temp_bytes,
                    max_pixels=limits.max_pixels,
                )
                provenance["limits.timeout_seconds"] = Provenance.ENV
        except ValueError:
            pass

    if "PDFTOOLSCLI_MEMORY_MIB" in env:
        try:
            m = int(env["PDFTOOLSCLI_MEMORY_MIB"])
            if m >= 64:
                limits = LimitsConfig(
                    timeout_seconds=limits.timeout_seconds,
                    memory_mib=m,
                    max_input_bytes=limits.max_input_bytes,
                    max_temp_bytes=limits.max_temp_bytes,
                    max_pixels=limits.max_pixels,
                )
                provenance["limits.memory_mib"] = Provenance.ENV
        except ValueError:
            pass

    if "PDFTOOLSCLI_TEMP_DIR" in env:
        p = Path(env["PDFTOOLSCLI_TEMP_DIR"])
        if p.is_absolute():
            paths = PathsConfig(temp_dir=p)
            provenance["paths.temp_dir"] = Provenance.ENV

    if "PDFTOOLSCLI_OCR_LANGUAGES" in env:
        langs = [
            lang.strip() for lang in env["PDFTOOLSCLI_OCR_LANGUAGES"].split(",") if lang.strip()
        ]
        if langs:
            ocr = OcrConfig(languages=tuple(langs))
            provenance["ocr.languages"] = Provenance.ENV

    # 5. CLI Overrides
    if cli_overrides:
        if "color" in cli_overrides and cli_overrides["color"] is not None:
            c = cli_overrides["color"]
            if c in VALID_COLORS:
                output = OutputConfig(
                    color=c,
                    progress=output.progress,
                    default_json=output.default_json,
                )
                provenance["output.color"] = Provenance.CLI

        if "quiet" in cli_overrides and cli_overrides["quiet"]:
            output = OutputConfig(
                color=output.color,
                progress=False,
                default_json=output.default_json,
            )
            provenance["output.progress"] = Provenance.CLI

        if "json" in cli_overrides and cli_overrides["json"]:
            output = OutputConfig(
                color=output.color,
                progress=False,
                default_json=True,
            )
            provenance["output.default_json"] = Provenance.CLI

    return Config(
        config_version=config_version,
        output=output,
        limits=limits,
        batch=batch,
        ocr=ocr,
        compress=compress,
        paths=paths,
        tools=tools,
        provenance=provenance,
        loaded_config_path=loaded_path,
    )
