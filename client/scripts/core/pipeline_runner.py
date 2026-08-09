"""批量全流程编排：切片成片 → 超分 → 去水印。

默认有限并行（max_parallel=2）：多任务可同时跑切片/导出；
超分+去水印用信号量串行，避免 GPU/磁盘互抢。
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    处理 jobs。max_parallel>1 时有限并行；超分/去水印串行。
    pause_event.clear() 表示暂停；skip_event 跳过其中一个进行中任务。
    """
    workers = max(1, min(int(settings.max_parallel or 1), 4, len(jobs) or 1))
    heavy_lock = threading.Semaphore(1)  # 超分 + 去水印
    update_lock = threading.Lock()

    def safe_update(index: int, job: PipelineJob) -> None:
        with update_lock:
            on_update(index, job)

    def process_one(i: int, job: PipelineJob) -> None:
        _wait_if_paused(pause_event, cancel_event)
        if cancel_event.is_set():
            job.state = PipelineJobState.CANCELLED
            job.message = "队列已取消"
            safe_update(i, job)
            return

        if job.state in (PipelineJobState.DONE, PipelineJobState.SKIPPED, PipelineJobState.CANCELLED):
            return

        attempts = 1 + max(0, int(settings.max_retries or 0))
        last_err = ""
        for attempt in range(attempts):
            job.state = PipelineJobState.RUNNING
            job.error = ""
            job.progress = 0.0
            if attempt > 0:
                job.message = f"重试 {attempt}/{attempts - 1}…"
                safe_update(i, job)
            else:
                job.message = "开始"
                safe_update(i, job)

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
                    heavy_lock=heavy_lock,
                    on_tick=lambda: safe_update(i, job),
                )
                job.result_path = result
                job.state = PipelineJobState.DONE
                job.phase = PipelinePhase.DONE
                job.progress = 100.0
                job.message = f"完成 → {os.path.basename(result)}" if result else "完成"
                safe_update(i, job)
                _maybe_enforce_quota(settings)
                return
            except PipelineSkipped:
                job.state = PipelineJobState.SKIPPED
                job.message = "已跳过"
                safe_update(i, job)
                return
            except PipelineCancelled:
                job.state = PipelineJobState.CANCELLED
                job.message = "已取消"
                safe_update(i, job)
                return
            except Exception as e:
                last_err = str(e)
                if attempt + 1 < attempts and not cancel_event.is_set():
                    job.message = f"失败将重试: {e}"
                    safe_update(i, job)
                    continue
                job.state = PipelineJobState.FAILED
                job.error = last_err
                job.message = f"失败: {last_err}"
                safe_update(i, job)
                return

    if workers <= 1:
        for i, job in enumerate(jobs):
            if cancel_event.is_set():
                for j in range(i, len(jobs)):
                    if jobs[j].state == PipelineJobState.WAITING:
                        jobs[j].state = PipelineJobState.CANCELLED
                        jobs[j].message = "队列已取消"
                        safe_update(j, jobs[j])
                return
            process_one(i, job)
        return

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="pipeline") as pool:
        futs = {pool.submit(process_one, i, job): i for i, job in enumerate(jobs)}
        for fut in as_completed(futs):
            if cancel_event.is_set():
                break
            try:
                fut.result()
            except Exception:
                pass
        if cancel_event.is_set():
            for j, job in enumerate(jobs):
                if job.state == PipelineJobState.WAITING:
                    job.state = PipelineJobState.CANCELLED
                    job.message = "队列已取消"
                    safe_update(j, job)


def _maybe_enforce_quota(settings: PipelineSettings) -> None:
    root = (settings.output_root or "").strip()
    if not root or not os.path.isdir(root):
        return
    max_gb = float(getattr(settings, "max_output_gb", 0) or 0)
    if max_gb <= 0:
        return
    try:
        from core.resource_cleanup import enforce_output_quota, format_bytes

        freed, paths = enforce_output_quota(root, max_gb=max_gb, delete_oldest=True)
        if freed > 0:
            import logging
            logging.getLogger("Pipeline").info(
                "队列产物超限，已清理 %s（%d 个文件）root=%s",
                format_bytes(freed), len(paths), root,
            )
    except Exception:
        pass


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
    # 消费一次跳过，避免并行时所有任务一起跳
    if skip_event.is_set():
        skip_event.clear()
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
    heavy_lock: threading.Semaphore,
    on_tick: Callable[[], None],
) -> str:
    path = os.path.abspath(job.path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"文件不存在: {path}")

    out_dir = _job_dir(settings, path)
    current = path

    from core.progress_eta import PhaseEtaTracker, with_phase_eta

    weights: dict[str, float] = {"probe": 0.02}
    if settings.do_slice:
        weights["slice"] = 0.28
        weights["export"] = 0.14
    tpl_key = getattr(settings, "film_template", "") or ""
    from core.film_templates import get_film_template, clamp_ranges_to_budget

    film_tpl = get_film_template(tpl_key)
    if film_tpl and film_tpl.do_vertical:
        weights["vertical"] = 0.12
    if settings.do_enhance:
        weights["enhance"] = 0.35 if settings.do_watermark else 0.45
    if settings.do_watermark:
        weights["watermark"] = 0.12
    # 归一化
    s = sum(weights.values()) or 1.0
    weights = {k: v / s for k, v in weights.items()}
    _eta = PhaseEtaTracker(weights=weights)

    def report_phase(phase: PipelinePhase, p: float, msg: str) -> None:
        _check(cancel_event, skip_event, pause_event)
        # 映射到权重键
        key = {
            PipelinePhase.PROBE: "probe",
            PipelinePhase.SLICE: "slice",
            PipelinePhase.EXPORT: "export",
            PipelinePhase.VERTICAL: "vertical",
            PipelinePhase.ENHANCE: "enhance",
            PipelinePhase.WATERMARK: "watermark",
            PipelinePhase.DONE: "enhance",
        }.get(phase, "")
        phase_local = {
            "probe": min(100.0, p / 0.05) if p < 5 else 100.0,
            "slice": max(0.0, min(100.0, (p - 5.0) / 0.35)),
            "export": max(0.0, min(100.0, (p - 42.0) / 0.14)),
            "vertical": max(0.0, min(100.0, (p - 55.0) / 0.10)),
            "enhance": max(0.0, min(100.0, (p - 65.0) / 0.22)),
            "watermark": max(0.0, min(100.0, (p - 88.0) / 0.12)),
        }.get(key, p)
        if key:
            _eta.set_phase(key, phase_local)
        job.phase = phase
        job.progress = max(0.0, min(100.0, float(_eta.overall_pct())))
        job.message = with_phase_eta(msg, _eta)
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

    # 2) slice + export（可与其它任务并行）
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

        ranges = [(s.start_sec, s.end_sec) for s in selected]
        if film_tpl is not None:
            ranges = clamp_ranges_to_budget(ranges, film_tpl.max_total_sec)
            report_phase(
                PipelinePhase.EXPORT,
                42.0,
                f"导出高光成片（模板 {film_tpl.label}，≤{film_tpl.max_total_sec:.0f}s）…",
            )

        def export_report(p: float, msg: str) -> None:
            report_phase(PipelinePhase.EXPORT, 42.0 + p * 0.14, msg)

        naming_preset = film_tpl.platform if film_tpl else "custom"
        _clips, merged = bridge.export_highlights(
            path, ranges, out_dir, concat=True, on_progress=export_report,
            naming_preset=naming_preset,
            use_naming_scheme=True,
        )
        if not merged or not os.path.isfile(merged):
            raise RuntimeError("高光成片未生成")
        current = merged
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

        # 模板：竖屏 + 封面/话题
        if film_tpl is not None and film_tpl.do_vertical:
            report_phase(PipelinePhase.VERTICAL, 55.0, f"竖屏成片（{film_tpl.label}）…")

            def vert_report(p: float, msg: str) -> None:
                report_phase(PipelinePhase.VERTICAL, 55.0 + p * 0.08, msg)

            from core.export_naming import default_vertical_name
            from core.film_templates import apply_publish_pack_for_template

            vert_name = default_vertical_name(
                path, preset=film_tpl.platform, ext="mp4",
            )
            vert_path = os.path.join(out_dir, vert_name)
            bridge.export_vertical_short(
                current,
                vert_path,
                width=film_tpl.vertical_w,
                height=film_tpl.vertical_h,
                track_mode="face",
                quality=film_tpl.quality,
                on_progress=vert_report,
            )
            if not os.path.isfile(vert_path):
                raise RuntimeError("竖屏成片未生成")
            current = vert_path
            try:
                cover, draft = apply_publish_pack_for_template(
                    bridge, current, film_tpl,
                    duration_sec=float(video.duration_sec or 0),
                )
                extra = []
                if cover:
                    extra.append(os.path.basename(cover))
                if draft:
                    extra.append(os.path.basename(draft))
                tail = f" · 已写 {'/'.join(extra)}" if extra else ""
                report_phase(PipelinePhase.VERTICAL, 63.0, f"竖屏完成{tail}")
            except Exception as e:
                report_phase(PipelinePhase.VERTICAL, 63.0, f"竖屏完成（发布包跳过: {e}）")
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

    # 3–4) 超分 / 去水印：串行占坑；未启用则完全跳过（避免空等）
    need_heavy = bool(settings.do_enhance or settings.do_watermark)
    if need_heavy:
        # 仅当锁被占用时才提示等待，避免「只切片」或空闲时假等待文案
        got = heavy_lock.acquire(blocking=False)
        if not got:
            report_phase(
                PipelinePhase.ENHANCE if settings.do_enhance else PipelinePhase.WATERMARK,
                60.0,
                "等待超分/去水印空闲…",
            )
            while not heavy_lock.acquire(timeout=0.2):
                _check(cancel_event, skip_event, pause_event)
        try:
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
                    end_sec = min(
                        float(settings.enhance_max_sec),
                        float(video.duration_sec or 0) or settings.enhance_max_sec,
                    )

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
        finally:
            heavy_lock.release()

    report_phase(PipelinePhase.DONE, 100.0, "完成")
    return current
