"""OpenCV 人脸采样 → 平滑轨迹（竖屏跟脸裁切）。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class FaceSample:
    t: float
    nx: float  # 0~1 画面归一化中心
    ny: float


def _cascade():
    try:
        import cv2
    except ImportError:
        return None
    path = getattr(cv2.data, "haarcascades", "") + "haarcascade_frontalface_default.xml"
    if not path or not os.path.isfile(path):
        return None
    clf = cv2.CascadeClassifier(path)
    if clf.empty():
        return None
    return clf


def sample_face_track(
    video_path: str,
    *,
    duration_sec: float = 0.0,
    interval_sec: float = 0.5,
    max_samples: int = 240,
) -> List[FaceSample]:
    """逐段采样人脸中心；无人脸则返回空列表。"""
    try:
        import cv2
    except ImportError:
        return []
    clf = _cascade()
    if clf is None:
        return []
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        if fps <= 1e-3:
            fps = 25.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        dur = duration_sec
        if dur <= 0 and frame_count > 0:
            dur = frame_count / fps
        if dur <= 0:
            dur = 30.0
        interval = max(0.2, float(interval_sec))
        samples: List[FaceSample] = []
        t = 0.0
        while t <= dur + 1e-6 and len(samples) < max_samples:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                t += interval
                continue
            h, w = frame.shape[:2]
            if h < 8 or w < 8:
                t += interval
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = clf.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(48, 48))
            if len(faces) > 0:
                # 取最大脸
                x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
                cx = (x + fw * 0.5) / float(w)
                cy = (y + fh * 0.5) / float(h)
                samples.append(FaceSample(t=t, nx=max(0.0, min(1.0, cx)), ny=max(0.0, min(1.0, cy))))
            t += interval
        return samples
    finally:
        cap.release()


def smooth_track(
    samples: List[FaceSample],
    *,
    alpha: float = 0.35,
) -> List[FaceSample]:
    if not samples:
        return []
    out: List[FaceSample] = []
    sx, sy = samples[0].nx, samples[0].ny
    for s in samples:
        sx = alpha * s.nx + (1.0 - alpha) * sx
        sy = alpha * s.ny + (1.0 - alpha) * sy
        out.append(FaceSample(t=s.t, nx=sx, ny=sy))
    return out


def face_at_time(track: List[FaceSample], t: float) -> Tuple[float, float]:
    """线性插值；无轨迹返回 (0.5, 0.5)。"""
    if not track:
        return 0.5, 0.5
    if t <= track[0].t:
        return track[0].nx, track[0].ny
    if t >= track[-1].t:
        return track[-1].nx, track[-1].ny
    for i in range(1, len(track)):
        a, b = track[i - 1], track[i]
        if a.t <= t <= b.t:
            if b.t <= a.t:
                return b.nx, b.ny
            u = (t - a.t) / (b.t - a.t)
            return a.nx + (b.nx - a.nx) * u, a.ny + (b.ny - a.ny) * u
    return track[-1].nx, track[-1].ny


def build_face_segments(
    track: List[FaceSample],
    duration_sec: float,
    *,
    seg_sec: float = 1.0,
) -> List[Tuple[float, float, float, float]]:
    """
    返回 [(t0, t1, nx, ny), ...] 供分段 crop。
    nx/ny 为裁切窗中心（归一化）。
    """
    if duration_sec <= 0:
        duration_sec = track[-1].t if track else 1.0
    seg = max(0.4, float(seg_sec))
    out: List[Tuple[float, float, float, float]] = []
    t = 0.0
    while t < duration_sec - 1e-3:
        t1 = min(duration_sec, t + seg)
        mid = (t + t1) * 0.5
        nx, ny = face_at_time(track, mid)
        out.append((t, t1, nx, ny))
        t = t1
    return out
