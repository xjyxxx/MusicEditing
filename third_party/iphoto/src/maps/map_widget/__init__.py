"""Public package interface for the map widget components.

This module re-exports the high-level classes that external callers relied on
before the refactor, keeping backwards compatibility for imports such as
``from map_widget import LayerPlan``.
"""

from .layer import LayerPlan
from .map_gl_widget import MapGLWidget, MapGLWindowWidget
from .map_widget import MapWidget
from .native_osmand_widget import NativeOsmAndWidget

try:
    from .qt_location_map_widget import QtLocationMapWidget
except Exception:  # pragma: no cover - lean host packs may prune QtPositioning
    QtLocationMapWidget = None  # type: ignore[misc, assignment]

__all__ = [
    "MapWidget",
    "MapGLWidget",
    "MapGLWindowWidget",
    "NativeOsmAndWidget",
    "QtLocationMapWidget",
    "LayerPlan",
]
