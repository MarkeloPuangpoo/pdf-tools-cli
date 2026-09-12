"""Domain error hierarchy and standard exit codes conforming to PLAN.md §17."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class ExitCode(IntEnum):
    """Standard CLI exit codes defined in PLAN.md §17."""

    SUCCESS = 0
    QUERY_EMPTY = 1
    USAGE_OR_SELECTION = 2
    IO_ERROR = 3
    AUTHENTICATION_REQUIRED = 4
    INVALID_DOCUMENT = 5
    DEPENDENCY_MISSING = 6
    RESOURCE_LIMIT = 7
    SAFETY_CONFLICT = 8
    BATCH_FAILURE = 9
    INTERNAL_ERROR = 10
    CANCELLED = 130
    BROKEN_PIPE = 141


@dataclass(frozen=True)
class ErrorDetail:
    """Structured error record matching PLAN.md §17 schema."""

    code: str
    category: str
    message: str
    input_id: str | None = None
    page: int | None = None
    details: dict[str, Any] | str | None = None
    hint: str | None = None
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize error detail to dictionary."""
        return {
            "code": self.code,
            "category": self.category,
            "message": self.message,
            "input_id": self.input_id,
            "page": self.page,
            "details": self.details,
            "hint": self.hint,
            "retryable": self.retryable,
        }


class PDFToolsError(Exception):
    """Base exception for all domain and CLI errors in PDF Tools CLI."""

    def __init__(
        self,
        message: str,
        code: str = "E_INTERNAL",
        category: str = "internal",
        exit_code: ExitCode = ExitCode.INTERNAL_ERROR,
        input_id: str | None = None,
        page: int | None = None,
        details: dict[str, Any] | str | None = None,
        hint: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.category = category
        self.exit_code = exit_code
        self.input_id = input_id
        self.page = page
        self.details = details
        self.hint = hint
        self.retryable = retryable

    def as_detail(self) -> ErrorDetail:
        """Convert exception to structured ErrorDetail."""
        return ErrorDetail(
            code=self.code,
            category=self.category,
            message=self.message,
            input_id=self.input_id,
            page=self.page,
            details=self.details,
            hint=self.hint,
            retryable=self.retryable,
        )


class RangeSyntaxError(PDFToolsError):
    """Raised when a page range string has invalid syntax."""

    def __init__(
        self,
        message: str,
        offset: int = 0,
        line: int = 1,
        column: int = 1,
        hint: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="E_PAGE_BOUNDS",
            category="selection",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            details={"offset": offset, "line": line, "column": column},
            hint=hint or "Check page range syntax (e.g. 1-5, odd, even, last).",
        )
        self.offset = offset
        self.line = line
        self.column = column


class PageBoundsError(PDFToolsError):
    """Raised when a requested page is out of document bounds or violates context."""

    def __init__(
        self,
        message: str,
        page: int | None = None,
        page_count: int | None = None,
        input_id: str | None = None,
        hint: str | None = None,
    ) -> None:
        details: dict[str, Any] = {}
        if page is not None:
            details["requested_page"] = page
        if page_count is not None:
            details["actual_page_count"] = page_count
        super().__init__(
            message=message,
            code="E_PAGE_BOUNDS",
            category="selection",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            input_id=input_id,
            page=page,
            details=details,
            hint=hint or "Verify total pages with `ptc inspect <file>`.",
        )


class ConfigError(PDFToolsError):
    """Raised when configuration parsing or validation fails."""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(
            message=message,
            code="E_CONFIG_INVALID",
            category="configuration",
            exit_code=ExitCode.USAGE_OR_SELECTION,
            hint=hint or "Check configuration file syntax and allowed keys.",
        )


class FileSafetyError(PDFToolsError):
    """Raised when a file safety check fails (e.g. input == output, existing file)."""

    def __init__(
        self,
        message: str,
        code: str = "E_SAME_FILE",
        hint: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            category="safety",
            exit_code=ExitCode.SAFETY_CONFLICT,
            hint=hint,
        )


class SecretError(PDFToolsError):
    """Raised when authentication credentials are missing or invalid."""

    def __init__(
        self,
        message: str,
        code: str = "E_PASSWORD_REQUIRED",
        hint: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code,
            category="authentication",
            exit_code=ExitCode.AUTHENTICATION_REQUIRED,
            hint=(
                hint
                or "Provide a password using --password-file, --password-env, or --password-stdin."
            ),
        )


class ResourceLimitError(PDFToolsError):
    """Raised when memory, timeout, or dimension limits are exceeded."""

    def __init__(
        self,
        message: str,
        hint: str | None = None,
    ) -> None:
        super().__init__(
            message=message,
            code="E_RESOURCE_LIMIT",
            category="resource",
            exit_code=ExitCode.RESOURCE_LIMIT,
            hint=hint or "Increase resource limits via CLI flags or configuration.",
        )
