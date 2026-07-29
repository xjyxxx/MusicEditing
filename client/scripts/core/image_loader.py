"""统一图片预览加载。

解码优先级：
  1) OpenCV imdecode（支持超大 PNG / Windows 中文路径）
  2) 可选 OpenCV CUDA 缩放（本机 opencv 带 CUDA 且有设备时）
  3) Qt QImageReader 回退（带 EXIF 自动旋转）

说明：静图没有「OpenGL 解码」——OpenGL 只负责把已解码的 RGB 上传为纹理显示；
对比视图通过 QOpenGLWidget 视口做 GPU 合成，见 EnhancePage ZoomImageView。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap


@dataclass(frozen=True)
class PreviewImage:
    pixmap: QPixmap
    native_width: int
    native_height: int
    backend: str  # opencv | opencv+cuda | qt | none

    @property
    def native_size(self) -> tuple[int, int]:
        return (self.native_width, self.native_height)

    @property
    def ok(self) -> bool:
        return not self.pixmap.isNull() and self.native_width > 0


def _cuda_device_count() -> int:
    try:
        import cv2  # type: ignore

        if not hasattr(cv2, "cuda"):
            return 0
        return int(cv2.cuda.getCudaEnabledDeviceCount())
    except Exception:
        return 0


def _resize_bgr(bgr, max_side: int):
    """返回 (resized_bgr, used_cuda: bool)。"""
    import cv2  # type: ignore

    h, w = bgr.shape[:2]
    m = max(w, h)
    if max_side <= 0 or m <= max_side:
        return bgr, False
    scale = max_side / float(m)
    nw, nh = max(1, int(w * scale)), max(1, int(h * scale))

    if _cuda_device_count() > 0:
        try:
            gpu = cv2.cuda_GpuMat()
            gpu.upload(bgr)
            gpu = cv2.cuda.resize(gpu, (nw, nh), interpolation=cv2.INTER_AREA)
            return gpu.download(), True
        except Exception:
            pass

    return cv2.resize(bgr, (nw, nh), interpolation=cv2.INTER_AREA), False


def _bgr_to_pixmap(bgr) -> QPixmap:
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, int(rgb.strides[0]), QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


def _load_opencv(path: str, max_side: int) -> PreviewImage | None:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        data = np.fromfile(path, dtype=np.uint8)
        if data.size == 0:
            return None
        bgr = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if bgr is None or bgr.size == 0:
            return None
        h, w = bgr.shape[:2]
        bgr, used_cuda = _resize_bgr(bgr, max_side)
        backend = "opencv+cuda" if used_cuda else "opencv"
        return PreviewImage(_bgr_to_pixmap(bgr), w, h, backend)
    except Exception:
        return None


def _load_qt(path: str, max_side: int) -> PreviewImage | None:
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    size = reader.size()
    nw = size.width() if size.isValid() else 0
    nh = size.height() if size.isValid() else 0
    if size.isValid() and max_side > 0:
        w, h = size.width(), size.height()
        m = max(w, h)
        if m > max_side:
            s = max_side / float(m)
            reader.setScaledSize(
                size.scaled(max(1, int(w * s)), max(1, int(h * s)), Qt.KeepAspectRatio)
            )
    img = reader.read()
    if img.isNull():
        return None
    if nw <= 0 or nh <= 0:
        nw, nh = img.width(), img.height()
    return PreviewImage(QPixmap.fromImage(img), nw, nh, "qt")


def load_preview(path: str, max_side: int = 2560) -> PreviewImage:
    """加载用于 UI 预览的 pixmap（可降采样）。"""
    if not path or not os.path.isfile(path):
        return PreviewImage(QPixmap(), 0, 0, "none")
    path = os.path.normpath(path)

    loaded = _load_opencv(path, max_side)
    if loaded is not None and loaded.ok:
        return loaded

    loaded = _load_qt(path, max_side)
    if loaded is not None and loaded.ok:
        return loaded

    return PreviewImage(QPixmap(), 0, 0, "none")


def probe_size(path: str) -> tuple[int, int]:
    """只读原始宽高，不加载全像素到 QPixmap。"""
    if not path or not os.path.isfile(path):
        return (0, 0)
    path = os.path.normpath(path)

    # Qt 对多数格式可只读头；超大 PNG 也通常能拿到 size
    reader = QImageReader(path)
    size = reader.size()
    if size.isValid() and size.width() > 0:
        return (size.width(), size.height())

    loaded = load_preview(path, max_side=64)
    return loaded.native_size
