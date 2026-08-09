"""回归：OpenCV 超分短链路（抽少量帧）。

用法（仓库根）:
  python tests/regression/test_opencv_upscale.py
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
    find_media_cli,
    find_test_video,
    ok,
)

ensure_scripts_path()

from core.media_bridge import MediaBridge  # noqa: E402


def main() -> int:
    if not find_media_cli():
        fail("未找到 media_cli.exe")
        return 2
    video = find_test_video()
    if not video:
        fail("tests/ 下无测试视频")
        return 2

    print(f"video={video}")
    bridge = MediaBridge()
    info = bridge.probe_video(str(video))
    fps = float(info.fps or 25.0)
    ok(f"probe {info.width}x{info.height} fps={fps:.2f}")

    out_dir = Path(tempfile.mkdtemp(prefix="me_reg_sr_"))
    out = str(out_dir / "opencv_2x.mp4")
    try:
        result = bridge.upscale_video(
            model_path="-",
            input_path=str(video),
            output_path=out,
            fps=fps,
            scale=2,
            strength=50,
            start_sec=0.0,
            end_sec=0.6,
            max_frames=12,
            backend="opencv",
        )
        if not os.path.isfile(result) or os.path.getsize(result) < 1000:
            fail(f"输出无效: {result}")
            return 3
        out_info = bridge.probe_video(result)
        if out_info.width < info.width or out_info.height < info.height:
            fail(
                f"分辨率未升高 in={info.width}x{info.height} "
                f"out={out_info.width}x{out_info.height}"
            )
            return 4
        ok(f"upscale out={out_info.width}x{out_info.height} size={os.path.getsize(result)}")
        print("PASS  OpenCV upscale")
        return 0
    except Exception as e:
        fail(str(e))
        return 1
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
