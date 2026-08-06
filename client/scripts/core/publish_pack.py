"""发布适配：抖音预设、封面/话题草稿。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple


def write_topic_draft(
    video_path: str,
    *,
    title: str = "",
    topics: Optional[list] = None,
) -> str:
    """在成片同目录写 .txt 话题/标题草稿。"""
    p = Path(video_path)
    out = p.with_suffix("").as_posix() + "_publish.txt"
    title = (title or p.stem).strip()
    tags = topics or ["#口播", "#干货", "#MusicEditing"]
    tag_line = " ".join(str(t) for t in tags)
    body = (
        f"标题：{title}\n"
        f"话题：{tag_line}\n"
        f"成片：{p.name}\n"
        "备注：请按平台规范自行调整文案后再发布（本工具不接发布 API）。\n"
    )
    Path(out).write_text(body, encoding="utf-8")
    return out


def make_publish_pack(
    bridge,
    video_path: str,
    *,
    title: str = "",
    duration_sec: float = 0.0,
    width: int = 1080,
    height: int = 1920,
) -> Tuple[str, str]:
    """
    生成封面 PNG + 话题草稿 txt。
    返回 (cover_png, draft_txt)。
    """
    from core.cover_factory import make_short_cover

    p = Path(video_path)
    cover = str(p.with_name(f"{p.stem}_cover.png"))
    ttl = (title or p.stem).strip() or "短视频"
    if duration_sec <= 0 and bridge is not None:
        try:
            info = bridge.probe_video(video_path)
            duration_sec = float(getattr(info, "duration_sec", 0) or 0)
        except Exception:
            duration_sec = 0.0
    make_short_cover(
        bridge,
        video_path,
        duration_sec or 30.0,
        cover,
        ttl,
        subtitle="抖音竖屏",
        width=width,
        height=height,
        count=8,
    )
    draft = write_topic_draft(video_path, title=ttl)
    return cover, draft
