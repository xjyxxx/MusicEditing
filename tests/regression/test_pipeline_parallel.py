"""回归：队列有限并行（切片阶段可重叠）。

用法（仓库根）:
  python tests/regression/test_pipeline_parallel.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
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
from core.pipeline_runner import run_pipeline_queue  # noqa: E402
from models.pipeline_model import (  # noqa: E402
    PipelineJob,
    PipelineJobState,
    PipelineSettings,
)
from models.video_model import HighlightSegment, SliceParams, VideoModel  # noqa: E402


def main() -> int:
    if not find_media_cli():
        fail("未找到 media_cli.exe")
        return 2
    video = find_test_video()
    if not video:
        fail("tests/ 下无测试视频")
        return 2

    out_root = tempfile.mkdtemp(prefix="me_reg_pipe_")
    second = Path(out_root) / "clip_b.mp4"
    shutil.copy2(video, second)
    paths = [str(video), str(second)]

    bridge = MediaBridge()
    jobs = [PipelineJob(path=p) for p in paths]
    settings = PipelineSettings(
        do_slice=True,
        do_enhance=False,
        do_watermark=False,
        scene="游戏高光",
        min_duration=0.5,
        max_duration=2.0,
        output_root=out_root,
        max_parallel=2,
        max_retries=0,
        max_output_gb=2.0,
    )

    active = 0
    max_active = 0
    lock = threading.Lock()

    def analyze_fn(video_m: VideoModel, params: SliceParams, report):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        report(20.0, "mock analyze")
        time.sleep(1.0)
        with lock:
            active -= 1
        end = min(1.0, max(0.4, float(video_m.duration_sec or 1.0) * 0.05))
        return [
            HighlightSegment(start_sec=0.0, end_sec=end, score=0.9, selected=True),
        ]

    cancel = threading.Event()
    skip = threading.Event()
    pause = threading.Event()
    pause.set()

    def on_update(i, job):
        pass

    t0 = time.monotonic()
    try:
        run_pipeline_queue(
            bridge=bridge,
            jobs=jobs,
            settings=settings,
            analyze_fn=analyze_fn,
            upscale_model_path="",
            watermark_model_path="",
            cancel_event=cancel,
            skip_event=skip,
            pause_event=pause,
            on_update=on_update,
        )
    except Exception as e:
        fail(f"队列异常: {e}")
        shutil.rmtree(out_root, ignore_errors=True)
        return 1

    elapsed = time.monotonic() - t0
    done = sum(1 for j in jobs if j.state == PipelineJobState.DONE)
    failed = [j for j in jobs if j.state == PipelineJobState.FAILED]
    ok(f"done={done}/{len(jobs)} elapsed={elapsed:.1f}s max_active={max_active}")

    if failed:
        fail("; ".join(j.error or j.message for j in failed))
        shutil.rmtree(out_root, ignore_errors=True)
        return 3
    if done != len(jobs):
        fail(f"未全部完成: {[j.state for j in jobs]}")
        shutil.rmtree(out_root, ignore_errors=True)
        return 3
    if max_active < 2:
        fail("并行未生效（切片阶段 max_active < 2）——检查 max_parallel")
        shutil.rmtree(out_root, ignore_errors=True)
        return 4

    from core.resource_cleanup import quota_status

    st = quota_status(out_root, settings.max_output_gb)
    ok(f"quota used={st['used_human']} limit={st['limit_human']}")

    shutil.rmtree(out_root, ignore_errors=True)
    print("PASS  pipeline parallel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
