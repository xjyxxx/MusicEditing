"""演讲金句 / 日常精彩：文稿规则打分 + 无人声识别时的能量段兜底。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple


@dataclass
class ScoredClip:
    start_sec: float
    end_sec: float
    score: float
    text: str = ""


# 演讲/口播常见「金句」信号词（规则兜底，不依赖 LLM）
_KEYWORDS_SPEECH = (
    "所以", "因此", "总之", "总而言之", "我认为", "我觉得", "其实",
    "重要", "关键", "核心", "本质", "记住", "一定要", "必须",
    "首先", "其次", "最后", "第一", "第二", "第三",
    "总结", "结论", "重点", "换句话说", "也就是说",
    "希望大家", "请大家", "告诉大家", "我想说",
)

_KEYWORDS_DAILY = (
    "哈哈", "太棒", "真的", "绝了", "牛", "厉害", "感动",
    "哭了", "笑死", "惊喜", "终于", "没想到", "太香",
)


def keywords_for_scene(scene: str) -> Tuple[str, ...]:
    if scene == "演讲金句":
        return _KEYWORDS_SPEECH
    if scene == "日常精彩片段":
        return _KEYWORDS_DAILY
    # 自定义：两类词都参考，权重偏低
    return _KEYWORDS_SPEECH + _KEYWORDS_DAILY


def score_text(text: str, scene: str) -> float:
    t = (text or "").strip()
    if not t:
        return 0.0
    keys = keywords_for_scene(scene)
    hits = sum(1 for k in keys if k in t)
    len_score = min(1.0, len(t) / 48.0)
    hit_score = min(1.0, hits * 0.22)
    # 演讲略偏好更长句
    if scene == "演讲金句":
        return min(1.0, len_score * 0.55 + hit_score * 0.45)
    return min(1.0, len_score * 0.45 + hit_score * 0.55)


def score_transcript(
    segments: Sequence,  # objects with start_sec, end_sec, text
    scene: str,
    min_duration: float,
    max_duration: float,
    sensitivity: float,
) -> List[ScoredClip]:
    """对 ASR 句段打分并按敏感度截取 Top-N；过短句会与邻句合并。"""
    sens = max(0.0, min(1.0, float(sensitivity)))
    raw: List[ScoredClip] = []
    for seg in segments:
        start = float(getattr(seg, "start_sec", 0.0))
        end = float(getattr(seg, "end_sec", 0.0))
        text = str(getattr(seg, "text", "") or "")
        if end <= start:
            continue
        base = score_text(text, scene)
        dur = end - start
        if dur < min_duration:
            dur_factor = 0.45
        elif dur > max_duration:
            dur_factor = 0.55
        else:
            dur_factor = 1.0
        score = base * dur_factor * (0.45 + 0.55 * sens)
        # 演讲金句：关键词命中额外加权
        if scene == "演讲金句" and base >= 0.35:
            score = min(1.0, score + 0.08)
        raw.append(ScoredClip(start, end, score, text))

    # 合并过短高分邻句
    raw.sort(key=lambda c: c.start_sec)
    merged: List[ScoredClip] = []
    for c in raw:
        if not merged:
            merged.append(c)
            continue
        prev = merged[-1]
        gap = c.start_sec - prev.end_sec
        if prev.end_sec - prev.start_sec < min_duration and gap <= 0.9:
            merged[-1] = ScoredClip(
                prev.start_sec,
                c.end_sec,
                max(prev.score, c.score),
                (prev.text + c.text).strip(),
            )
        else:
            merged.append(c)

    # 裁切过长段
    clipped: List[ScoredClip] = []
    for c in merged:
        dur = c.end_sec - c.start_sec
        if dur > max_duration:
            clipped.append(ScoredClip(c.start_sec, c.start_sec + max_duration, c.score, c.text))
        elif dur >= min_duration * 0.5:
            clipped.append(c)

    clipped.sort(key=lambda c: c.score, reverse=True)
    max_count = max(2, int(3 + sens * 12))
    out = clipped[:max_count]
    out.sort(key=lambda c: c.start_sec)
    return out


def clips_from_speech_ranges(
    ranges: Iterable[Tuple[float, float]],
    *,
    min_duration: float,
    max_duration: float,
    sensitivity: float,
    scene: str = "演讲金句",
) -> List[ScoredClip]:
    """
    无人声 ASR 时：用 silencedetect 得到的有声区间，切成符合时长的「演讲候选」。
    """
    sens = max(0.0, min(1.0, float(sensitivity)))
    clips: List[ScoredClip] = []
    for start, end in ranges:
        start = float(start)
        end = float(end)
        if end - start < min_duration * 0.6:
            continue
        # 长口播按 max_duration 切开，保留中段（更可能是观点展开）
        t = start
        while t < end - min_duration * 0.5:
            chunk_end = min(t + max_duration, end)
            dur = chunk_end - t
            if dur < min_duration:
                break
            # 演讲：略偏好中等偏长段
            mid = 0.5 * (min_duration + max_duration)
            dur_score = 1.0 - min(1.0, abs(dur - mid) / max(max_duration, 1.0))
            score = (0.35 + 0.5 * dur_score) * (0.5 + 0.5 * sens)
            if scene == "演讲金句":
                score = min(1.0, score + 0.05)
            clips.append(ScoredClip(t, chunk_end, score, ""))
            # 步进：敏感度高则重叠更少、片更多
            step = max(min_duration, max_duration * (0.85 - 0.35 * sens))
            t += step

    clips.sort(key=lambda c: c.score, reverse=True)
    max_count = max(2, int(3 + sens * 10))
    out = clips[:max_count]
    out.sort(key=lambda c: c.start_sec)
    return out
