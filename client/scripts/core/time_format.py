"""时间轴显示用秒 → 可读字符串。"""

from __future__ import annotations


def format_timestamp(sec: float) -> str:
    """将秒格式化为 m:ss 或 h:mm:ss（向下取整到秒）。"""
    if sec < 0 or sec != sec:  # NaN
        sec = 0.0
    s = int(sec)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def format_range(start_sec: float, end_sec: float) -> str:
    """起止区间，如 1:23 – 1:45。"""
    return f"{format_timestamp(start_sec)} – {format_timestamp(end_sec)}"
