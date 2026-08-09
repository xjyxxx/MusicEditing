"""开箱试跑：本地样例 → 裁 15 秒 → 竖屏导出（验证引擎真能出片）。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable, Optional, Tuple


ProgressCb = Callable[[float, str], None]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def find_trial_sample() -> Optional[str]:
    tests = _project_root() / "tests"
    for name in ("test_video.mp4", "222222.mp4"):
        p = tests / name
        if p.is_file():
            return str(p)
    if tests.is_dir():
        for p in sorted(tests.iterdir()):
            if p.suffix.lower() in {".mp4", ".mov", ".mkv"} and p.is_file():
                return str(p)
    return None


def run_trial_15s(
    bridge,
    *,
    sample_path: str = "",
    output_dir: str = "",
    on_progress: Optional[ProgressCb] = None,
) -> Tuple[str, str]:
    """
    试跑 15 秒竖屏成片。
    返回 (vertical_mp4, message)。
    """
    def report(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    src = sample_path or find_trial_sample()
    if not src or not os.path.isfile(src):
        raise FileNotFoundError(
            "未找到试跑样例。请把任意短视频放到 tests/test_video.mp4"
        )

    out_root = output_dir.strip() if output_dir else ""
    if not out_root:
        out_root = str(_project_root() / "output" / "trial")
    os.makedirs(out_root, exist_ok=True)

    report(5.0, "探测样例…")
    info = bridge.probe_video(src)
    fps = float(getattr(info, "fps", 0) or 25.0)
    dur = float(getattr(info, "duration_sec", 0) or 15.0)
    end = min(15.0, max(3.0, dur))

    report(15.0, f"裁切前 {end:.0f} 秒…")
    clip = os.path.join(out_root, "trial_15s_clip.mp4")
    # 用高光导出单段
    _clips, merged = bridge.export_highlights(
        src, [(0.0, end)], out_root, concat=True,
        naming_preset="douyin_vertical",
        use_naming_scheme=True,
        on_progress=lambda p, m: report(15.0 + p * 0.35, m),
    )
    work = merged if merged and os.path.isfile(merged) else (clip if os.path.isfile(clip) else "")
    if not work and _clips:
        work = _clips[0]
    if not work or not os.path.isfile(work):
        raise RuntimeError("试跑裁切失败：未生成片段（请确认 media_cli / ffmpeg 可用）")

    report(55.0, "竖屏导出…")
    from core.export_naming import default_vertical_name

    vert = os.path.join(
        out_root,
        default_vertical_name(src, preset="douyin_vertical", ext="mp4"),
    )
    bridge.export_vertical_short(
        work,
        vert,
        width=1080,
        height=1920,
        track_mode="fixed",
        quality="standard",
        on_progress=lambda p, m: report(55.0 + p * 0.35, m),
    )
    if not os.path.isfile(vert):
        raise RuntimeError("竖屏导出失败")

    try:
        from core.film_templates import get_film_template, apply_publish_pack_for_template

        tpl = get_film_template("douyin_hook")
        if tpl:
            apply_publish_pack_for_template(bridge, vert, tpl, duration_sec=end)
    except Exception:
        pass

    report(100.0, "试跑完成")
    msg = (
        f"已生成试跑成片：\n{vert}\n\n"
        f"样例：{os.path.basename(src)} · 时长约 {end:.0f}s\n"
        "说明：引擎链路正常，可以开始用正式素材。"
    )
    return vert, msg
