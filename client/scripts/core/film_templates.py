"""一键竖屏成片模板：封面文案位、时长上限、话题草稿。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class FilmTemplate:
    """成片闭环模板（队列 / 导出对话框共用）。"""

    key: str
    label: str
    # 对应 export_naming / publish_pack 的平台键
    platform: str  # douyin_vertical | bilibili_vertical | kuaishou_vertical
    # 高光合并总时长上限（秒）；0=不限制
    max_total_sec: float = 45.0
    cover_title: str = "高光速看"
    cover_subtitle: str = "竖屏成片"
    topics: Tuple[str, ...] = ("#高光", "#竖屏")
    make_cover: bool = True
    make_topic_draft: bool = True
    do_vertical: bool = True
    vertical_w: int = 1080
    vertical_h: int = 1920
    quality: str = "high"
    hint: str = ""


_TEMPLATES: Dict[str, FilmTemplate] = {
    "douyin_hook": FilmTemplate(
        key="douyin_hook",
        label="抖音爆款竖屏（≤45s）",
        platform="douyin_vertical",
        max_total_sec=45.0,
        cover_title="高光速看",
        cover_subtitle="抖音竖屏",
        topics=("#抖音", "#竖屏", "#高光", "#必看"),
        hint="跟脸竖屏 + 封面/话题；适合短冲击切片",
    ),
    "bili_highlight": FilmTemplate(
        key="bili_highlight",
        label="B站竖屏高光（≤60s）",
        platform="bilibili_vertical",
        max_total_sec=60.0,
        cover_title="本场高光",
        cover_subtitle="B站竖屏",
        topics=("#必剪", "#竖屏", "#高光成片", "#精彩集锦"),
        hint="稍长成片，封面强调「本场」",
    ),
    "kuaishou_fast": FilmTemplate(
        key="kuaishou_fast",
        label="快手快剪竖屏（≤30s）",
        platform="kuaishou_vertical",
        max_total_sec=30.0,
        cover_title="精彩一秒",
        cover_subtitle="快手竖屏",
        topics=("#快手", "#竖屏", "#高光", "#快剪"),
        hint="更短更密，适合快节奏剪辑",
    ),
}


def list_film_templates() -> List[FilmTemplate]:
    return list(_TEMPLATES.values())


def get_film_template(key: str) -> Optional[FilmTemplate]:
    k = (key or "").strip()
    if not k or k in ("none", "off", "custom", ""):
        return None
    return _TEMPLATES.get(k)


def clamp_ranges_to_budget(
    ranges: List[Tuple[float, float]],
    max_total_sec: float,
) -> List[Tuple[float, float]]:
    """按时间顺序裁剪片段，使总时长不超过上限。"""
    if max_total_sec <= 0 or not ranges:
        return list(ranges)
    out: List[Tuple[float, float]] = []
    budget = float(max_total_sec)
    for a, b in ranges:
        if budget <= 0.05:
            break
        a = float(a)
        b = float(b)
        if b <= a:
            continue
        dur = b - a
        if dur <= budget:
            out.append((a, b))
            budget -= dur
        else:
            out.append((a, a + budget))
            budget = 0.0
            break
    return out or list(ranges[:1])


def apply_publish_pack_for_template(
    bridge,
    video_path: str,
    tpl: FilmTemplate,
    *,
    duration_sec: float = 0.0,
) -> Tuple[str, str]:
    """按模板写封面 + 话题草稿。"""
    from core.publish_pack import make_publish_pack, write_topic_draft

    if tpl.make_cover:
        return make_publish_pack(
            bridge,
            video_path,
            title=tpl.cover_title,
            duration_sec=duration_sec,
            width=tpl.vertical_w,
            height=tpl.vertical_h,
            preset=tpl.platform,
        )
    draft = ""
    if tpl.make_topic_draft:
        draft = write_topic_draft(
            video_path,
            title=tpl.cover_title,
            topics=list(tpl.topics),
            preset=tpl.platform,
        )
    return "", draft
