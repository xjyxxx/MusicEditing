"""封面/缩略图工厂：在已有 thumbnail 上选最清晰帧，并叠加大字标题导出 PNG。"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

ProgressFn = Callable[[float, str], None]


@dataclass
class FrameCandidate:
    time_sec: float
    path: str
    sharpness: float


@dataclass
class CoverResult:
    frame_path: str
    cover_path: str
    time_sec: float
    sharpness: float
    size: Tuple[int, int]


def _load_bgr(path: str):
    import cv2
    import numpy as np

    # PPM / PNG / JPG：优先 imdecode 兼容中文路径
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
    return img


def score_sharpness(image_path: str) -> float:
    """Laplacian 方差：越大越清晰。"""
    import cv2

    img = _load_bgr(image_path)
    if img is None:
        return -1.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def sample_timestamps(
    duration_sec: float,
    *,
    count: int = 12,
    start_sec: float = 0.0,
    end_sec: float = 0.0,
    skip_edges: float = 0.08,
) -> List[float]:
    """在区间内均匀采样，避开片头片尾黑场。"""
    dur = max(0.1, float(duration_sec or 0.0))
    a = max(0.0, float(start_sec or 0.0))
    b = float(end_sec) if end_sec and end_sec > a else dur
    b = min(dur, max(a + 0.05, b))
    span = b - a
    # 跳过两端各 skip_edges 比例
    pad = span * max(0.0, min(0.4, skip_edges))
    a2, b2 = a + pad, b - pad
    if b2 <= a2 + 0.05:
        a2, b2 = a, b
    n = max(3, min(36, int(count)))
    if n == 1:
        return [(a2 + b2) * 0.5]
    return [a2 + (b2 - a2) * i / (n - 1) for i in range(n)]


def pick_sharpest_frame(
    bridge,
    video_path: str,
    duration_sec: float,
    *,
    count: int = 12,
    start_sec: float = 0.0,
    end_sec: float = 0.0,
    max_width: int = 1280,
    on_progress: Optional[ProgressFn] = None,
) -> FrameCandidate:
    """抽多帧 → 锐度打分 → 返回最清晰帧。"""
    report = on_progress or (lambda _p, _m: None)
    times = sample_timestamps(
        duration_sec, count=count, start_sec=start_sec, end_sec=end_sec
    )
    best: Optional[FrameCandidate] = None
    work = Path(tempfile.mkdtemp(prefix="me_cover_"))
    keep_dir: Optional[Path] = None
    try:
        for i, t in enumerate(times):
            report(5.0 + 70.0 * i / max(1, len(times)), f"抽样 {i + 1}/{len(times)} @ {t:.1f}s")
            out = work / f"f_{i:02d}_{t:.2f}.ppm"
            try:
                path = bridge.extract_thumbnail(
                    video_path,
                    t,
                    output_path=str(out),
                    max_width=max_width,
                    use_cache=False,
                )
                score = score_sharpness(path)
            except Exception:
                continue
            if score < 0:
                continue
            cand = FrameCandidate(time_sec=t, path=path, sharpness=score)
            if best is None or cand.sharpness > best.sharpness:
                best = cand
        if best is None:
            raise RuntimeError("未能抽出可用帧，请确认视频有画面轨")
        # 保留最佳帧到独立临时目录，再删抽样目录
        keep_dir = Path(tempfile.mkdtemp(prefix="me_cover_"))
        keep_path = keep_dir / Path(best.path).name
        try:
            shutil.copy2(best.path, keep_path)
            best = FrameCandidate(
                time_sec=best.time_sec,
                path=str(keep_path),
                sharpness=best.sharpness,
            )
        except OSError:
            keep_dir = None
        report(80.0, f"最清晰帧 @ {best.time_sec:.2f}s（锐度 {best.sharpness:.0f}）")
        return best
    finally:
        # 成功拷出最佳帧后清理抽样目录；失败则整棵 work 留给 orphan 清理
        if best is None or keep_dir is not None:
            shutil.rmtree(work, ignore_errors=True)


def _wrap_title(text: str, max_chars: int = 14) -> List[str]:
    text = (text or "").strip().replace("\r", "")
    if not text:
        return []
    lines: List[str] = []
    for para in text.split("\n"):
        para = para.strip()
        if not para:
            continue
        while len(para) > max_chars:
            lines.append(para[:max_chars])
            para = para[max_chars:]
        if para:
            lines.append(para)
    return lines[:6]


def render_cover_png(
    frame_path: str,
    output_path: str,
    title: str,
    *,
    width: int = 1080,
    height: int = 1920,
    subtitle: str = "",
    dark_bar: bool = True,
) -> str:
    """
    以最清晰帧为底，居中裁切到目标比例，叠加大字标题（Qt 绘制，支持中文）。
    默认 9:16 竖屏短视频封面。
    """
    from PySide6.QtCore import Qt, QRect
    from PySide6.QtGui import (
        QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QLinearGradient,
    )

    if not os.path.isfile(frame_path):
        raise FileNotFoundError(frame_path)

    src = QImage(frame_path)
    if src.isNull():
        # PPM 有时需 OpenCV 转 PNG
        import cv2
        bgr = _load_bgr(frame_path)
        if bgr is None:
            raise RuntimeError(f"无法读取帧: {frame_path}")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        src = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()

    w, h = int(width), int(height)
    canvas = QImage(w, h, QImage.Format_RGB32)
    canvas.fill(QColor(8, 10, 14))

    # 等比裁切 cover
    scaled = src.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    x = (scaled.width() - w) // 2
    y = (scaled.height() - h) // 2
    cropped = scaled.copy(x, y, w, h)

    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    p.drawImage(0, 0, cropped)

    if dark_bar:
        grad = QLinearGradient(0, h * 0.45, 0, h)
        grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        grad.setColorAt(0.45, QColor(0, 0, 0, 140))
        grad.setColorAt(1.0, QColor(0, 0, 0, 210))
        p.fillRect(0, int(h * 0.45), w, int(h * 0.55), grad)

    lines = _wrap_title(title, max_chars=12 if w < 900 else 16)
    sub_lines = _wrap_title(subtitle, max_chars=18) if subtitle else []

    # 大标题：优先雅黑，缺字体时回退无衬线（避免封面标题空白）
    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "sans-serif"])
    font.setBold(True)
    # 按画布高度估字号
    px = max(36, min(96, int(h * 0.055)))
    font.setPixelSize(px)
    p.setFont(font)
    fm = QFontMetrics(font)

    block_h = sum(fm.height() + 8 for _ in lines) + (fm.height() if sub_lines else 0)
    ty = int(h * 0.62)
    if ty + block_h > h - 40:
        ty = max(40, h - 40 - block_h)

    for line in lines:
        tw = fm.horizontalAdvance(line)
        tx = max(24, (w - tw) // 2)
        # 描边
        p.setPen(QPen(QColor(0, 0, 0, 200), 4))
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2)):
            p.drawText(tx + dx, ty + dy, line)
        p.setPen(QColor("#F5F0E8"))
        p.drawText(tx, ty, line)
        ty += fm.height() + 10

    if sub_lines:
        sfont = QFont()
        sfont.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "sans-serif"])
        sfont.setPixelSize(max(22, int(px * 0.45)))
        p.setFont(sfont)
        sfm = QFontMetrics(sfont)
        ty += 8
        for line in sub_lines:
            tw = sfm.horizontalAdvance(line)
            tx = max(24, (w - tw) // 2)
            p.setPen(QColor(0, 0, 0, 160))
            p.drawText(tx + 1, ty + 1, line)
            p.setPen(QColor("#E8A45C"))
            p.drawText(tx, ty, line)
            ty += sfm.height() + 6

    p.end()

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not canvas.save(str(out), "PNG"):
        raise RuntimeError(f"保存封面失败: {out}")
    return str(out.resolve())


def make_short_cover(
    bridge,
    video_path: str,
    duration_sec: float,
    output_png: str,
    title: str,
    *,
    subtitle: str = "",
    count: int = 12,
    start_sec: float = 0.0,
    end_sec: float = 0.0,
    width: int = 1080,
    height: int = 1920,
    on_progress: Optional[ProgressFn] = None,
) -> CoverResult:
    """端到端：最清晰帧 + 标题封面。"""
    report = on_progress or (lambda _p, _m: None)
    best = pick_sharpest_frame(
        bridge,
        video_path,
        duration_sec,
        count=count,
        start_sec=start_sec,
        end_sec=end_sec,
        max_width=max(width, 1280),
        on_progress=report,
    )
    report(88.0, "绘制标题封面…")
    cover = render_cover_png(
        best.path,
        output_png,
        title,
        width=width,
        height=height,
        subtitle=subtitle,
    )
    report(100.0, f"封面已生成: {os.path.basename(cover)}")
    return CoverResult(
        frame_path=best.path,
        cover_path=cover,
        time_sec=best.time_sec,
        sharpness=best.sharpness,
        size=(width, height),
    )


COVER_SIZES = {
    "竖屏 9:16": (1080, 1920),
    "横屏 16:9": (1920, 1080),
    "方图 1:1": (1080, 1080),
}
