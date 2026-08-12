"""照片编辑数学核心：Gaussian 主滑块、投影坐标和无黑边安全裁剪。无 Qt 依赖。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class ToneAdjustments:
    exposure: float = 0.0
    contrast: float = 0.0
    saturation: float = 0.0
    temperature: float = 0.0


def gaussian_weights(centers: Iterable[float], focus: float = 0.0, sigma: float = 0.62) -> list[float]:
    """返回归一化高斯权重；用于把一个大师滑块平滑分配到多个细分参数。"""
    values = [math.exp(-0.5 * ((float(center) - focus) / max(0.05, sigma)) ** 2) for center in centers]
    total = sum(values) or 1.0
    return [value / total for value in values]


def resolve_master_adjustments(
    *, light: float = 0.0, color: float = 0.0, exposure: float = 0.0,
    contrast: float = 0.0, saturation: float = 0.0, temperature: float = 0.0,
) -> ToneAdjustments:
    light = max(-1.0, min(1.0, float(light)))
    color = max(-1.0, min(1.0, float(color)))
    lw = gaussian_weights((-1.0, -0.15, 0.75), focus=-0.05)
    cw = gaussian_weights((-0.8, 0.1, 0.85), focus=0.15)
    return ToneAdjustments(
        exposure=max(-3.0, min(3.0, exposure + light * (0.55 + lw[1]))),
        contrast=max(-1.0, min(1.0, contrast + light * (lw[2] - lw[0]) * 0.55)),
        saturation=max(-1.0, min(1.0, saturation + color * (0.35 + cw[1]))),
        temperature=max(-1.0, min(1.0, temperature + color * (cw[2] - cw[0]) * 0.35)),
    )


def point_in_convex_polygon(point: tuple[float, float], polygon: np.ndarray, eps: float = 1e-6) -> bool:
    """凸多边形包含测试；顺/逆时针顶点均支持，边界视为有效。"""
    p = np.asarray(point, dtype=np.float64)
    poly = np.asarray(polygon, dtype=np.float64)
    signs: list[float] = []
    for index in range(len(poly)):
        edge = poly[(index + 1) % len(poly)] - poly[index]
        rel = p - poly[index]
        cross = float(edge[0] * rel[1] - edge[1] * rel[0])
        if abs(cross) > eps:
            signs.append(cross)
    return not signs or all(value >= -eps for value in signs) or all(value <= eps for value in signs)


def safe_aabb_in_quad(
    quad: np.ndarray, *, aspect: float, center: tuple[float, float] | None = None,
) -> tuple[float, float, float, float]:
    """二分求位于投影凸四边形内的最大中心 AABB，返回 x,y,w,h。"""
    poly = np.asarray(quad, dtype=np.float64)
    if poly.shape != (4, 2):
        raise ValueError("quad 必须是 4×2 坐标")
    cx = float(np.mean(poly[:, 0])) if center is None else float(center[0])
    cy = float(np.mean(poly[:, 1])) if center is None else float(center[1])
    aspect = max(1e-6, float(aspect))
    max_half_w = max(float(np.ptp(poly[:, 0])), 1.0)
    low, high = 0.0, max_half_w
    for _ in range(48):
        half_w = (low + high) * 0.5
        half_h = half_w / aspect
        corners = ((cx-half_w, cy-half_h), (cx+half_w, cy-half_h),
                   (cx+half_w, cy+half_h), (cx-half_w, cy+half_h))
        if all(point_in_convex_polygon(point, poly) for point in corners):
            low = half_w
        else:
            high = half_w
    half_w = max(0.5, low)
    half_h = max(0.5, half_w / aspect)
    return cx-half_w, cy-half_h, half_w*2.0, half_h*2.0


def projected_quad(width: int, height: int, horizontal: float = 0.0, vertical: float = 0.0) -> np.ndarray:
    """构造透视后的有效凸四边形；参数范围 -1..1。"""
    w, h = float(max(1, width)), float(max(1, height))
    hx = max(-1.0, min(1.0, float(horizontal))) * w * 0.22
    vy = max(-1.0, min(1.0, float(vertical))) * h * 0.22
    return np.array([[max(0.0, hx), max(0.0, vy)],
                     [w + min(0.0, hx), max(0.0, -vy)],
                     [w + min(0.0, -hx), h + min(0.0, -vy)],
                     [max(0.0, -hx), h + min(0.0, vy)]], dtype=np.float32)
