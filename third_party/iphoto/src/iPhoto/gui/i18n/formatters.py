"""Locale-aware formatting helpers for GUI text."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QDateTime, QLocale

_DEFAULT_LOCALE = QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
_CURRENT_LOCALE = QLocale(_DEFAULT_LOCALE)


def set_current_locale(locale_name: str | None) -> None:
    """Set the locale used by GUI formatters."""

    global _CURRENT_LOCALE

    if not locale_name:
        _CURRENT_LOCALE = QLocale(_DEFAULT_LOCALE)
        return
    locale = QLocale(locale_name)
    if locale.language() == QLocale.Language.C:
        _CURRENT_LOCALE = QLocale(_DEFAULT_LOCALE)
        return
    _CURRENT_LOCALE = locale


def current_locale() -> QLocale:
    """Return the active GUI locale."""

    return QLocale(_CURRENT_LOCALE)


def format_datetime(value: datetime, *, fallback_format: str = "%Y-%m-%d %H:%M:%S") -> str:
    """Format a :class:`datetime` using the active GUI locale."""

    qt_datetime = QDateTime(value)
    formatted = _CURRENT_LOCALE.toString(qt_datetime, QLocale.FormatType.LongFormat)
    if formatted:
        return formatted
    return value.strftime(fallback_format)


def format_integer(value: int) -> str:
    """Format an integer using the active GUI locale."""

    return _CURRENT_LOCALE.toString(int(value))


def format_decimal(value: float, *, precision: int) -> str:
    """Format a decimal value using the active GUI locale."""

    text = _CURRENT_LOCALE.toString(float(value), "f", precision)
    decimal_point = _CURRENT_LOCALE.decimalPoint()
    if decimal_point:
        text = text.rstrip("0").rstrip(decimal_point)
    return text or "0"


def format_file_size(value: Any) -> str:
    """Return *value* expressed in human readable units."""

    numeric = _coerce_float(value)
    if numeric is None or numeric <= 0:
        return ""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(numeric)
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{format_integer(int(size))} {units[unit_index]}"

    rounded = round(size, 1)
    if float(rounded).is_integer():
        return f"{format_integer(int(rounded))} {units[unit_index]}"
    return f"{format_decimal(rounded, precision=1)} {units[unit_index]}"


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value)
        except ValueError:
            return None
    return None
