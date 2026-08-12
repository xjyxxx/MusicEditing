"""Language metadata used by the GUI translation service."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LanguageInfo:
    """Description of a supported UI language."""

    code: str
    native_name: str
    english_name: str
    qt_locale: str | None = None
    qm: str | None = None


__all__ = ["LanguageInfo"]
