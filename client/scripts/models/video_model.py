"""视频数据模型"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional


class TaskState(IntEnum):
    WAITING = 0
    PROCESSING = 1
    RENDERING = 2
    COMPLETED = 3
    FAILED = 4
    CANCELLED = 5


class TaskType(IntEnum):
    SLICE = 0
    ENHANCE = 1
    WATERMARK = 2


@dataclass
class VideoModel:
    file_path: str = ""
    width: int = 0
    height: int = 0
    duration_sec: float = 0.0
    fps: float = 0.0
    total_frames: int = 0
    codec_name: str = ""
    format_name: str = ""
    thumbnail_path: str = ""


@dataclass
class HighlightSegment:
    start_sec: float
    end_sec: float
    score: float = 0.0
    selected: bool = True


@dataclass
class TaskModel:
    task_id: int
    task_type: TaskType
    file_path: str
    state: TaskState = TaskState.WAITING
    progress: float = 0.0
    current_frame: int = 0
    total_frames: int = 0
    message: str = ""


@dataclass
class SliceParams:
    scene: str = "游戏高光"
    min_duration: float = 3.0
    max_duration: float = 60.0
    sensitivity: float = 0.5


@dataclass
class AppState:
    current_video: Optional[VideoModel] = None
    tasks: List[TaskModel] = field(default_factory=list)
    slice_params: SliceParams = field(default_factory=SliceParams)
    highlight_segments: List[HighlightSegment] = field(default_factory=list)
    output_dir: str = ""
