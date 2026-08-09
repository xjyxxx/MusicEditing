"""回归：播放器 SHM + 预取 + Seek。

用法（仓库根）:
  python tests/regression/test_player_shm_seek.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (
    ensure_scripts_path,
    fail,
    find_media_player,
    find_test_video,
    ok,
)

ensure_scripts_path()

from core.player_backend import PlayerBackend  # noqa: E402


def main() -> int:
    if not find_media_player():
        fail("未找到 media_player.exe，请先 build_x64.bat")
        return 2
    video = find_test_video()
    if not video:
        fail("tests/ 下无测试视频")
        return 2

    print(f"video={video}")
    backend = PlayerBackend()
    try:
        info = backend.open(str(video))
        ok(f"open {info.width}x{info.height} {info.duration_sec:.1f}s fps={info.fps:.2f}")

        if not getattr(backend, "use_shm", False):
            fail("未启用 SHM（回退写盘）——帧传通道异常")
            return 3
        dual = getattr(backend, "shm_dual", False)
        ok(f"SHM 已启用 dual={dual}")

        target = min(1.0, max(0.1, info.duration_sec * 0.1))
        frame = backend.seek_and_frame(target)
        if frame is None:
            fail("seek_and_frame 无帧")
            return 4
        ts, data, w, h = frame
        if w <= 0 or h <= 0 or len(data) < w * h * 3:
            fail(f"帧数据异常 w={w} h={h} len={len(data)}")
            return 4
        ok(f"seek_and_frame ts={ts:.3f} {w}x{h}")

        hit = 0
        for _ in range(8):
            f = backend.next_frame()
            if f is None:
                break
            stats = backend.last_frame_stats
            if getattr(stats, "from_prefetch", False):
                hit += 1
            time.sleep(0.01)
        if hit <= 0:
            fail("预取未命中（from_prefetch 始终 False）")
            return 5
        ok(f"prefetch hits={hit}")

        frame2 = backend.seek_and_frame(min(target + 0.5, max(0.2, info.duration_sec - 0.1)))
        if frame2 is None:
            fail("二次 Seek 无帧")
            return 4
        ok(f"second seek ts={frame2[0]:.3f}")
        print("PASS  player SHM/prefetch/Seek")
        return 0
    except Exception as e:
        fail(str(e))
        return 1
    finally:
        try:
            backend.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
