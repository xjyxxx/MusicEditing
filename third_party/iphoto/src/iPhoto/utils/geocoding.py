"""Helpers for reverse geocoding GPS coordinates."""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Dict, Optional

from .logging import get_logger

try:
    import reverse_geocoder  # type: ignore[import]
except ImportError:  # pragma: no cover - optional in lean host packs
    reverse_geocoder = None  # type: ignore[assignment]


@lru_cache(maxsize=1)
def _geocoder():
    """Return a cached reverse geocoder instance, or None if dependency missing."""

    if reverse_geocoder is None:
        return None
    return reverse_geocoder.RGeocoder(mode=1, verbose=False)


@lru_cache(maxsize=32768)
def _lookup_location_name(latitude_key: float, longitude_key: float) -> Optional[str]:
    """Resolve a stable location label for the rounded GPS coordinate."""

    geocoder = _geocoder()
    if geocoder is None:
        return None

    try:
        result = geocoder.query([(latitude_key, longitude_key)])
    except Exception:
        return None

    record: Optional[Dict[str, str]] = None

    def _to_text(value: object) -> str:
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="ignore")
        return str(value)

    if isinstance(result, dict):
        record = {key: _to_text(value) for key, value in result.items() if isinstance(key, str)}
    elif isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            record = {
                key: _to_text(value)
                for key, value in first.items()
                if isinstance(key, str)
            }

    if not record:
        return None

    city = str(record.get("name", "")).strip()
    admin = str(record.get("admin2") or record.get("admin1") or "").strip()
    components = [component for component in (city, admin) if component]
    if not components:
        return None
    return " — ".join(components)


def _coerce_coordinate(value: object) -> Optional[float]:
    """Return *value* as decimal coordinates when possible."""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return float(candidate)
        except ValueError:
            return None
    return None


def resolve_location_name(gps: Optional[Dict[str, float]]) -> Optional[str]:
    """Return a human readable place name for *gps* coordinates.

    Parameters
    ----------
    gps:
        Mapping that may contain ``latitude`` / ``longitude`` keys.
    """

    if not gps:
        return None

    latitude = _coerce_coordinate(gps.get("latitude"))
    longitude = _coerce_coordinate(gps.get("longitude"))
    if latitude is None or longitude is None:
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None

    # Quantize to reduce cache churn while keeping city-level precision.
    latitude_key = round(latitude, 3)
    longitude_key = round(longitude, 3)
    try:
        return _lookup_location_name(latitude_key, longitude_key)
    except Exception as exc:  # pragma: no cover
        get_logger(__name__).debug("reverse geocode failed: %s", exc)
        return None
