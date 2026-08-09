"""回归：竖屏短视频导出（固定裁切，短片）。

用法（仓库根）:
  python tests/regression/test_vertical_export.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    ensure_scripts_path,
    fail,
    find_ffmpeg,
    find_media_cli,
    find_test_video,
    ok,
)

ensure_scripts_path()

from core.media_bridge import MediaBridge  # noqa: E402


def main() -> int:
    if not find_ffmpeg() and not find_media_cli():
        fail("未找到 ffmpeg / media_cli")
        return 2
    video = find_test_video()
    if not video:
        fail("tests/ 下无测试视频")
        return 2

    print(f"video={video}")
    bridge = MediaBridge()
    info = bridge.probe_video(str(video))
    ok(f"probe {info.width}x{info.height} dur={info.duration_sec:.2f}s")

    out_dir = Path(tempfile.mkdtemp(prefix="me_reg_vert_"))
    # 先裁一小段，再竖屏，缩短耗时
    clip = str(out_dir / "clip.mp4")
    out = str(out_dir / "vertical_9x16.mp4")
    try:
        bridge.export_clip(
            str(video),
            0.0,
            min(1.2, max(0.5, float(info.duration_sec or 1.0) * 0.2)),
            clip,
            reencode=True,
            quality="fast",
        )
        if not os.path.isfile(clip):
            fail("裁切失败")
            return 3

        bridge.export_vertical_short(
            clip,
            out,
            width=720,
            height=1280,
            crop_bias="center",
            track_mode="fixed",
            quality="fast",
        )
        if not os.path.isfile(out) or os.path.getsize(out) < 800:
            fail(f"竖屏输出无效: {out}")
            return 4

        vinfo = bridge.probe_video(out)
        # 允许偶数对齐偏差；要求接近 9:16
        ratio = float(vinfo.width) / max(1, float(vinfo.height))
        target = 9.0 / 16.0
        if abs(ratio - target) > 0.08:
            fail(
                f"画幅不像竖屏 9:16: {vinfo.width}x{vinfo.height} "
                f"ratio={ratio:.3f}"
            )
            return 5
        if vinfo.height < vinfo.width:
            fail(f"高度应大于宽度: {vinfo.width}x{vinfo.height}")
            return 5

        ok(f"vertical {vinfo.width}x{vinfo.height} size={os.path.getsize(out)}")
        print("PASS  vertical export")
        return 0
    except Exception as e:
        fail(str(e))
        return 1
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
