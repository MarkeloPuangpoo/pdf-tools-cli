"""Secret value models and redaction wrappers conforming to PLAN.md §28."""

from __future__ import annotations

from typing import Protocol


class SecretValue:
    """A secret string wrapper that redacts its content from repr and str."""

    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret(self) -> str:
        """Access the underlying raw secret value."""
        return self._value

    def __repr__(self) -> str:
        return "<SecretValue: ***REDACTED***>"

    def __str__(self) -> str:
        return "***REDACTED***"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretValue):
            return self._value == other._value
        if isinstance(other, str):
            return self._value == other
        return False


class SecretProvider(Protocol):
    """Protocol for secret acquisition providers."""

    def get_password(self) -> SecretValue:
        """Acquire the secret password."""
        ...
