"""批量全流程编排：切片成片 → 超分 → 去水印（单线程顺序执行）。"""

from __future__ import annotations

import os
import threading
from typing import Callable, List, Optional

from models.pipeline_model import (
    PipelineJob,
    PipelineJobState,
    PipelinePhase,
    PipelineSettings,
    corner_watermark_regions,
)
from models.video_model import HighlightSegment, SliceParams, VideoModel


AnalyzeFn = Callable[
    [VideoModel, SliceParams, Callable[[float, str], None]],
    List[HighlightSegment],
]
ProgressFn = Callable[[int, PipelineJob], None]  # job_index, job snapshot


class PipelineCancelled(Exception):
    pass


class PipelineSkipped(Exception):
    pass


def _job_dir(settings: PipelineSettings, src_path: str) -> str:
    root = settings.output_root.strip() or os.path.join(
        os.path.dirname(os.path.abspath(src_path)), "pipeline_out"
    )
    base = os.path.splitext(os.path.basename(src_path))[0]
    out = os.path.join(root, base)
    os.makedirs(out, exist_ok=True)
    return out


def run_pipeline_queue(
    *,
    bridge,
    jobs: List[PipelineJob],
    settings: PipelineSettings,
    analyze_fn: AnalyzeFn,
    upscale_model_path: str,
    watermark_model_path: str,
    cancel_event: threading.Event,
    skip_event: threading.Event,
    pause_event: threading.Event,
    on_update: ProgressFn,
) -> None:
    """
    顺序处理 jobs。通过 on_update 回传状态（调用方用 Signal 抛到 UI 线程）。
    pause_event.clear() 表示暂停（阻塞在任务间隙）；skip_event 跳过当前任务剩余步骤。
    """
    for i, job in enumerate(jobs):
        _wait_if_paused(pause_event, cancel_event)
        if cancel_event.is_set():
            job.state = PipelineJobState.CANCELLED
            job.message = "队列已取消"
            on_update(i, job)
            for j in range(i + 1, len(jobs)):
                if jobs[j].state == PipelineJobState.WAITING:
                    jobs[j].state = PipelineJobState.CANCELLED
                    jobs[j].message = "队列已取消"
                    on_update(j, jobs[j])
            return

        if job.state in (PipelineJobState.DONE, PipelineJobState.SKIPPED, PipelineJobState.CANCELLED):
            continue

        skip_event.clear()
        job.state = PipelineJobState.RUNNING
        job.error = ""
        job.progress = 0.0
        job.message = "开始"
        on_update(i, job)

        try:
            result = _run_one(
                bridge=bridge,
                job=job,
                settings=settings,
                analyze_fn=analyze_fn,
                upscale_model_path=upscale_model_path,
                watermark_model_path=watermark_model_path,
                cancel_event=cancel_event,
                skip_event=skip_event,
                pause_event=pause_event,
                on_tick=lambda: on_update(i, job),
            )
            job.result_path = result
            job.state = PipelineJobState.DONE
            job.phase = PipelinePhase.DONE
            job.progress = 100.0
            job.message = f"完成 → {os.path.basename(result)}" if result else "完成"
            on_update(i, job)
        except PipelineSkipped:
            job.state = PipelineJobState.SKIPPED
            job.message = "已跳过"
            on_update(i, job)
        except PipelineCancelled:
            job.state = PipelineJobState.CANCELLED
            job.message = "已取消"
            on_update(i, job)
            for j in range(i + 1, len(jobs)):
                if jobs[j].state == PipelineJobState.WAITING:
                    jobs[j].state = PipelineJobState.CANCELLED
                    jobs[j].message = "队列已取消"
                    on_update(j, jobs[j])
            return
        except Exception as e:
            job.state = PipelineJobState.FAILED
            job.error = str(e)
            job.message = f"失败: {e}"
            on_update(i, job)


def _wait_if_paused(pause_event: threading.Event, cancel_event: threading.Event) -> None:
    """pause_event 置位 = 运行中；clear = 暂停。"""
    while not pause_event.is_set():
        if cancel_event.is_set():
            return
        pause_event.wait(timeout=0.2)


def _check(
    cancel_event: threading.Event,
    skip_event: threading.Event,
    pause_event: threading.Event | None = None,
) -> None:
    if pause_event is not None:
        _wait_if_paused(pause_event, cancel_event)
    if cancel_event.is_set():
        raise PipelineCancelled()
    if skip_event.is_set():
        raise PipelineSkipped()


def _run_one(
    *,
    bridge,
    job: PipelineJob,
    settings: PipelineSettings,
    analyze_fn: AnalyzeFn,
    upscale_model_path: str,
    watermark_model_path: str,
    cancel_event: threading.Event,
    skip_event: threading.Event,
    pause_event: threading.Event,
    on_tick: Callable[[], None],
) -> str:
    path = os.path.abspath(job.path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"文件不存在: {path}")

    out_dir = _job_dir(settings, path)
    current = path

    def report_phase(phase: PipelinePhase, p: float, msg: str) -> None:
        _check(cancel_event, skip_event, pause_event)
        job.phase = phase
        job.progress = max(0.0, min(100.0, float(p)))
        job.message = msg
        on_tick()

    # 1) probe
    report_phase(PipelinePhase.PROBE, 2.0, "探测视频…")
    info = bridge.probe_video(path)
    video = VideoModel(
        file_path=info.file_path,
        width=info.width,
        height=info.height,
        duration_sec=info.duration_sec,
        fps=info.fps,
        total_frames=info.total_frames,
        codec_name=info.codec_name,
        format_name=info.format_name,
    )
    fps = video.fps or 25.0

    # 2) slice + export
    if settings.do_slice:
        report_phase(PipelinePhase.SLICE, 5.0, "切片分析…")

        def slice_report(p: float, msg: str) -> None:
            report_phase(PipelinePhase.SLICE, 5.0 + p * 0.35, msg)

        params = SliceParams(
            scene=settings.scene,
            min_duration=settings.min_duration,
            max_duration=settings.max_duration,
            sensitivity=settings.sensitivity,
        )
        segments = analyze_fn(video, params, slice_report)
        selected = [s for s in segments if s.selected and s.end_sec > s.start_sec]
        if not selected:
            raise RuntimeError("未识别到可导出的高光片段")

        report_phase(PipelinePhase.EXPORT, 42.0, "导出高光成片…")

        def export_report(p: float, msg: str) -> None:
            report_phase(PipelinePhase.EXPORT, 42.0 + p * 0.18, msg)

        ranges = [(s.start_sec, s.end_sec) for s in selected]
        _clips, merged = bridge.export_highlights(
            path, ranges, out_dir, concat=True, on_progress=export_report,
        )
        if not merged or not os.path.isfile(merged):
            raise RuntimeError("高光成片未生成")
        current = merged
        # 成片后重新探测分辨率（超分/水印用）
        info = bridge.probe_video(current)
        video = VideoModel(
            file_path=info.file_path,
            width=info.width,
            height=info.height,
            duration_sec=info.duration_sec,
            fps=info.fps,
            total_frames=info.total_frames,
            codec_name=info.codec_name,
            format_name=info.format_name,
        )
        fps = video.fps or fps

    # 3) enhance
    if settings.do_enhance:
        report_phase(PipelinePhase.ENHANCE, 62.0, "超分处理…")
        be = (settings.enhance_backend or "opencv").strip().lower()
        if be in ("opencv", "cv", "fast", "bicubic"):
            be = "opencv"
        else:
            be = "realesrgan"
        sc = 2 if int(settings.enhance_scale) == 2 else 4
        enhanced = os.path.join(out_dir, f"enhanced_{sc}x.mp4")
        end_sec = 0.0
        if settings.enhance_max_sec and settings.enhance_max_sec > 0:
            end_sec = min(float(settings.enhance_max_sec), float(video.duration_sec or 0) or settings.enhance_max_sec)

        def enhance_report(p: float, msg: str) -> None:
            report_phase(PipelinePhase.ENHANCE, 62.0 + p * 0.22, msg)

        model = "-" if be == "opencv" else upscale_model_path
        bridge.upscale_video(
            model,
            current,
            enhanced,
            fps=fps,
            scale=sc,
            strength=int(settings.enhance_strength),
            start_sec=0.0,
            end_sec=end_sec,
            on_progress=enhance_report,
            backend=be,
        )
        if not os.path.isfile(enhanced):
            raise RuntimeError("超分输出不存在")
        current = enhanced
        info = bridge.probe_video(current)
        video.width = info.width
        video.height = info.height
        video.duration_sec = info.duration_sec
        video.fps = info.fps or fps
        fps = video.fps or fps

    # 4) watermark
    if settings.do_watermark:
        regions = corner_watermark_regions(
            int(video.width), int(video.height), settings.watermark_corner,
        )
        if not regions:
            report_phase(PipelinePhase.WATERMARK, 90.0, "去水印已跳过（未选角标区域）")
        else:
            report_phase(PipelinePhase.WATERMARK, 88.0, "去水印…")
            be = (settings.watermark_backend or "opencv").strip().lower()
            if be in ("opencv", "cv", "fast"):
                be = "opencv"
            else:
                be = "lama"
            wm_out = os.path.join(out_dir, "final_nowm.mp4")

            def wm_report(p: float, msg: str) -> None:
                report_phase(PipelinePhase.WATERMARK, 88.0 + p * 0.10, msg)

            model = "-" if be == "opencv" else watermark_model_path
            bridge.watermark_inpaint_video(
                model,
                current,
                wm_out,
                regions,
                fps,
                start_sec=0.0,
                end_sec=0.0,
                on_progress=wm_report,
                backend=be,
            )
            if not os.path.isfile(wm_out):
                raise RuntimeError("去水印输出不存在")
            current = wm_out

    report_phase(PipelinePhase.DONE, 100.0, "完成")
    return current
