"""Configuration models and provenance tracking conforming to PLAN.md §27."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Provenance(Enum):
    """Origin of a configuration value."""

    DEFAULT = "default"
    USER_CONFIG = "user_config"
    EXPLICIT_CONFIG = "explicit_config"
    ENV = "env"
    CLI = "cli"


@dataclass(frozen=True)
class ValueWithProvenance[T]:
    """Wraps a configuration value with its source provenance."""

    value: T
    provenance: Provenance = Provenance.DEFAULT


@dataclass(frozen=True)
class OutputConfig:
    color: str = "auto"  # "auto", "always", "never"
    progress: bool = True
    default_json: bool = False


@dataclass(frozen=True)
class LimitsConfig:
    timeout_seconds: float = 300.0
    memory_mib: int = 1024
    max_input_bytes: int = 20 * 1024 * 1024 * 1024  # 20 GiB
    max_temp_bytes: int = 40 * 1024 * 1024 * 1024  # 40 GiB
    max_pixels: int = 100_000_000  # 100 megapixels


@dataclass(frozen=True)
class BatchConfig:
    jobs: int = field(default_factory=lambda: max(1, min(4, os.cpu_count() or 1)))


@dataclass(frozen=True)
class OcrConfig:
    languages: tuple[str, ...] = ("eng",)


@dataclass(frozen=True)
class CompressConfig:
    default_preset: str | None = None


@dataclass(frozen=True)
class PathsConfig:
    temp_dir: Path | None = None


@dataclass(frozen=True)
class ToolsConfig:
    ocrmypdf: Path | None = None
    ghostscript: Path | None = None
    verapdf: Path | None = None
    unpaper: Path | None = None


@dataclass(frozen=True)
class Config:
    """Master configuration container for pdftoolscli."""

    config_version: int = 1
    output: OutputConfig = field(default_factory=OutputConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    compress: CompressConfig = field(default_factory=CompressConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    provenance: dict[str, Provenance] = field(default_factory=dict)
    loaded_config_path: Path | None = None

    def get_provenance(self, key: str) -> Provenance:
        """Return the provenance for a given key, defaulting to DEFAULT."""
        return self.provenance.get(key, Provenance.DEFAULT)

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary representation."""
        return {
            "config_version": self.config_version,
            "output": {
                "color": self.output.color,
                "progress": self.output.progress,
                "default_json": self.output.default_json,
            },
            "limits": {
                "timeout_seconds": self.limits.timeout_seconds,
                "memory_mib": self.limits.memory_mib,
                "max_input_bytes": self.limits.max_input_bytes,
                "max_temp_bytes": self.limits.max_temp_bytes,
                "max_pixels": self.limits.max_pixels,
            },
            "batch": {
                "jobs": self.batch.jobs,
            },
            "ocr": {
                "languages": list(self.ocr.languages),
            },
            "compress": {
                "default_preset": self.compress.default_preset,
            },
            "paths": {
                "temp_dir": str(self.paths.temp_dir) if self.paths.temp_dir else None,
            },
            "tools": {
                "ocrmypdf": str(self.tools.ocrmypdf) if self.tools.ocrmypdf else None,
                "ghostscript": str(self.tools.ghostscript) if self.tools.ghostscript else None,
                "verapdf": str(self.tools.verapdf) if self.tools.verapdf else None,
                "unpaper": str(self.tools.unpaper) if self.tools.unpaper else None,
            },
        }
