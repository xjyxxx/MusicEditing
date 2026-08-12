"""Smoke: MUSIC_IPHOTO_HOSTED 下地点地图能否叠上照片缩略图。"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ["MUSIC_IPHOTO_HOSTED"] = "1"
os.environ.setdefault("MUSIC_IPHOTO_SOFT_VIEWER", "1")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "client" / "scripts"))
sys.path.insert(0, str(ROOT / "third_party" / "iphoto" / "src"))

from core.iphoto_bootstrap import ensure_iphoto_on_path  # noqa: E402

ensure_iphoto_on_path()

from PySide6.QtCore import QPointF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from iPhoto.application.dtos import GeotaggedAsset  # noqa: E402
from iPhoto.gui.ui.widgets.map_widget_factory import MapWidget  # noqa: E402
from iPhoto.gui.ui.widgets.marker_controller import _MarkerCluster  # noqa: E402
from iPhoto.gui.ui.widgets.photo_map_view import (  # noqa: E402
    PhotoMapView,
    _GLMarkerLayer,
    _MarkerLayer,
)
from maps.map_widget.map_gl_widget import MapGLWidget  # noqa: E402


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    img_path = ROOT / ".cache" / "smoke_place.jpg"
    if not img_path.is_file():
        img = QImage(64, 64, QImage.Format.Format_RGB32)
        img.fill(QColor(30, 144, 255))
        img_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(img_path), "JPG")

    lib_root = img_path.parent
    rel = img_path.name

    view = PhotoMapView()
    view.resize(900, 600)
    view.show()
    app.processEvents()

    print("map_widget=", type(view.map_widget()).__name__)
    print("overlay=", type(view._overlay).__name__)
    print(
        "is_MarkerLayer=",
        isinstance(view._overlay, _MarkerLayer)
        and not isinstance(view._overlay, _GLMarkerLayer),
    )
    print("is_MapWidget_CPU=", isinstance(view.map_widget(), MapWidget))
    print("is_MapGL=", isinstance(view.map_widget(), MapGLWidget))

    asset = GeotaggedAsset(
        library_relative=rel,
        album_relative=rel,
        absolute_path=img_path,
        album_path=lib_root,
        asset_id="smoke1",
        latitude=22.55,
        longitude=114.07,
        is_image=True,
        is_video=False,
        still_image_time=None,
        duration=None,
        location_name="Shenzhen",
        live_photo_group_id=None,
        live_partner_rel=None,
    )
    view.set_assets([asset], lib_root)

    pix = QPixmap(str(img_path))
    assert not pix.isNull(), "failed to load smoke pixmap"
    view._overlay.set_thumbnail(rel, pix)
    cluster = _MarkerCluster(
        representative=asset, assets=[asset], screen_pos=QPointF(450, 300)
    )
    view._overlay.set_clusters([cluster])
    app.processEvents()

    print("overlay_pixmaps=", list(view._overlay._pixmaps.keys()))
    print("overlay_pixmap_null=", view._overlay._pixmaps[rel].isNull())
    print("clusters=", len(view._overlay._clusters))

    w, h = view.width(), view.height()
    canvas = QImage(w, h, QImage.Format.Format_ARGB32)
    canvas.fill(QColor(136, 168, 194))
    painter = QPainter(canvas)
    painter_ok = painter.isActive()
    view._overlay.paint_markers(painter)
    painter.end()
    print("painter_ok=", painter_ok)

    c = canvas.pixelColor(450, 260)
    print(f"sample_rgb=({c.red()},{c.green()},{c.blue()}) alpha={c.alpha()}")
    bg = (136, 168, 194)
    diff = abs(c.red() - bg[0]) + abs(c.green() - bg[1]) + abs(c.blue() - bg[2])
    print("diff_from_bg=", diff)
    out = ROOT / ".cache" / "smoke_place_map.png"
    canvas.save(str(out))
    print("saved", out)

    deadline = time.time() + 1.5
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)

    ok = (
        isinstance(view.map_widget(), MapWidget)
        and isinstance(view._overlay, _MarkerLayer)
        and not isinstance(view._overlay, _GLMarkerLayer)
        and (not view._overlay._pixmaps[rel].isNull())
        and diff > 10
    )
    print("RESULT=", "PASS" if ok else "FAIL")
    view.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
