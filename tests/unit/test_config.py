"""Unit tests for configuration loading and precedence resolution conforming to PLAN.md §27."""

from __future__ import annotations

from pathlib import Path

import pytest

from pdftoolscli.config.load import load_config
from pdftoolscli.config.model import Provenance
from pdftoolscli.domain.errors import ConfigError


def test_default_config() -> None:
    config = load_config(no_config=True, env={})
    assert config.config_version == 1
    assert config.output.color == "auto"
    assert config.output.progress is True
    assert config.output.default_json is False
    assert config.limits.timeout_seconds == 300.0
    assert config.limits.memory_mib == 1024
    assert config.batch.jobs >= 1
    assert config.ocr.languages == ("eng",)
    assert config.compress.default_preset is None
    assert config.paths.temp_dir is None


def test_load_explicit_config(tmp_path: Path) -> None:
    cfg_file = tmp_path / "custom.toml"
    cfg_file.write_text(
        """
config_version = 1

[output]
color = "never"
progress = false
default_json = true

[limits]
timeout_seconds = 120.0
memory_mib = 512

[batch]
jobs = 8

[ocr]
languages = ["tha", "eng"]

[compress]
default_preset = "ebook"
"""
    )

    config = load_config(explicit_config_path=cfg_file, env={})
    assert config.output.color == "never"
    assert config.output.progress is False
    assert config.output.default_json is True
    assert config.limits.timeout_seconds == 120.0
    assert config.limits.memory_mib == 512
    assert config.batch.jobs == 8
    assert config.ocr.languages == ("tha", "eng")
    assert config.compress.default_preset == "ebook"
    assert config.loaded_config_path == cfg_file
    assert config.get_provenance("output") == Provenance.EXPLICIT_CONFIG


def test_env_var_precedence_over_config(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        """
[output]
color = "always"

[limits]
timeout_seconds = 60.0
memory_mib = 256
"""
    )

    env = {
        "PDFTOOLSCLI_COLOR": "never",
        "PDFTOOLSCLI_TIMEOUT": "99.0",
        "PDFTOOLSCLI_MEMORY_MIB": "1024",
        "PDFTOOLSCLI_JOBS": "16",
        "PDFTOOLSCLI_OCR_LANGUAGES": "jpn, eng",
    }

    config = load_config(explicit_config_path=cfg_file, env=env)
    assert config.output.color == "never"
    assert config.get_provenance("output.color") == Provenance.ENV
    assert config.limits.timeout_seconds == 99.0
    assert config.get_provenance("limits.timeout_seconds") == Provenance.ENV
    assert config.limits.memory_mib == 1024
    assert config.batch.jobs == 16
    assert config.ocr.languages == ("jpn", "eng")


def test_no_color_and_ci_env_vars() -> None:
    # NO_COLOR forces color="never"
    config = load_config(no_config=True, env={"NO_COLOR": "1"})
    assert config.output.color == "never"

    # CI forces progress=False
    config_ci = load_config(no_config=True, env={"CI": "true"})
    assert config_ci.output.progress is False


def test_cli_overrides_precedence(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[output]\ncolor = "never"\n')

    env = {"PDFTOOLSCLI_COLOR": "always"}
    cli_overrides = {"color": "auto", "json": True, "quiet": True}

    config = load_config(explicit_config_path=cfg_file, env=env, cli_overrides=cli_overrides)
    assert config.output.color == "auto"
    assert config.get_provenance("output.color") == Provenance.CLI
    assert config.output.default_json is True
    assert config.output.progress is False


def test_no_config_flag(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[output]\ncolor = "never"\n')

    config = load_config(explicit_config_path=cfg_file, no_config=True, env={})
    assert config.output.color == "auto"  # Default used, config ignored
    assert config.loaded_config_path is None


@pytest.mark.parametrize(
    ("prohibited_content", "expected_err"),
    [
        ('password = "secret"', "Prohibited security-sensitive key 'password'"),
        ('[output]\npassword = "xyz"', "Prohibited security-sensitive key 'output.password'"),
        ("overwrite = true", "Prohibited security-sensitive key 'overwrite'"),
        ("in_place = true", "Prohibited security-sensitive key 'in_place'"),
        ('signature = "allow"', "Prohibited security-sensitive key 'signature'"),
        ('hooks = ["echo"]', "Prohibited security-sensitive key 'hooks'"),
        ('url = "http://evil.com"', "Prohibited security-sensitive key 'url'"),
    ],
)
def test_prohibited_keys_rejected(
    tmp_path: Path, prohibited_content: str, expected_err: str
) -> None:
    cfg_file = tmp_path / "bad.toml"
    cfg_file.write_text(prohibited_content)

    with pytest.raises(ConfigError) as exc_info:
        load_config(explicit_config_path=cfg_file, env={})
    assert expected_err in str(exc_info.value)
    assert exc_info.value.code == "E_CONFIG_INVALID"
    assert exc_info.value.exit_code == 2


def test_unknown_section_rejected(tmp_path: Path) -> None:
    cfg_file = tmp_path / "unknown.toml"
    cfg_file.write_text("[random_plugin]\nfoo = 'bar'")

    with pytest.raises(ConfigError) as exc_info:
        load_config(explicit_config_path=cfg_file, env={})
    assert "Unknown configuration section" in str(exc_info.value)


def test_invalid_types_and_bounds_rejected(tmp_path: Path) -> None:
    # Invalid color
    f1 = tmp_path / "c1.toml"
    f1.write_text('[output]\ncolor = "magenta"')
    with pytest.raises(ConfigError, match="Invalid output.color"):
        load_config(explicit_config_path=f1, env={})

    # Non-boolean progress
    f2 = tmp_path / "c2.toml"
    f2.write_text('[output]\nprogress = "yes"')
    with pytest.raises(ConfigError, match="output.progress must be a boolean"):
        load_config(explicit_config_path=f2, env={})

    # Memory too small (<64)
    f3 = tmp_path / "c3.toml"
    f3.write_text("[limits]\nmemory_mib = 16")
    with pytest.raises(ConfigError, match="must be at least 64 MiB"):
        load_config(explicit_config_path=f3, env={})

    # Non-absolute tool path
    f4 = tmp_path / "c4.toml"
    f4.write_text('[tools]\nocrmypdf = "relative/path/ocrmypdf"')
    with pytest.raises(ConfigError, match="must be an absolute path"):
        load_config(explicit_config_path=f4, env={})


def test_missing_config_file_raises_error(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.toml"
    with pytest.raises(ConfigError, match="not found"):
        load_config(explicit_config_path=missing, env={})


def test_toml_syntax_error(tmp_path: Path) -> None:
    bad_toml = tmp_path / "syntax.toml"
    bad_toml.write_text("output = [this is not valid toml")
    with pytest.raises(ConfigError, match="Syntax error"):
        load_config(explicit_config_path=bad_toml, env={})


def test_more_limits_and_paths_validation(tmp_path: Path) -> None:
    # timeout <= 0
    f1 = tmp_path / "t1.toml"
    f1.write_text("[limits]\ntimeout_seconds = 0")
    with pytest.raises(ConfigError, match="timeout_seconds must be positive"):
        load_config(explicit_config_path=f1, env={})

    # max_input_bytes <= 0
    f2 = tmp_path / "t2.toml"
    f2.write_text("[limits]\nmax_input_bytes = -1")
    with pytest.raises(ConfigError, match="max_input_bytes must be positive"):
        load_config(explicit_config_path=f2, env={})

    # max_temp_bytes <= 0
    f3 = tmp_path / "t3.toml"
    f3.write_text("[limits]\nmax_temp_bytes = 0")
    with pytest.raises(ConfigError, match="max_temp_bytes must be positive"):
        load_config(explicit_config_path=f3, env={})

    # max_pixels <= 0
    f4 = tmp_path / "t4.toml"
    f4.write_text("[limits]\nmax_pixels = 0")
    with pytest.raises(ConfigError, match="max_pixels must be positive"):
        load_config(explicit_config_path=f4, env={})

    # batch.jobs < 1
    f5 = tmp_path / "t5.toml"
    f5.write_text("[batch]\njobs = 0")
    with pytest.raises(ConfigError, match="batch.jobs must be at least 1"):
        load_config(explicit_config_path=f5, env={})

    # paths.temp_dir not absolute
    f6 = tmp_path / "t6.toml"
    f6.write_text('[paths]\ntemp_dir = "relative/temp"')
    with pytest.raises(ConfigError, match="paths.temp_dir must be an absolute path"):
        load_config(explicit_config_path=f6, env={})

    # valid paths.temp_dir and tools
    f7 = tmp_path / "t7.toml"
    f7.write_text(
        f"""
[paths]
temp_dir = "{tmp_path.resolve()}"

[tools]
ghostscript = "{tmp_path.resolve() / "gs"}"
"""
    )
    cfg = load_config(explicit_config_path=f7, env={})
    assert cfg.paths.temp_dir == tmp_path.resolve()
    assert cfg.tools.ghostscript == tmp_path.resolve() / "gs"
    assert cfg.to_dict()["paths"]["temp_dir"] == str(tmp_path.resolve())
