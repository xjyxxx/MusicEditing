"""热评导出与短视频效果接口。

已实现：
  - export_comments_json / export_comments_ass
  - render_comment_short_video：ASS 字幕 + 竖屏烧录（最小可用管线）
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from core.netease_comments import HotComment


@dataclass
class CommentExportPackage:
    """可序列化的评论导出包（短视频管线输入契约）。"""

    comments: List[HotComment] = field(default_factory=list)
    song_id: str = ""
    song_name: str = ""
    media_path: str = ""
    media_kind: str = ""  # audio | video | ""
    source: str = ""
    exported_at: str = ""
    schema: str = "music_editing.comment_export.v1"

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "exported_at": self.exported_at,
            "song_id": self.song_id,
            "song_name": self.song_name,
            "media_path": self.media_path,
            "media_kind": self.media_kind,
            "source": self.source,
            "count": len(self.comments),
            "comments": [
                {
                    "content": c.content,
                    "liked_count": int(c.liked_count or 0),
                    "nickname": c.nickname or "",
                    "display": c.display_text(),
                }
                for c in self.comments
            ],
        }


def build_export_package(
    comments: Sequence[HotComment],
    *,
    song_id: str = "",
    song_name: str = "",
    media_path: str = "",
    media_kind: str = "",
    source: str = "",
) -> CommentExportPackage:
    return CommentExportPackage(
        comments=list(comments or []),
        song_id=song_id or "",
        song_name=song_name or "",
        media_path=media_path or "",
        media_kind=media_kind or "",
        source=source or "",
        exported_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def export_comments_json(package: CommentExportPackage, output_path: str) -> str:
    """写出 JSON 评论包，返回绝对路径。"""
    if not package.comments:
        raise ValueError("没有可导出的评论")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(package.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(path.resolve())


def _ass_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def export_comments_ass(
    package: CommentExportPackage,
    output_path: str,
    *,
    seconds_per_comment: float = 3.0,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
) -> str:
    """按顺序排出 ASS 字幕（底部居中），可供竖屏短视频烧录。"""
    if not package.comments:
        raise ValueError("没有可导出的评论")
    dur = max(0.8, float(seconds_per_comment))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(play_res_x)}",
        f"PlayResY: {int(play_res_y)}",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Microsoft YaHei,56,&H00FFFFFF,&H000000FF,"
        "&H00101010,&H80000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,72,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    t = 0.0
    for c in package.comments:
        text = (c.display_text() or "").replace("\n", " ").replace("{", "(").replace("}", ")")
        if not text.strip():
            continue
        start = _ass_timestamp(t)
        end = _ass_timestamp(t + dur)
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")
        t += dur

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return str(path.resolve())


@dataclass
class CommentShortVideoRequest:
    """热评短视频成片请求。

    style:
      - ass_caption / danmaku / cards：当前均走 ASS + 竖屏烧录最小管线
    """

    media_path: str
    comments: List[HotComment] = field(default_factory=list)
    output_path: str = ""
    style: str = "ass_caption"  # danmaku | cards | ass_caption
    song_name: str = ""
    song_id: str = ""
    width: int = 1080
    height: int = 1920
    seconds_per_comment: float = 3.0


class CommentShortVideoNotImplemented(NotImplementedError):
    """短视频效果管线尚未接入。"""


def _is_audio_media(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg", ".opus"}


def _make_canvas_from_audio(
    audio_path: str,
    out_mp4: str,
    *,
    width: int,
    height: int,
    duration_sec: float,
) -> str:
    """纯音频：生成黑底竖屏画布 + 音轨，供后续烧字幕。"""
    from core.media_bridge import _find_ffmpeg, _video_encoder_args

    ffmpeg = _find_ffmpeg()
    w = width - (width % 2)
    h = height - (height % 2)
    dur = max(1.0, float(duration_sec))
    cmd = [
        str(ffmpeg), "-y", "-hide_banner",
        "-f", "lavfi", "-i", f"color=c=0x101418:s={w}x{h}:d={dur}",
        "-i", audio_path,
        "-shortest",
        *_video_encoder_args(high_quality=False),
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        out_mp4,
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=600,
    )
    if proc.returncode != 0 or not os.path.isfile(out_mp4):
        raise RuntimeError(
            f"音频画布生成失败：{(proc.stderr or proc.stdout or '')[-400:]}"
        )
    return out_mp4


def render_comment_short_video(
    req: CommentShortVideoRequest,
    *,
    bridge=None,
    on_progress=None,
) -> str:
    """将媒体 + 热评渲染为竖屏短视频（ASS 字幕烧录）。

    danmaku / cards 暂与 ass_caption 共用最小管线，保证可导出可播。
    """
    if not req.media_path or not os.path.isfile(req.media_path):
        raise FileNotFoundError(f"媒体不存在: {req.media_path}")
    if not req.comments:
        raise ValueError("没有评论，无法生成热评短视频")

    from core.media_bridge import MediaBridge

    b = bridge or MediaBridge()
    out = (req.output_path or "").strip()
    if not out:
        stem = Path(req.media_path).stem
        out = str(Path(req.media_path).with_name(f"{stem}_hot_comments.mp4"))
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    n = len(req.comments)
    spc = max(0.8, float(req.seconds_per_comment or 3.0))
    total_dur = max(spc * n, 3.0)

    fd, ass_path = tempfile.mkstemp(prefix="me_hc_", suffix=".ass")
    os.close(fd)
    canvas_tmp = ""
    try:
        if on_progress:
            on_progress(5.0, "生成热评字幕…")
        pkg = build_export_package(
            req.comments,
            song_id=req.song_id,
            song_name=req.song_name,
            media_path=req.media_path,
        )
        export_comments_ass(
            pkg,
            ass_path,
            seconds_per_comment=spc,
            play_res_x=int(req.width) or 1080,
            play_res_y=int(req.height) or 1920,
        )

        media_in = req.media_path
        if _is_audio_media(req.media_path):
            if on_progress:
                on_progress(20.0, "纯音频：生成竖屏画布…")
            fd2, canvas_tmp = tempfile.mkstemp(prefix="me_hc_canvas_", suffix=".mp4")
            os.close(fd2)
            # 尽量用真实音频时长
            try:
                dur = float(b.probe_duration(req.media_path) or 0.0)
            except Exception:
                dur = 0.0
            if dur <= 0:
                dur = total_dur
            else:
                dur = max(dur, total_dur)
            media_in = _make_canvas_from_audio(
                req.media_path,
                canvas_tmp,
                width=int(req.width) or 1080,
                height=int(req.height) or 1920,
                duration_sec=dur,
            )

        if on_progress:
            on_progress(35.0, "竖屏烧录热评字幕…")
        return b.export_vertical_short(
            media_in,
            out,
            width=int(req.width) or 1080,
            height=int(req.height) or 1920,
            crop_bias="center",
            subtitle_path=ass_path,
            on_progress=on_progress,
        )
    finally:
        for p in (ass_path, canvas_tmp):
            if p and os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass


def load_export_package(json_path: str) -> CommentExportPackage:
    """从 JSON 读回评论包（短视频管线入口）。"""
    raw = json.loads(Path(json_path).read_text(encoding="utf-8"))
    comments = [
        HotComment(
            content=str(item.get("content") or ""),
            liked_count=int(item.get("liked_count") or 0),
            nickname=str(item.get("nickname") or ""),
        )
        for item in (raw.get("comments") or [])
        if str(item.get("content") or "").strip()
    ]
    return CommentExportPackage(
        comments=comments,
        song_id=str(raw.get("song_id") or ""),
        song_name=str(raw.get("song_name") or ""),
        media_path=str(raw.get("media_path") or ""),
        media_kind=str(raw.get("media_kind") or ""),
        source=str(raw.get("source") or ""),
        exported_at=str(raw.get("exported_at") or ""),
        schema=str(raw.get("schema") or "music_editing.comment_export.v1"),
    )
