"""外挂字幕：解析 SRT / VTT，按时间轴查询当前行。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class Cue:
    start: float
    end: float
    text: str


_SRT_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)
_VTT_TIME = re.compile(
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\.(\d{1,3})\s*-->\s*"
    r"(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\.(\d{1,3})"
)
_TAG = re.compile(r"<[^>]+>")
_ASS_OVERRIDE = re.compile(r"\{[^}]*\}")


def _pad_ms(ms: str) -> float:
    ms = (ms or "0").ljust(3, "0")[:3]
    return int(ms) / 1000.0


def _hms_to_sec(h: str, m: str, s: str, ms: str) -> float:
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + _pad_ms(ms)


def _clean_text(text: str) -> str:
    text = _ASS_OVERRIDE.sub("", text)
    text = _TAG.sub("", text)
    text = text.replace("\\N", "\n").replace("\\n", "\n")
    text = text.replace("&nbsp;", " ").replace("&lt;", "<").replace("&gt;", ">")
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and not ln.isdigit()]
    return "\n".join(lines).strip()


def parse_srt(content: str) -> List[Cue]:
    cues: List[Cue] = []
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").replace("\r", "\n"))
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        # 跳过序号行
        idx = 0
        if lines[0].strip().isdigit():
            idx = 1
        if idx >= len(lines):
            continue
        m = _SRT_TIME.search(lines[idx])
        if not m:
            continue
        start = _hms_to_sec(m.group(1), m.group(2), m.group(3), m.group(4))
        end = _hms_to_sec(m.group(5), m.group(6), m.group(7), m.group(8))
        body = "\n".join(lines[idx + 1 :])
        text = _clean_text(body)
        if text and end > start:
            cues.append(Cue(start, end, text))
    return cues


def parse_vtt(content: str) -> List[Cue]:
    cues: List[Cue] = []
    text = content.replace("\r\n", "\n").replace("\r", "\n")
    if text.lstrip().startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    # 去掉 NOTE / STYLE 块
    parts = re.split(r"\n\s*\n", text)
    for block in parts:
        lines = [ln for ln in block.split("\n") if ln.strip() != ""]
        if not lines:
            continue
        if lines[0].upper().startswith("WEBVTT") or lines[0].upper().startswith("NOTE"):
            continue
        if lines[0].upper().startswith("STYLE") or lines[0].upper().startswith("REGION"):
            continue
        idx = 0
        if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
            idx = 1
        if idx >= len(lines) or "-->" not in lines[idx]:
            continue
        m = _VTT_TIME.search(lines[idx])
        if not m:
            # 回退 SRT 风格
            m2 = _SRT_TIME.search(lines[idx])
            if not m2:
                continue
            start = _hms_to_sec(m2.group(1), m2.group(2), m2.group(3), m2.group(4))
            end = _hms_to_sec(m2.group(5), m2.group(6), m2.group(7), m2.group(8))
        else:
            start = _hms_to_sec(m.group(1), m.group(2), m.group(3), m.group(4))
            end = _hms_to_sec(m.group(5), m.group(6), m.group(7), m.group(8))
        body = "\n".join(lines[idx + 1 :])
        cleaned = _clean_text(body)
        if cleaned and end > start:
            cues.append(Cue(start, end, cleaned))
    return cues


_ASS_DIALOGUE = re.compile(
    r"^Dialogue:\s*[^,]*,"
    r"(\d+):(\d{2}):(\d{2})\.(\d{1,2}),"
    r"(\d+):(\d{2}):(\d{2})\.(\d{1,2}),"
    r"(?:[^,]*,){6}"
    r"(.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_ass(content: str) -> List[Cue]:
    """仅提取 Dialogue 文本时间轴（忽略样式/特效）。"""
    cues: List[Cue] = []
    for m in _ASS_DIALOGUE.finditer(content.replace("\r\n", "\n").replace("\r", "\n")):
        start = _hms_to_sec(m.group(1), m.group(2), m.group(3), m.group(4).ljust(3, "0"))
        end = _hms_to_sec(m.group(5), m.group(6), m.group(7), m.group(8).ljust(3, "0"))
        text = _clean_text(m.group(9).replace("\\N", "\n").replace("\\n", "\n"))
        if text and end > start:
            cues.append(Cue(start, end, text))
    return cues


def load_subtitle_file(path: str) -> List[Cue]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(path)
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030", "utf-16"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            text = None
    else:
        text = raw.decode("utf-8", errors="replace")

    ext = p.suffix.lower()
    if ext in (".ass", ".ssa"):
        cues = parse_ass(text)
        if not cues:
            cues = parse_srt(text)
    elif ext == ".vtt" or text.lstrip().upper().startswith("WEBVTT"):
        cues = parse_vtt(text)
    else:
        cues = parse_srt(text)
    cues.sort(key=lambda c: c.start)
    return cues


def find_sidecar_subtitles(video_path: str) -> Optional[str]:
    """同目录同名 .srt / .vtt / .ass（ass 当纯文本尽力解析）。"""
    base = Path(video_path)
    stem = base.with_suffix("")
    for ext in (".srt", ".vtt", ".SRT", ".VTT", ".ass", ".ASS"):
        cand = Path(str(stem) + ext)
        if cand.is_file():
            return str(cand)
    # 常见：video.zh.srt / video.chs.srt
    parent = base.parent
    name = base.stem
    for p in parent.glob(name + ".*"):
        if p.suffix.lower() in (".srt", ".vtt", ".ass") and p.is_file():
            return str(p)
    return None


class SubtitleTrack:
    """缓存 cue 列表，按时间二分查找当前字幕。"""

    def __init__(self, cues: Optional[List[Cue]] = None, source: str = ""):
        self.cues: List[Cue] = list(cues or [])
        self.source = source
        self._last_idx = 0

    @classmethod
    def from_file(cls, path: str) -> "SubtitleTrack":
        cues = load_subtitle_file(path)
        return cls(cues, source=path)

    def clear(self) -> None:
        self.cues.clear()
        self.source = ""
        self._last_idx = 0

    @property
    def empty(self) -> bool:
        return not self.cues

    def text_at(self, t: float) -> str:
        if not self.cues:
            return ""
        # 从上次索引附近扫描，播放时更高效
        i = min(self._last_idx, len(self.cues) - 1)
        # 回退
        while i > 0 and self.cues[i].start > t:
            i -= 1
        # 前进
        while i + 1 < len(self.cues) and self.cues[i + 1].start <= t:
            i += 1
        self._last_idx = i
        cue = self.cues[i]
        if cue.start <= t <= cue.end:
            return cue.text
        return ""


def _sec_to_srt_ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    ms = int(round(sec * 1000.0))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: List[Cue], path: str) -> str:
    """写入 UTF-8 SRT（带 BOM 便于部分播放器识别中文）。"""
    lines: List[str] = []
    idx = 1
    for c in cues:
        if c.end <= c.start:
            continue
        text = (c.text or "").strip()
        if not text:
            continue
        lines.append(str(idx))
        lines.append(f"{_sec_to_srt_ts(c.start)} --> {_sec_to_srt_ts(c.end)}")
        lines.append(text)
        lines.append("")
        idx += 1
    Path(path).write_text("\ufeff" + "\n".join(lines), encoding="utf-8")
    return path


def retime_cues_for_segments(
    cues: List[Cue],
    segments: List[Tuple[float, float]],
) -> List[Cue]:
    """
    将原片时间轴字幕，按导出片段拼接后的新时间轴重定时。
    segments: [(start_sec, end_sec), ...] 与成片拼接顺序一致。
    """
    out: List[Cue] = []
    t_cursor = 0.0
    for seg_start, seg_end in segments:
        if seg_end <= seg_start:
            continue
        for cue in cues:
            a = max(float(cue.start), float(seg_start))
            b = min(float(cue.end), float(seg_end))
            if b <= a:
                continue
            out.append(
                Cue(
                    start=t_cursor + (a - seg_start),
                    end=t_cursor + (b - seg_start),
                    text=cue.text,
                )
            )
        t_cursor += seg_end - seg_start
    return out
