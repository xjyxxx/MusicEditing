"""游戏高光视觉侧：PySceneDetect 场景切点。

依赖仓库内第三方源码 `third_party/PySceneDetect`（随代码分发），
也可经 `pip install -r client/scripts/requirements.txt` / `scripts/install_scenedetect.bat` 安装。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from core.app_logger import setup_logging

log = setup_logging("SceneDetect")

ProgressCb = Callable[[float, str], None]


def _vendor_root() -> Path:
    # client/scripts/core → MusicEditing
    return Path(__file__).resolve().parents[3] / "third_party" / "PySceneDetect"


def _ensure_local_vendor_on_path() -> None:
    """保证能 import scenedetect：优先仓库 third_party，再退回已 pip 安装的包。"""
    vendor = _vendor_root()
    if (vendor / "scenedetect").is_dir():
        p = str(vendor.resolve())
        if p not in sys.path:
            sys.path.insert(0, p)

    env = os.environ.get("MUSIC_SCENEDETECT_PATH", "").strip()
    if env:
        ep = Path(env)
        if (ep / "scenedetect").is_dir():
            s = str(ep.resolve())
            if s not in sys.path:
                sys.path.insert(0, s)

    try:
        import scenedetect  # noqa: F401
        return
    except ImportError:
        pass


def scenedetect_available() -> bool:
    _ensure_local_vendor_on_path()
    try:
        import scenedetect  # noqa: F401
        return True
    except ImportError:
        return False


def sensitivity_to_adaptive_threshold(sensitivity: float) -> float:
    """切片敏感度 0..1 → AdaptiveDetector.adaptive_threshold（越小越灵敏）。"""
    s = max(0.0, min(1.0, float(sensitivity)))
    # 默认敏感度 0.5 → 约 3.0（库默认）；高敏感 → 更低阈值
    return max(1.5, min(6.0, 4.5 - s * 3.0))


def sensitivity_to_content_threshold(sensitivity: float) -> float:
    """切片敏感度 0..1 → ContentDetector.threshold。"""
    s = max(0.0, min(1.0, float(sensitivity)))
    # 0.5 → 27；越高敏感阈值越低
    return max(15.0, min(45.0, 38.0 - s * 22.0))


def detect_scene_ranges(
    video_path: str,
    *,
    sensitivity: float = 0.5,
    min_scene_sec: float = 1.0,
    method: str = "adaptive",
    frame_skip: int = 0,
    on_progress: Optional[ProgressCb] = None,
) -> List[Tuple[float, float]]:
    """
    返回场景区间列表 [(start_sec, end_sec), ...]。
    method: adaptive（游戏推荐，抗快速运镜）| content（硬切）
    """
    _ensure_local_vendor_on_path()
    from scenedetect import (
        AdaptiveDetector,
        ContentDetector,
        SceneManager,
        open_video,
    )

    path = os.path.abspath(video_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    def report(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    report(5.0, "打开视频（PySceneDetect）…")
    video = open_video(path, backend="opencv")
    manager = SceneManager()
    min_len = max(0.2, float(min_scene_sec))

    method_l = (method or "adaptive").strip().lower()
    if method_l in ("content", "detect-content", "cut"):
        thr = sensitivity_to_content_threshold(sensitivity)
        manager.add_detector(ContentDetector(threshold=thr, min_scene_len=min_len))
        report(10.0, f"ContentDetector threshold={thr:.1f}")
    else:
        thr = sensitivity_to_adaptive_threshold(sensitivity)
        manager.add_detector(
            AdaptiveDetector(adaptive_threshold=thr, min_scene_len=min_len)
        )
        report(10.0, f"AdaptiveDetector threshold={thr:.1f}")

    skip = max(0, int(frame_skip))
    report(15.0, "正在检测场景切点…" + (f"（跳帧 {skip}）" if skip else ""))

    # 无逐帧 UI 回调时用起止进度近似；检测本身在本线程
    frames = manager.detect_scenes(
        video=video,
        frame_skip=skip,
        show_progress=False,
    )
    scenes = manager.get_scene_list(start_in_scene=True)
    report(85.0, f"检测到 {len(scenes)} 个场景（处理 {frames} 帧）")
    log.info(
        "检测完成 path=%s method=%s scenes=%d frames=%d sensitivity=%.2f",
        path, method_l, len(scenes), frames, sensitivity,
    )

    ranges: List[Tuple[float, float]] = []
    for start_tc, end_tc in scenes:
        start = float(start_tc.get_seconds())
        end = float(end_tc.get_seconds())
        if end > start + 0.05:
            ranges.append((start, end))
    if ranges:
        log.info(
            "场景区间样例: %s%s",
            ranges[:3],
            " …" if len(ranges) > 3 else "",
        )
    return ranges


def ranges_to_clipped_segments(
    ranges: List[Tuple[float, float]],
    *,
    min_duration: float,
    max_duration: float,
    sensitivity: float = 0.5,
    max_segments: int = 24,
) -> List[Tuple[float, float, float]]:
    """
    按最短/最长约束整形场景，返回 (start, end, score)。
    过短丢弃；过长按 max_duration 切开。
    """
    min_d = max(0.5, float(min_duration))
    max_d = max(min_d, float(max_duration))
    out: List[Tuple[float, float, float]] = []

    for start, end in ranges:
        dur = end - start
        if dur < min_d:
            continue
        t = start
        while t < end - 1e-3:
            e = min(t + max_d, end)
            if e - t >= min_d:
                # 略偏长的片段分数稍高；敏感度抬高基准分
                score = 0.45 + 0.35 * min(1.0, (e - t) / max_d) + 0.2 * float(sensitivity)
                out.append((t, e, min(0.99, score)))
            t = e

    if len(out) > max_segments:
        # 均匀抽样，保留时间分布
        step = len(out) / float(max_segments)
        picked = [out[int(i * step)] for i in range(max_segments)]
        out = picked
    return out
