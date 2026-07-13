"""无 UI 播放同步自测"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.app_logger import setup_logging
from core.player_backend import PlayerBackend

log = setup_logging("VideoPlayer", "WARNING")

VIDEO = Path(r"e:\code_2026\MusicEditing\tests\test_video.mp4")
PLAY_SEC = 8.0


def frame_index(sec: float, fi: float) -> int:
    if sec < 0:
        return -1
    return int(math.floor(sec / fi + 1e-9))


def main() -> int:
    backend = PlayerBackend()
    backend.set_hwaccel(True)
    info = backend.open(str(VIDEO))
    fi = 1.0 / max(info.fps, 1.0)
    backend.set_playback_scale(640, 360)
    backend.set_playback_filter(False)
    timer_ms = max(16, int(1000 / info.fps))

    last_ts = -fi
    shows = ticks = 0
    t_start = time.monotonic()

    while time.monotonic() - t_start < PLAY_SEC:
        t0 = time.monotonic()
        ticks += 1
        audio = time.monotonic() - t_start
        ai = frame_index(audio, fi)
        si = frame_index(last_ts, fi)
        if ai <= si:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            time.sleep(max(1, timer_ms - elapsed_ms) / 1000.0)
            continue
        want = si + 1
        if ai - si > 6:
            want = ai - 1
        target = max(0.0, want * fi - fi * 0.02)
        frame = backend.next_frame(min_ts=target, apply_filter=False)
        if frame:
            ts = frame[0]
            if frame_index(ts, fi) >= want:
                last_ts = ts
                shows += 1
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        sleep_ms = max(1, timer_ms - elapsed_ms)
        time.sleep(sleep_ms / 1000.0)

    expected = int(PLAY_SEC / fi)
    fps = shows / PLAY_SEC
    print(f"RESULT shows={shows}/{expected} ticks={ticks} fps={fps:.1f}")
    backend.shutdown()
    return 0 if shows >= expected * 0.85 else 2


if __name__ == "__main__":
    raise SystemExit(main())
