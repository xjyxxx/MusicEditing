"""批量全流程队列：任务项与共享参数。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple


class PipelineJobState(str, Enum):
    WAITING = "等待"
    RUNNING = "进行中"
    DONE = "完成"
    FAILED = "失败"
    SKIPPED = "已跳过"
    CANCELLED = "已取消"


class PipelinePhase(str, Enum):
    IDLE = ""
    PROBE = "探测"
    SLICE = "切片分析"
    EXPORT = "导出成片"
    ENHANCE = "超分"
    WATERMARK = "去水印"
    DONE = "完成"


@dataclass
class PipelineSettings:
    """队列共享参数（启动时快照，避免跑着改）。"""

    do_slice: bool = True
    do_enhance: bool = True
    do_watermark: bool = False
    scene: str = "游戏高光"
    min_duration: float = 3.0
    max_duration: float = 60.0
    sensitivity: float = 0.5
    enhance_backend: str = "opencv"  # opencv | realesrgan
    enhance_scale: int = 2
    enhance_strength: int = 65
    # 0 = 对成片/原片全程超分；>0 仅处理前 N 秒（试跑）
    enhance_max_sec: float = 0.0
    watermark_backend: str = "opencv"
    # none | top_left | top_right | bottom_left | bottom_right
    watermark_corner: str = "top_right"
    output_root: str = ""


@dataclass
class PipelineJob:
    path: str
    state: PipelineJobState = PipelineJobState.WAITING
    phase: PipelinePhase = PipelinePhase.IDLE
    progress: float = 0.0
    message: str = ""
    result_path: str = ""
    error: str = ""


def corner_watermark_regions(
    width: int,
    height: int,
    corner: str,
) -> List[Tuple[int, int, int, int]]:
    """按分辨率生成常见角标水印框（无人值守默认）。"""
    c = (corner or "none").strip().lower()
    if c in ("", "none", "off", "跳过"):
        return []
    if width <= 0 or height <= 0:
        return []
    rw = max(48, int(width * 0.18))
    rh = max(32, int(height * 0.10))
    margin = max(8, int(min(width, height) * 0.02))
    if c in ("top_right", "右上", "tr"):
        return [(max(0, width - rw - margin), margin, rw, rh)]
    if c in ("top_left", "左上", "tl"):
        return [(margin, margin, rw, rh)]
    if c in ("bottom_right", "右下", "br"):
        return [(max(0, width - rw - margin), max(0, height - rh - margin), rw, rh)]
    if c in ("bottom_left", "左下", "bl"):
        return [(margin, max(0, height - rh - margin), rw, rh)]
    return []
