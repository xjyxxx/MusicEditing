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
    preset: str = "custom",
) -> str:
    """在成片同目录写 .txt 话题/标题草稿。"""
    from core.export_naming import build_export_name, sanitize_stem

    p = Path(video_path)
    # 规范名话题文件，避免覆盖
    out_name = build_export_name(
        video_path, kind="topic", preset=preset, ext="txt",
    )
    out = str(p.with_name(out_name))
    title = (title or sanitize_stem(p.stem)).strip()
    if topics is None:
        topics = {
            "douyin_vertical": ["#抖音", "#竖屏", "#高光"],
            "bilibili_vertical": ["#必剪", "#竖屏", "#高光成片"],
            "kuaishou_vertical": ["#快手", "#竖屏", "#高光"],
        }.get(preset, ["#口播", "#干货", "#MusicEditing"])
    tag_line = " ".join(str(t) for t in topics)
    platform = {
        "douyin_vertical": "抖音",
        "bilibili_vertical": "B站",
        "kuaishou_vertical": "快手",
    }.get(preset, "通用")
    body = (
        f"平台：{platform}\n"
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
    preset: str = "douyin_vertical",
) -> Tuple[str, str]:
    """
    生成封面 PNG + 话题草稿 txt。
    返回 (cover_png, draft_txt)。
    """
    from core.cover_factory import make_short_cover
    from core.export_naming import build_export_name, sanitize_stem

    p = Path(video_path)
    cover = str(p.with_name(build_export_name(
        video_path, kind="cover", preset=preset, ext="png",
    )))
    ttl = (title or sanitize_stem(p.stem)).strip() or "短视频"
    subtitle = {
        "douyin_vertical": "抖音竖屏",
        "bilibili_vertical": "B站竖屏",
        "kuaishou_vertical": "快手竖屏",
    }.get(preset, "竖屏短视频")
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
        subtitle=subtitle,
        width=width,
        height=height,
        count=8,
    )
    draft = write_topic_draft(video_path, title=ttl, preset=preset)
    return cover, draft
