"""非破坏编辑的 NumPy/OpenCV 参考渲染器；也是 OpenGL 不可用时的软件回退。"""

from __future__ import annotations

import numpy as np

from core.photo_edit_math import projected_quad, resolve_master_adjustments, safe_aabb_in_quad


def render_rgba(rgba: np.ndarray, recipe) -> np.ndarray:
    """渲染 RGBA uint8，保持输入不变；recipe 使用鸭子类型避免 UI 依赖。"""
    source = np.asarray(rgba, dtype=np.uint8)
    if source.ndim != 3 or source.shape[2] != 4:
        raise ValueError("输入必须是 H×W×4 RGBA")
    out = source.copy()
    rgb = out[:, :, :3].astype(np.float32) / 255.0
    tone = resolve_master_adjustments(
        light=getattr(recipe, "master_light", 0.0),
        color=getattr(recipe, "master_color", 0.0),
        exposure=getattr(recipe, "exposure", 0.0),
        contrast=getattr(recipe, "contrast", 0.0),
        saturation=getattr(recipe, "saturation", 0.0),
        temperature=getattr(recipe, "temperature", 0.0),
    )
    rgb *= 2.0 ** tone.exposure
    rgb = (rgb - 0.5) * (1.0 + tone.contrast) + 0.5
    luminance = np.sum(rgb * np.array([0.2126, 0.7152, 0.0722], dtype=np.float32), axis=2, keepdims=True)
    rgb = luminance + (rgb - luminance) * (1.0 + tone.saturation)
    rgb[:, :, 0] += tone.temperature * 0.08
    rgb[:, :, 2] -= tone.temperature * 0.08
    out[:, :, :3] = np.clip(rgb * 255.0, 0.0, 255.0).astype(np.uint8)
    return _apply_geometry(out, recipe)


def _apply_geometry(rgba: np.ndarray, recipe) -> np.ndarray:
    horizontal = float(getattr(recipe, "perspective_horizontal", 0.0))
    vertical = float(getattr(recipe, "perspective_vertical", 0.0))
    rotation = float(getattr(recipe, "rotation", 0.0))
    if abs(horizontal) < 1e-6 and abs(vertical) < 1e-6 and abs(rotation) < 1e-6:
        return rgba
    try:
        import cv2  # type: ignore
    except Exception:
        return rgba
    h, w = rgba.shape[:2]
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    dst = projected_quad(w, h, horizontal, vertical)
    matrix = cv2.getPerspectiveTransform(src, dst)
    if abs(rotation) > 1e-6:
        rotate = cv2.getRotationMatrix2D((w * 0.5, h * 0.5), rotation, 1.0)
        rotate3 = np.vstack([rotate, [0.0, 0.0, 1.0]])
        matrix = rotate3 @ matrix
        dst_h = np.hstack([dst, np.ones((4, 1), dtype=np.float32)])
        transformed = (rotate3 @ dst_h.T).T
        dst = (transformed[:, :2] / transformed[:, 2:3]).astype(np.float32)
    warped = cv2.warpPerspective(rgba, matrix, (w, h), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    x, y, cw, ch = safe_aabb_in_quad(dst, aspect=w / float(max(1, h)))
    x0, y0 = max(0, int(np.ceil(x))), max(0, int(np.ceil(y)))
    x1, y1 = min(w, int(np.floor(x + cw))), min(h, int(np.floor(y + ch)))
    if x1 <= x0 or y1 <= y0:
        return rgba
    cropped = warped[y0:y1, x0:x1]
    return cv2.resize(cropped, (w, h), interpolation=cv2.INTER_LINEAR)
