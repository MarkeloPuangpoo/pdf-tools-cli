"""Domain models, grammar parsers, and errors."""

from pdftoolscli.domain.errors import (
    ConfigError,
    ErrorDetail,
    ExitCode,
    FileSafetyError,
    PageBoundsError,
    PDFToolsError,
    RangeSyntaxError,
    ResourceLimitError,
    SecretError,
)

__all__ = [
    "ConfigError",
    "ErrorDetail",
    "ExitCode",
    "FileSafetyError",
    "PDFToolsError",
    "PageBoundsError",
    "RangeSyntaxError",
    "ResourceLimitError",
    "SecretError",
]
