"""Internationalisation helpers for the Qt GUI."""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication

from . import formatters
from .language import LanguageInfo
from .translation_manager import TranslationManager


def tr(context: str, source_text: str, disambiguation: str | None = None, n: int = -1) -> str:
    """Translate *source_text* through Qt using a stable context."""

    return QCoreApplication.translate(context, source_text, disambiguation, n)


__all__ = ["LanguageInfo", "TranslationManager", "formatters", "tr"]
