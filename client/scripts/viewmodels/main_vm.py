"""主视图模型 - MVVM 双向绑定核心"""



from __future__ import annotations



import os

import tempfile
import threading

from typing import List, Optional



from PySide6.QtCore import QObject, Property, Signal, Slot



from core.app_logic import AppLogic, load_app_config

from core.asr_engine import AsrEngine

from core.speech_highlights import (
    clips_from_speech_ranges,
    score_transcript,
)

from core.media_bridge import MediaBridge
from core.pipeline_runner import run_pipeline_queue

from models.pipeline_model import PipelineJob, PipelineSettings

from models.video_model import (

    AppState, HighlightSegment, SliceParams, TaskModel, TaskState, TaskType, VideoModel,

)



SPEECH_SCENES = frozenset({"演讲金句", "日常精彩片段", "自定义识别"})
LOUDNESS_SCENES = frozenset({"响度高潮"})





class MainViewModel(QObject):

    """主窗口 ViewModel，连接 Model 与 View"""



    videoLoaded = Signal(object)

    progressUpdated = Signal(int, float, str)

    taskStateChanged = Signal(int, int)

    highlightsReady = Signal(list)

    watermarkProgress = Signal(int, float, str)

    watermarkFinished = Signal(int, str)

    enhanceProgress = Signal(int, float, str)

    enhanceFinished = Signal(int, str)

    interpolateProgress = Signal(int, float, str)

    interpolateFinished = Signal(int, str)

    colorGradeProgress = Signal(int, float, str)

    colorGradeFinished = Signal(int, str)

    coverProgress = Signal(int, float, str)

    coverFinished = Signal(int, str, object)  # task_id, path, CoverResult|None

    audioFxProgress = Signal(int, float, str)

    audioFxFinished = Signal(int, str)

    bgmMixProgress = Signal(int, float, str)

    bgmMixFinished = Signal(int, str)

    sfxOverlayProgress = Signal(int, float, str)

    sfxOverlayFinished = Signal(int, str)

    demucsProgress = Signal(int, float, str)

    demucsFinished = Signal(int, str)

    exportFinished = Signal(str)

    silenceFinished = Signal(str)

    verticalExportProgress = Signal(int, float, str)

    verticalExportFinished = Signal(str)

    downloadProgress = Signal(int, float, str)

    downloadFinished = Signal(str)

    downloadProbeReady = Signal(object)

    errorOccurred = Signal(str)

    statusMessageChanged = Signal(str)

    # 批量全流程队列
    pipelineItemUpdated = Signal(int, object)  # index, PipelineJob
    pipelineFinished = Signal()
    pipelineStatusChanged = Signal(str)

    gpuNameChanged = Signal(str)

    authTypeChanged = Signal(str)



    def __init__(self, parent=None):

        super().__init__(parent)

        self._app = AppLogic()

        self._state = AppState()

        self._bridge: Optional[MediaBridge] = None

        self._asr = AsrEngine(self._app.vosk_model_dir or None)

        self._status_message = "就绪"

        self._next_task_id = 1
        self._slice_running = False
        self._import_running = False
        self._pipeline_running = False
        self._pipeline_jobs: list[PipelineJob] = []
        self._pipeline_cancel = threading.Event()
        self._pipeline_skip = threading.Event()
        # set = 运行；clear = 暂停
        self._pipeline_pause = threading.Event()
        self._pipeline_pause.set()



        try:

            self._bridge = MediaBridge()

            self._bridge.set_prefer_hw_decode(self._app.prefer_hw_decode)
            # 超分 / LaMa：有 NVIDIA 时尝试 ORT CUDA EP（失败会回退 CPU）
            self._bridge.set_prefer_cuda(self._app.use_gpu)
            self._bridge.set_yt_dlp_cookies_from_browser(
                getattr(self._app, "yt_dlp_cookies_from_browser", "") or ""
            )
            self._bridge.set_yt_dlp_cookies_file(
                getattr(self._app, "yt_dlp_cookies_file", "") or ""
            )

            self._status_message = f"引擎就绪 (FFmpeg {self._bridge.ffmpeg_version})"

        except FileNotFoundError as e:

            self._status_message = str(e)



        self.gpuNameChanged.emit(self.gpu_name)

        self.authTypeChanged.emit(self.auth_type)



    @property

    def bridge(self) -> Optional[MediaBridge]:

        return self._bridge



    @Property(str, notify=statusMessageChanged)

    def status_message(self) -> str:

        return self._status_message



    @Property(str, notify=gpuNameChanged)

    def gpu_name(self) -> str:

        if self._app.use_gpu:

            return self._app.gpu_info["name"]

        return "CPU 模式"



    @Property(str, notify=authTypeChanged)

    def auth_type(self) -> str:

        return self._app.auth_type

    @property
    def gpu_enabled(self) -> bool:
        return bool(self._app.prefer_hw_decode)

    @property
    def output_dir(self) -> str:
        return getattr(self._app, "output_dir", "") or ""



    @property
    def is_licensed(self) -> bool:
        return bool(getattr(self._app, "is_licensed", False))

    def require_feature(self, feature: str) -> tuple[bool, str]:
        """试用门禁。返回 (ok, tip)。正式版一律放行。"""
        if self.is_licensed:
            return True, ""
        tips = {
            "enhance_ai_4x": "试用版不可用 AI 超分 4×，请到「个人中心」兑换正式版，或改用 2× / 快速 OpenCV。",
            "pipeline_queue": "试用版不可用批量全流程队列，请到「个人中心」兑换正式版。",
            "watermark_lama": "试用版不可用精修去水印（LaMa），请到「个人中心」兑换正式版，或改用「快速」。",
        }
        tip = tips.get(feature, "该功能需正式版，请到「个人中心」兑换卡密。")
        return False, tip

    @Property(str, constant=True)

    def version(self) -> str:

        return self._app.version



    @Slot(str)

    def import_video(self, file_path: str):
        """探测视频元数据；probe 在后台线程，完成后经 Signal 更新 UI。"""

        if not self._bridge:

            self.errorOccurred.emit("媒体引擎未加载，请先编译 C++ 核心库")

            return



        if not os.path.isfile(file_path):

            self.errorOccurred.emit(f"文件不存在: {file_path}")

            return

        # 纯音频由首页播放器走 QMediaPlayer；勿 probe_video（会报导入失败）
        _audio_exts = {
            ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus",
            ".aiff", ".ape",
        }
        if os.path.splitext(file_path)[1].lower() in _audio_exts:
            self._status_message = (
                f"已打开音频: {os.path.basename(file_path)}（不作为视频导入）"
            )
            self.statusMessageChanged.emit(self._status_message)
            return



        if self._import_running:

            self.errorOccurred.emit("正在导入视频，请稍候")

            return



        bridge = self._bridge

        path = os.path.abspath(file_path)

        self._import_running = True

        self._status_message = f"正在导入: {os.path.basename(path)}…"

        self.statusMessageChanged.emit(self._status_message)



        def run():

            try:

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

                self._state.current_video = video

                self._status_message = (

                    f"已导入: {os.path.basename(path)} "

                    f"({video.width}x{video.height}, {video.duration_sec:.1f}s)"

                )

                self.statusMessageChanged.emit(self._status_message)

                self.videoLoaded.emit(video)

            except Exception as e:

                self.errorOccurred.emit(f"导入失败: {e}")

            finally:

                self._import_running = False



        import threading

        threading.Thread(target=run, daemon=True).start()



    @Slot(str)

    def import_image(self, file_path: str):

        if not os.path.isfile(file_path):

            self.errorOccurred.emit(f"文件不存在: {file_path}")

            return

        self._state.current_image_path = file_path

        self._status_message = f"已导入图片: {os.path.basename(file_path)}"

        self.statusMessageChanged.emit(self._status_message)



    @Slot(float, float)

    def update_watermark_range(self, start_sec: float, end_sec: float):

        self._state.watermark_params.start_sec = start_sec

        self._state.watermark_params.end_sec = end_sec



    @Slot(str, str, list)

    def start_watermark_image(

        self, input_path: str, output_path: str, regions: list, backend: str = "lama",

    ):

        be = (backend or "lama").strip().lower()

        if be in ("opencv", "cv", "fast"):

            be = "opencv"

        else:

            be = "lama"

        if be == "lama":
            ok, tip = self.require_feature("watermark_lama")
            if not ok:
                self.errorOccurred.emit(tip)
                return

        self._state.watermark_params.backend = be



        def work(bridge, report):

            model = self._watermark_model_path(be)

            return bridge.watermark_inpaint_image(

                model, input_path, output_path, regions, backend=be,

            )



        self._run_watermark_task(

            TaskType.WATERMARK, input_path, work, output_path, backend=be,

        )



    @Slot(str, list, float, float)

    def start_watermark_video(

        self,

        output_path: str,

        regions: list,

        start_sec: float,

        end_sec: float,

        backend: str = "opencv",

    ):

        video = self._state.current_video

        if not video or not self._bridge:

            self.errorOccurred.emit("请先导入视频")

            return

        input_path = video.file_path

        fps = video.fps or 25.0

        be = (backend or "opencv").strip().lower()

        if be in ("opencv", "cv", "fast"):

            be = "opencv"

        else:

            be = "lama"

        if be == "lama":
            ok, tip = self.require_feature("watermark_lama")
            if not ok:
                self.errorOccurred.emit(tip)
                return

        self._state.watermark_params.backend = be



        def work(bridge, report):

            model = self._watermark_model_path(be)

            return bridge.watermark_inpaint_video(

                model, input_path, output_path, regions,

                fps, start_sec, end_sec, on_progress=report, backend=be,

            )



        self._run_watermark_task(

            TaskType.WATERMARK, input_path, work, output_path, backend=be,

        )



    def _watermark_model_path(self, backend: str) -> str:

        if backend == "opencv":

            return "-"

        path = self._app.lama_model_path

        if not path or not os.path.isfile(path):

            raise RuntimeError(
                "未找到 LaMa 模型（models/lama.onnx）。\n"
                "请在项目根目录运行：scripts\\download_lama_model.bat\n"
                "下载完成后重启 UI；精修去水印需要该模型。"
            )

        return path



    def _lama_model_path(self) -> str:

        return self._watermark_model_path("lama")



    def _run_watermark_task(

        self, task_type, file_path, worker_fn, output_path: str, backend: str = "lama",

    ):

        if not self._bridge:

            self.errorOccurred.emit("媒体引擎未加载")

            return

        if not self._bridge.watermark_available:

            self.errorOccurred.emit("ONNX Runtime 未就绪，请先 build_x64.bat 编译")

            return

        task = TaskModel(

            task_id=self._next_task_id,

            task_type=task_type,

            file_path=file_path,

            state=TaskState.PROCESSING,

        )

        self._next_task_id += 1

        self._state.tasks.append(task)

        task_id = task.task_id

        bridge = self._bridge

        label = "OpenCV 快速去水印" if backend == "opencv" else "LaMa 精修去水印"



        def run():

            try:

                from core.progress_eta import EtaTracker, with_eta
                eta = EtaTracker()

                def report(p: float, msg: str):

                    task.progress = p

                    self.watermarkProgress.emit(task_id, p, with_eta(msg, p, eta))



                report(1.0, f"{label}处理中…")

                result = worker_fn(bridge, report)

                out = result or output_path

                task.state = TaskState.COMPLETED

                task.progress = 100.0

                self.taskStateChanged.emit(task_id, TaskState.COMPLETED)

                self.watermarkFinished.emit(task_id, out)

                self._status_message = f"去水印完成: {os.path.basename(out)}"

                self.statusMessageChanged.emit(self._status_message)

            except Exception as e:

                task.state = TaskState.FAILED

                self.taskStateChanged.emit(task_id, TaskState.FAILED)

                self.errorOccurred.emit(str(e))



        import threading

        threading.Thread(target=run, daemon=True).start()



    @Slot(float, float)

    def update_enhance_range(self, start_sec: float, end_sec: float):

        self._state.enhance_params.start_sec = start_sec

        self._state.enhance_params.end_sec = end_sec



    def _upscale_model_path(self, backend: str) -> str:

        if backend == "opencv":

            return "-"

        path = self._app.realesrgan_model_path

        if not path or not os.path.isfile(path):

            raise FileNotFoundError(
                "未找到 Real-ESRGAN 模型（models/realesr-general-x4v3.onnx）。\n"
                "请在项目根目录运行：scripts\\download_realesrgan_model.bat\n"
                "下载完成后重启 UI；也可先用「快速 · OpenCV」超分。"
            )

        return path

    def ai_runtime_hint(self) -> str:
        """GPU 推理 / 模型就绪一句话状态。"""
        gpu = "GPU 推理开" if self._app.use_gpu else "GPU 推理关（CPU）"
        sr_ok = bool(
            getattr(self._app, "realesrgan_model_path", "")
            and os.path.isfile(self._app.realesrgan_model_path)
        )
        lama_ok = bool(
            getattr(self._app, "lama_model_path", "")
            and os.path.isfile(self._app.lama_model_path)
        )
        parts = [gpu]
        if self._bridge and self._app.use_gpu:
            ok_ep, ep_msg = self._bridge.probe_ort_cuda()
            if not ok_ep:
                parts.append(ep_msg)
            else:
                parts.append("CUDA EP✓ · tile自动≈512")
        parts.append("超分模型✓" if sr_ok else "超分模型缺（download_realesrgan_model.bat）")
        parts.append("LaMa✓" if lama_ok else "LaMa缺（download_lama_model.bat）")
        return " · ".join(parts)



    @Slot(str, str, int, str, int)

    def start_enhance_image(

        self, input_path: str, output_path: str, scale: int = 2,
        backend: str = "realesrgan", strength: int = 65,

    ):

        be = (backend or "realesrgan").strip().lower()

        if be in ("opencv", "cv", "fast", "bicubic"):

            be = "opencv"

        else:

            be = "realesrgan"

        sc = 2 if int(scale) == 2 else 4
        sp = max(0, min(100, int(strength)))

        if be == "realesrgan" and sc == 4:
            ok, tip = self.require_feature("enhance_ai_4x")
            if not ok:
                self.errorOccurred.emit(tip)
                return

        self._state.enhance_params.backend = be

        self._state.enhance_params.scale = sc
        self._state.enhance_params.strength = sp



        def work(bridge, report):

            model = self._upscale_model_path(be)

            tile = int(getattr(self._state.enhance_params, "tile", 0) or 0)
            bridge.set_upscale_tile(tile)
            return bridge.upscale_image(

                model, input_path, output_path, scale=sc, strength=sp, backend=be,

            )



        self._run_enhance_task(

            TaskType.ENHANCE, input_path, work, output_path, backend=be, scale=sc,

        )



    @Slot(str, float, float, int, str, int)

    def start_enhance_video(

        self,

        output_path: str,

        start_sec: float,

        end_sec: float,

        scale: int = 2,

        backend: str = "opencv",
        strength: int = 65,

    ):

        video = self._state.current_video

        if not video or not self._bridge:

            self.errorOccurred.emit("请先导入视频")

            return

        input_path = video.file_path

        fps = video.fps or 25.0

        be = (backend or "opencv").strip().lower()

        if be in ("opencv", "cv", "fast", "bicubic"):

            be = "opencv"

        else:

            be = "realesrgan"

        sc = 2 if int(scale) == 2 else 4
        sp = max(0, min(100, int(strength)))

        if be == "realesrgan" and sc == 4:
            ok, tip = self.require_feature("enhance_ai_4x")
            if not ok:
                self.errorOccurred.emit(tip)
                return

        self._state.enhance_params.backend = be

        self._state.enhance_params.scale = sc
        self._state.enhance_params.strength = sp

        self._state.enhance_params.start_sec = start_sec

        self._state.enhance_params.end_sec = end_sec



        def work(bridge, report):

            model = self._upscale_model_path(be)

            tile = int(getattr(self._state.enhance_params, "tile", 0) or 0)
            bridge.set_upscale_tile(tile)
            return bridge.upscale_video(

                model,

                input_path,

                output_path,

                fps=fps,

                scale=sc,
                strength=sp,

                start_sec=start_sec,

                end_sec=end_sec,

                on_progress=report,

                backend=be,

            )



        self._run_enhance_task(

            TaskType.ENHANCE, input_path, work, output_path, backend=be, scale=sc,

        )



    def _run_enhance_task(

        self, task_type, file_path, worker_fn, output_path: str,

        backend: str = "opencv", scale: int = 2,

    ):

        if not self._bridge:

            self.errorOccurred.emit("媒体引擎未加载")

            return

        if not self._bridge.upscale_available:

            self.errorOccurred.emit("ONNX Runtime 未就绪，请先 build_x64.bat 编译")

            return

        task = TaskModel(

            task_id=self._next_task_id,

            task_type=task_type,

            file_path=file_path,

            state=TaskState.PROCESSING,

        )

        self._next_task_id += 1

        self._state.tasks.append(task)

        task_id = task.task_id

        bridge = self._bridge

        label = (

            f"OpenCV {scale}x 放大" if backend == "opencv"

            else f"Real-ESRGAN {scale}x 超分"

        )



        def run():

            try:

                from core.progress_eta import EtaTracker, with_eta
                eta = EtaTracker()

                def report(p: float, msg: str):

                    task.progress = p

                    self.enhanceProgress.emit(task_id, p, with_eta(msg, p, eta))



                report(1.0, f"{label}处理中…")

                result = worker_fn(bridge, report)

                out = result or output_path

                task.state = TaskState.COMPLETED

                task.progress = 100.0

                self.taskStateChanged.emit(task_id, TaskState.COMPLETED)

                self.enhanceFinished.emit(task_id, out)

                self._status_message = f"画质增强完成: {os.path.basename(out)}"

                self.statusMessageChanged.emit(self._status_message)

            except Exception as e:

                task.state = TaskState.FAILED

                self.taskStateChanged.emit(task_id, TaskState.FAILED)

                self.errorOccurred.emit(str(e))



        import threading

        threading.Thread(target=run, daemon=True).start()



    @Slot()

    def start_slice_analysis(self):
        """AI 切片分析：ASR/LLM/规则在后台线程执行，不阻塞 UI。"""

        video = self._state.current_video

        if not video or not self._bridge:

            self.errorOccurred.emit("请先导入视频")

            return



        if self._slice_running:

            self.errorOccurred.emit("切片分析正在进行中")

            return



        # 拷贝参数，避免后台跑时用户改滑条产生竞态

        src = self._state.slice_params

        params = SliceParams(

            scene=src.scene,

            min_duration=src.min_duration,

            max_duration=src.max_duration,

            sensitivity=src.sensitivity,

        )

        task = TaskModel(

            task_id=self._next_task_id,

            task_type=TaskType.SLICE,

            file_path=video.file_path,

            state=TaskState.PROCESSING,

            total_frames=video.total_frames or 1,

        )

        self._next_task_id += 1

        self._state.tasks.append(task)

        self.taskStateChanged.emit(task.task_id, TaskState.PROCESSING)

        self._slice_running = True

        self._status_message = "切片分析进行中…"

        self.statusMessageChanged.emit(self._status_message)



        def run():

            try:

                def report(progress: float, msg: str):

                    task.progress = progress

                    self.progressUpdated.emit(task.task_id, progress, msg)



                if params.scene in SPEECH_SCENES:

                    segments = self._analyze_speech_pipeline(video, params, report)

                elif params.scene in LOUDNESS_SCENES:

                    segments = self._analyze_loudness_climaxes(video, params, report)

                else:

                    segments = self._analyze_game_fallback(video, params, report)



                self._state.highlight_segments = segments

                task.state = TaskState.COMPLETED

                task.progress = 100.0

                self.taskStateChanged.emit(task.task_id, TaskState.COMPLETED)

                self.progressUpdated.emit(task.task_id, 100.0, "分析完成")

                self.highlightsReady.emit(segments)



                if params.scene in SPEECH_SCENES:
                    mode = "LLM+ASR"
                elif params.scene in LOUDNESS_SCENES:
                    mode = "ebur128"
                else:
                    mode = "规则"

                self._status_message = f"[{mode}] 识别出 {len(segments)} 个高光片段"

                self.statusMessageChanged.emit(self._status_message)

            except Exception as e:

                task.state = TaskState.FAILED

                self.taskStateChanged.emit(task.task_id, TaskState.FAILED)

                self.errorOccurred.emit(f"分析失败: {e}")

            finally:

                self._slice_running = False



        import threading

        threading.Thread(target=run, daemon=True).start()



    def _analyze_speech_pipeline(

        self, video: VideoModel, params: SliceParams, report

    ) -> List[HighlightSegment]:

        """演讲金句 / 日常精彩 / 自定义：

        优先 Vosk ASR → media_cli analyze-speech（LLM 或 C++ 规则）；
        ASR 成功但 CLI 失败时用 Python 金句词打分；
        无 Vosk 时用 silencedetect 人声段兜底（仍可选中「演讲金句」）。
        """

        with tempfile.TemporaryDirectory(prefix="music_edit_") as tmp:

            wav_path = os.path.join(tmp, "audio.wav")

            json_path = os.path.join(tmp, "transcript.json")



            report(5.0, "正在提取音频…")

            self._bridge.extract_audio(video.file_path, wav_path)



            asr_segments = []

            if self._asr.is_available():

                report(15.0, "正在进行语音识别 (Vosk)…")



                def asr_progress(pct, msg):

                    report(15.0 + pct * 0.45, msg)



                asr_segments = self._asr.transcribe(wav_path, on_progress=asr_progress)

            else:

                report(

                    15.0,

                    "未检测到 Vosk 模型，改用人声能量检测（可运行 scripts\\download_vosk_model.bat）…",

                )



            if asr_segments:

                self._asr.save_transcript_json(asr_segments, json_path)

                report(65.0, f"识别 {len(asr_segments)} 句，分析「{params.scene}」…")



                llm_path = self._app.llm_model_path or ""

                if llm_path and not os.path.isfile(llm_path):

                    llm_path = ""



                highlights = []

                try:

                    highlights = self._bridge.analyze_speech(

                        json_path, llm_path or "none", params.scene,

                        params.min_duration, params.max_duration, params.sensitivity,

                    )

                except Exception:

                    highlights = []



                if highlights:

                    report(95.0, "整理 LLM/规则结果…")

                    return [

                        HighlightSegment(

                            start_sec=h.start_sec,

                            end_sec=h.end_sec,

                            score=h.score,

                            selected=True,

                        )

                        for h in highlights

                    ]



                report(75.0, "引擎分析无结果，改用演讲金句词规则…")

                scored = score_transcript(

                    asr_segments,

                    params.scene,

                    params.min_duration,

                    params.max_duration,

                    params.sensitivity,

                )

                if not scored:

                    raise RuntimeError("未识别出高光片段，可尝试调高敏感度或改用手动切片")

                report(95.0, f"金句规则选出 {len(scored)} 段…")

                return [

                    HighlightSegment(

                        start_sec=c.start_sec,

                        end_sec=c.end_sec,

                        score=c.score,

                        selected=True,

                    )

                    for c in scored

                ]



            # 无 ASR：人声区间兜底

            report(40.0, "检测有声段落（演讲候选）…")

            ranges = self._bridge.detect_speech_segments(

                video.file_path,

                duration_hint=float(video.duration_sec or 0.0),

                min_silence=max(0.35, 0.55 - params.sensitivity * 0.2),

            )

            if not ranges:

                raise RuntimeError(

                    "未检测到有效人声。请确认视频有旁白/演讲，"
                    "或运行 scripts\\download_vosk_model.bat 后重试完整识别。"

                )



            report(70.0, f"找到 {len(ranges)} 段有声区间，按「{params.scene}」切段…")

            scored = clips_from_speech_ranges(

                ranges,

                min_duration=params.min_duration,

                max_duration=params.max_duration,

                sensitivity=params.sensitivity,

                scene=params.scene,

            )

            if not scored:

                raise RuntimeError("未能生成符合时长的演讲片段，请放宽最短/最长限制")



            report(95.0, f"生成 {len(scored)} 段候选（无 Vosk 文本，建议下载模型获金句识别）…")

            return [

                HighlightSegment(

                    start_sec=c.start_sec,

                    end_sec=c.end_sec,

                    score=c.score,

                    selected=True,

                )

                for c in scored

            ]



    def _analyze_game_fallback(

        self, video: VideoModel, params: SliceParams, report

    ) -> List[HighlightSegment]:

        """游戏高光：PySceneDetect 视觉切点；失败则回退时间轴规则。"""

        from core.scene_detect import (
            detect_scene_ranges,
            ranges_to_clipped_segments,
            scenedetect_available,
        )

        report(5.0, "游戏模式：视觉场景切点（PySceneDetect）…")

        if scenedetect_available():
            cfg = load_app_config()
            method = (cfg.get("scenedetect_method") or "adaptive").strip().lower()
            try:
                frame_skip = int(cfg.get("scenedetect_frame_skip") or "0")
            except ValueError:
                frame_skip = 0

            def sd_report(p: float, msg: str):
                # 映射到 5–75
                report(5.0 + max(0.0, min(100.0, p)) * 0.70, msg)

            try:
                ranges = detect_scene_ranges(
                    video.file_path,
                    sensitivity=params.sensitivity,
                    min_scene_sec=max(0.5, params.min_duration * 0.35),
                    method=method,
                    frame_skip=max(0, frame_skip),
                    on_progress=sd_report,
                )
                clipped = ranges_to_clipped_segments(
                    ranges,
                    min_duration=params.min_duration,
                    max_duration=params.max_duration,
                    sensitivity=params.sensitivity,
                )
                if clipped:
                    report(78.0, f"场景切点 {len(clipped)} 段，语义打分…")

                    def sem_report(p: float, msg: str):
                        report(78.0 + max(0.0, min(100.0, p)) * 0.12, msg)

                    try:
                        from core.game_semantic import enrich_game_segments
                        clipped = enrich_game_segments(
                            video.file_path, clipped, on_progress=sem_report,
                        )
                    except Exception as e:
                        import logging
                        logging.getLogger("SceneDetect").warning(
                            "语义打分跳过: %s", e,
                        )
                    report(92.0, f"游戏高光完成：{len(clipped)} 段（含语义分）")
                    import logging
                    logging.getLogger("SceneDetect").info(
                        "游戏高光采用 PySceneDetect+语义 segments=%d", len(clipped),
                    )
                    return [
                        HighlightSegment(
                            start_sec=s, end_sec=e, score=sc, selected=True,
                        )
                        for s, e, sc in clipped
                    ]
                report(70.0, "未检出有效场景，回退时间规则…")
                import logging
                logging.getLogger("SceneDetect").warning("场景为空，回退时间规则")
            except Exception as e:
                report(50.0, f"场景检测失败（{e}），回退时间规则…")
                import logging
                logging.getLogger("SceneDetect").exception("场景检测失败，回退时间规则")
        else:
            report(
                20.0,
                "未安装 scenedetect，回退时间规则（可运行 scripts\\install_scenedetect.bat）…",
            )
            import logging
            logging.getLogger("SceneDetect").warning("scenedetect 不可用，回退时间规则")

        try:
            with tempfile.TemporaryDirectory(prefix="music_edit_") as tmp:
                wav_path = os.path.join(tmp, "audio.wav")
                self._bridge.extract_audio(video.file_path, wav_path)
                report(55.0, "已提取音频（规则兜底）")
        except Exception:
            pass

        report(80.0, "生成规则候选片段…")
        return self._simulate_highlights(video.duration_sec, params)



    def _analyze_loudness_climaxes(
        self, video: VideoModel, params: SliceParams, report
    ) -> List[HighlightSegment]:
        """响度高潮：FFmpeg ebur128 瞬时响度峰值 → 片段。"""
        from core.audio_viz import analyze_ebur128, find_loudness_climaxes

        report(5.0, "响度分析（ebur128）…")

        def ebur_report(p: float, msg: str):
            report(5.0 + max(0.0, min(100.0, p)) * 0.75, msg)

        samples, integrated, lra, _peak = analyze_ebur128(
            video.file_path, on_progress=ebur_report
        )
        report(82.0, f"I={integrated:.1f} LUFS，LRA={lra:.1f}，找高潮…")
        clipped = find_loudness_climaxes(
            samples,
            duration_sec=float(video.duration_sec or 0.0),
            min_duration=params.min_duration,
            max_duration=params.max_duration,
            sensitivity=params.sensitivity,
            max_segments=24,
        )
        if not clipped:
            report(90.0, "未检出响度高潮，回退时间规则…")
            return self._simulate_highlights(video.duration_sec, params)
        report(95.0, f"响度高潮 {len(clipped)} 段")
        return [
            HighlightSegment(start_sec=s, end_sec=e, score=sc, selected=True)
            for s, e, sc in clipped
        ]



    def _simulate_highlights(self, duration: float, params: SliceParams) -> List[HighlightSegment]:

        segments = []

        step = params.max_duration * (1.1 - params.sensitivity)

        t = 0.0

        idx = 0

        while t < duration:

            end = min(t + params.max_duration, duration)

            if end - t >= params.min_duration:

                segments.append(HighlightSegment(

                    start_sec=t, end_sec=end,

                    score=0.5 + params.sensitivity * 0.5,

                    selected=True,

                ))

            t += step

            idx += 1

            if idx > 20:

                break

        return segments



    @Slot(bool)

    def set_gpu_enabled(self, enabled: bool):

        if not self._app.toggle_gpu(enabled):

            self.errorOccurred.emit("未检测到可用 GPU，已保持 CPU 模式")

            return

        if self._bridge:

            self._bridge.set_prefer_hw_decode(self._app.prefer_hw_decode)
            self._bridge.set_prefer_cuda(self._app.use_gpu)

        self.gpuNameChanged.emit(self.gpu_name)



    @Slot(str)

    def set_output_dir(self, path: str):

        if hasattr(self._app, "set_output_dir"):
            self._app.set_output_dir(path)
        else:
            self._app.output_dir = path
        self._state.output_dir = path

    @Slot(str, result=object)
    def redeem_license(self, key: str):
        """返回 (ok: bool, message: str)。"""
        ok, msg = self._app.redeem_license(key)
        if ok:
            self.authTypeChanged.emit(self.auth_type)
        return ok, msg

    @Slot(result=object)
    def clear_license(self):
        ok, msg = self._app.clear_license()
        if ok:
            self.authTypeChanged.emit(self.auth_type)
        return ok, msg

    @Slot(str)
    def set_yt_dlp_cookies_file(self, path: str):
        """设置/清除 yt-dlp cookies 文件，并同步到 MediaBridge。"""
        p = self._app.set_yt_dlp_cookies_file(path or "")
        if self._bridge:
            self._bridge.set_yt_dlp_cookies_file(p)
        if p:
            self._status_message = f"已设置 Cookie 文件: {os.path.basename(p)}"
        else:
            self._status_message = "已清除 Cookie 文件（将尝试浏览器 Cookie）"
        self.statusMessageChanged.emit(self._status_message)

    @Slot(str, bool)
    def export_highlights(
        self,
        output_dir: str,
        concat: bool = True,
        *,
        max_height: int = 0,
        quality: str = "high",
        container: str = "mp4",
        naming_preset: str = "custom",
        use_naming_scheme: bool = False,
        max_total_sec: float = 0.0,
    ):
        """批量导出高光片段，并可选拼接成片。"""
        video = self._state.current_video
        segs = [s for s in self._state.highlight_segments if s.selected and s.end_sec > s.start_sec]
        if not video or not self._bridge:
            self.errorOccurred.emit("请先导入视频")
            return
        if not segs:
            self.errorOccurred.emit("没有可导出的高光片段")
            return

        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.EXPORT,
            file_path=video.file_path,
            state=TaskState.PROCESSING,
            total_frames=len(segs),
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        self.taskStateChanged.emit(task.task_id, TaskState.PROCESSING)
        self.set_output_dir(output_dir)

        def run():
            try:
                def report(p: float, msg: str):
                    task.progress = p
                    self.progressUpdated.emit(task.task_id, p, msg)

                ranges = [(s.start_sec, s.end_sec) for s in segs]
                if max_total_sec and max_total_sec > 0:
                    from core.film_templates import clamp_ranges_to_budget
                    ranges = clamp_ranges_to_budget(ranges, float(max_total_sec))
                clips, merged = self._bridge.export_highlights(
                    video.file_path, ranges, output_dir,
                    concat=concat, on_progress=report,
                    max_height=max_height, quality=quality, container=container,
                    naming_preset=naming_preset,
                    use_naming_scheme=use_naming_scheme,
                )
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task.task_id, TaskState.COMPLETED)
                out = merged or (clips[0] if clips else output_dir)
                self._status_message = f"已导出 {len(clips)} 个片段"
                self.statusMessageChanged.emit(self._status_message)
                self.exportFinished.emit(out)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task.task_id, TaskState.FAILED)
                self.errorOccurred.emit(f"导出失败: {e}")

        import threading
        threading.Thread(target=run, daemon=True).start()

    @Slot(str)
    def compact_speech(self, output_path: str):
        """静音段剪掉，生成紧凑口播版。"""
        video = self._state.current_video
        if not video or not self._bridge:
            self.errorOccurred.emit("请先导入视频")
            return

        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.EXPORT,
            file_path=video.file_path,
            state=TaskState.PROCESSING,
            total_frames=1,
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        self.taskStateChanged.emit(task.task_id, TaskState.PROCESSING)

        def run():
            try:
                def report(p: float, msg: str):
                    task.progress = p
                    self.progressUpdated.emit(task.task_id, p, msg)

                self._bridge.remove_silence(
                    video.file_path,
                    output_path,
                    duration_hint=float(video.duration_sec or 0.0),
                    on_progress=report,
                )
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task.task_id, TaskState.COMPLETED)
                self._status_message = f"紧凑口播已生成: {os.path.basename(output_path)}"
                self.statusMessageChanged.emit(self._status_message)
                self.silenceFinished.emit(output_path)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task.task_id, TaskState.FAILED)
                self.errorOccurred.emit(f"静音裁剪失败: {e}")

        import threading
        threading.Thread(target=run, daemon=True).start()

    def export_vertical_short(
        self,
        output_path: str,
        *,
        crop_bias: str = "center",
        track_mode: str = "fixed",
        use_highlights: bool = True,
        width: int = 1080,
        height: int = 1920,
        quality: str = "high",
    ) -> None:
        """
        竖屏短视频：可选先拼高光成片 → 9:16 裁切（不再烧录外挂字幕）。
        """
        video = self._state.current_video
        if not video or not self._bridge:
            self.errorOccurred.emit("请先导入视频")
            return
        if not output_path:
            self.errorOccurred.emit("请指定输出路径")
            return

        segs = [
            s for s in self._state.highlight_segments
            if s.selected and s.end_sec > s.start_sec
        ]
        use_hl = bool(use_highlights and segs)
        ranges = [(s.start_sec, s.end_sec) for s in segs] if use_hl else []
        src_path = video.file_path
        bias = crop_bias
        track_mode = (track_mode or "fixed").strip().lower() or "fixed"
        out_path = os.path.abspath(output_path)
        w, h = int(width), int(height)
        quality = (quality or "high").strip().lower() or "high"

        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.EXPORT,
            file_path=src_path,
            state=TaskState.PROCESSING,
            total_frames=1,
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        self.taskStateChanged.emit(task.task_id, TaskState.PROCESSING)
        self._status_message = "竖屏短视频导出中…"
        self.statusMessageChanged.emit(self._status_message)

        def run():
            tmp_dir = ""
            try:
                from core.progress_eta import EtaTracker, with_eta
                eta = EtaTracker()
                def report(p: float, msg: str):
                    task.progress = p
                    msg2 = with_eta(msg, p, eta)
                    self.progressUpdated.emit(task.task_id, p, msg2)
                    self.verticalExportProgress.emit(task.task_id, p, msg2)

                work_input = src_path
                if use_hl:
                    report(5.0, "正在导出高光成片…")
                    tmp_dir = tempfile.mkdtemp(prefix="me_vertical_")
                    _clips, merged = self._bridge.export_highlights(
                        src_path, ranges, tmp_dir, concat=True,
                        on_progress=lambda p, m: report(5.0 + p * 0.35, m),
                    )
                    if not merged or not os.path.isfile(merged):
                        raise RuntimeError("高光成片未生成")
                    work_input = merged

                report(50.0, "正在竖屏裁切…")
                self._bridge.export_vertical_short(
                    work_input,
                    out_path,
                    width=w,
                    height=h,
                    crop_bias=bias,
                    track_mode=track_mode,
                    subtitle_path=None,
                    quality=quality,
                    on_progress=lambda p, m: report(50.0 + p * 0.5, m),
                )
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task.task_id, TaskState.COMPLETED)
                self._status_message = f"竖屏短视频已生成: {os.path.basename(out_path)}"
                self.statusMessageChanged.emit(self._status_message)
                self.verticalExportFinished.emit(out_path)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task.task_id, TaskState.FAILED)
                self.errorOccurred.emit(f"竖屏导出失败: {e}")
            finally:
                if tmp_dir:
                    try:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    except Exception:
                        pass

        import shutil
        import threading
        threading.Thread(target=run, daemon=True).start()

    @Slot(str, bool)
    def probe_download_url(self, url: str, list_entries: bool = False):
        if not self._bridge:
            self.errorOccurred.emit("媒体引擎未加载")
            return

        def run():
            try:
                info = self._bridge.probe_url(url, list_entries=list_entries)
                self.downloadProbeReady.emit(info)
            except Exception as e:
                import logging
                logging.getLogger("MusicEditing").exception("探测失败 url=%s", url)
                self.errorOccurred.emit(f"探测失败: {e}")

        import threading
        threading.Thread(target=run, daemon=True).start()

    def preview_list_item(self, item) -> None:
        """列表项播放：拉到临时文件后 emit downloadFinished（首页打开）。"""
        if not self._bridge:
            self.errorOccurred.emit("媒体引擎未加载")
            return

        def run():
            try:
                def report(p: float, msg: str):
                    self.downloadProgress.emit(0, p, msg)

                path = self._bridge.fetch_for_preview(
                    getattr(item, "kind", "format"),
                    page_url=getattr(item, "page_url", "") or "",
                    media_url=getattr(item, "url", "") or "",
                    format_id=getattr(item, "format_id", "") or "",
                    ext=getattr(item, "ext", "") or "mp3",
                    referer=getattr(item, "page_url", "") or "",
                    has_video=bool(getattr(item, "has_video", False)),
                    has_audio=bool(getattr(item, "has_audio", False)),
                    on_progress=report,
                )
                self._status_message = f"预览就绪: {os.path.basename(path)}"
                self.statusMessageChanged.emit(self._status_message)
                # 复用 downloadFinished → 首页播放；不弹「下载完成」由 UI 区分
                self.downloadFinished.emit(path)
            except Exception as e:
                self.errorOccurred.emit(f"播放失败: {e}")

        import threading
        threading.Thread(target=run, daemon=True).start()

    @Slot(str, str, bool, str)
    def start_url_download(
        self,
        url: str,
        output_dir: str,
        audio_only: bool = False,
        format_id: str = "",
    ):
        if not self._bridge:
            self.errorOccurred.emit("媒体引擎未加载")
            return
        if not getattr(self._bridge, "yt_dlp_available", False):
            self.errorOccurred.emit(
                "未找到 yt-dlp.exe，请运行 scripts\\download_yt_dlp.bat"
            )
            return

        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.DOWNLOAD,
            file_path=url,
            state=TaskState.PROCESSING,
            total_frames=1,
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        self.taskStateChanged.emit(task.task_id, TaskState.PROCESSING)

        def run():
            try:
                def report(p: float, msg: str):
                    task.progress = p
                    self.downloadProgress.emit(task.task_id, p, msg)

                path = self._bridge.download_url(
                    url,
                    output_dir,
                    audio_only=audio_only,
                    format_id=format_id or "",
                    on_progress=report,
                )
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task.task_id, TaskState.COMPLETED)
                self._status_message = f"下载完成: {os.path.basename(path)}"
                self.statusMessageChanged.emit(self._status_message)
                self.downloadFinished.emit(path)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task.task_id, TaskState.FAILED)
                import logging
                logging.getLogger("MusicEditing").exception("下载失败 url=%s", url)
                self.errorOccurred.emit(f"下载失败: {e}")

        import threading
        threading.Thread(target=run, daemon=True).start()


    @Slot(str, int, float, float, str)
    def start_interpolate_video(
        self,
        output_path: str,
        factor: int = 2,
        start_sec: float = 0.0,
        end_sec: float = 0.0,
        quality: str = "fast",
        backend: str = "ffmpeg",
    ):
        """视频补帧（后台线程）：FFmpeg minterpolate。quality=fast|quality。"""
        video = self._state.current_video
        if not video or not self._bridge:
            self.errorOccurred.emit("请先导入视频")
            return

        factor = 2 if int(factor) <= 2 else 4
        q = (quality or "fast").strip().lower()
        if q not in ("fast", "quality"):
            q = "fast"
        input_path = video.file_path
        fps = float(video.fps or 25.0)

        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.INTERPOLATE,
            file_path=input_path,
            state=TaskState.PROCESSING,
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        task_id = task.task_id
        bridge = self._bridge
        mode = "精细" if q == "quality" else "快速"

        def run():
            try:
                def report(p: float, msg: str):
                    task.progress = p
                    from core.progress_eta import EtaTracker, with_eta
                    if not hasattr(run, '_eta'):
                        run._eta = EtaTracker()
                    self.interpolateProgress.emit(task_id, p, with_eta(msg, p, run._eta))

                report(1.0, f"FFmpeg {mode}补帧 {factor}x…")
                be_interp = (backend or "ffmpeg").strip().lower() or "ffmpeg"
                out = bridge.interpolate_video(
                    input_path,
                    output_path,
                    fps=fps,
                    factor=factor,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    quality=q,
                    backend=be_interp,
                    on_progress=report,
                )
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task_id, TaskState.COMPLETED)
                self.interpolateFinished.emit(task_id, out or output_path)
                self._status_message = f"补帧完成: {os.path.basename(out or output_path)}"
                self.statusMessageChanged.emit(self._status_message)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task_id, TaskState.FAILED)
                self.errorOccurred.emit(str(e))

        import threading
        threading.Thread(target=run, daemon=True).start()

    def start_color_grade(
        self,
        input_path: str,
        output_path: str,
        preset: str,
        *,
        start_sec: float = 0.0,
        end_sec: float = 0.0,
    ):
        """一键调色（warm/cool/vintage）→ lut3d / OpenCV 矩阵。"""
        if not input_path or not os.path.isfile(input_path):
            self.errorOccurred.emit("调色：输入文件无效")
            return
        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.COLOR_GRADE,
            file_path=input_path,
            state=TaskState.PROCESSING,
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        task_id = task.task_id
        bridge = self._bridge

        def run():
            try:
                def report(p: float, msg: str):
                    task.progress = p
                    self.colorGradeProgress.emit(task_id, p, msg)

                out = bridge.apply_color_grade(
                    input_path,
                    output_path,
                    preset,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    on_progress=report,
                )
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task_id, TaskState.COMPLETED)
                self.colorGradeFinished.emit(task_id, out or output_path)
                self._status_message = f"调色完成: {os.path.basename(out or output_path)}"
                self.statusMessageChanged.emit(self._status_message)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task_id, TaskState.FAILED)
                self.errorOccurred.emit(str(e))

        import threading
        threading.Thread(target=run, daemon=True).start()

    def start_cover_factory(
        self,
        video_path: str,
        output_png: str,
        title: str,
        *,
        subtitle: str = "",
        duration_sec: float = 0.0,
        count: int = 12,
        width: int = 1080,
        height: int = 1920,
        start_sec: float = 0.0,
        end_sec: float = 0.0,
    ):
        """封面工厂：最清晰帧 + 大字标题 PNG。"""
        if not self._bridge:
            self.errorOccurred.emit("媒体引擎未加载")
            return
        if not video_path or not os.path.isfile(video_path):
            self.errorOccurred.emit("封面：输入视频无效")
            return
        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.COVER,
            file_path=video_path,
            state=TaskState.PROCESSING,
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        task_id = task.task_id
        bridge = self._bridge

        def run():
            try:
                def report(p: float, msg: str):
                    task.progress = p
                    self.coverProgress.emit(task_id, p, msg)

                result = bridge.make_short_cover(
                    video_path,
                    output_png,
                    title,
                    duration_sec=duration_sec,
                    subtitle=subtitle,
                    count=count,
                    start_sec=start_sec,
                    end_sec=end_sec,
                    width=width,
                    height=height,
                    on_progress=report,
                )
                out = getattr(result, "cover_path", None) or output_png
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task_id, TaskState.COMPLETED)
                self.coverFinished.emit(task_id, out, result)
                self._status_message = f"封面完成: {os.path.basename(out)}"
                self.statusMessageChanged.emit(self._status_message)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task_id, TaskState.FAILED)
                self.errorOccurred.emit(str(e))

        import threading
        threading.Thread(target=run, daemon=True).start()

    def start_audio_fx(
        self,
        input_path: str,
        output_path: str,
        params,
    ):
        """音频趣味效果（变调/变速/倒放/8D/混响）。"""
        if not self._bridge:
            self.errorOccurred.emit("媒体引擎未加载")
            return
        if not input_path or not os.path.isfile(input_path):
            self.errorOccurred.emit("音频效果：输入文件无效")
            return
        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.AUDIO_FX,
            file_path=input_path,
            state=TaskState.PROCESSING,
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        task_id = task.task_id
        bridge = self._bridge

        def run():
            try:
                def report(p: float, msg: str):
                    task.progress = p
                    self.audioFxProgress.emit(task_id, p, msg)

                out = bridge.apply_audio_fx(
                    input_path, output_path, params, on_progress=report,
                )
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task_id, TaskState.COMPLETED)
                self.audioFxFinished.emit(task_id, out or output_path)
                self._status_message = f"音频效果完成: {os.path.basename(out or output_path)}"
                self.statusMessageChanged.emit(self._status_message)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task_id, TaskState.FAILED)
                self.errorOccurred.emit(str(e))

        import threading
        threading.Thread(target=run, daemon=True).start()

    def start_bgm_mix(
        self,
        video_path: str,
        bgm_path: str,
        output_path: str,
        *,
        mode: str = "overlay",
        bgm_volume: float = 0.35,
        voice_volume: float = 1.0,
        loop_bgm: bool = True,
    ):
        """成片 + BGM 混音（FFmpeg）。"""
        if not self._bridge:
            self.errorOccurred.emit("媒体引擎未加载")
            return
        if not video_path or not os.path.isfile(video_path):
            self.errorOccurred.emit("混音：视频无效")
            return
        if not bgm_path or not os.path.isfile(bgm_path):
            self.errorOccurred.emit("混音：BGM 无效")
            return
        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.BGM_MIX,
            file_path=video_path,
            state=TaskState.PROCESSING,
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        task_id = task.task_id
        bridge = self._bridge

        def run():
            try:
                def report(p: float, msg: str):
                    task.progress = p
                    self.bgmMixProgress.emit(task_id, p, msg)

                out = bridge.mix_bgm(
                    video_path,
                    bgm_path,
                    output_path,
                    mode=mode,
                    bgm_volume=bgm_volume,
                    voice_volume=voice_volume,
                    loop_bgm=loop_bgm,
                    on_progress=report,
                )
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task_id, TaskState.COMPLETED)
                self.bgmMixFinished.emit(task_id, out or output_path)
                self._status_message = f"BGM 混音完成: {os.path.basename(out or output_path)}"
                self.statusMessageChanged.emit(self._status_message)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task_id, TaskState.FAILED)
                self.errorOccurred.emit(str(e))

        import threading
        threading.Thread(target=run, daemon=True).start()

    def start_sfx_overlay(self, video_path: str, sfx_path: str, output_path: str, params):
        """梗音效叠加到视频指定时刻（FFmpeg adelay + atempo）。"""
        if not self._bridge:
            self.errorOccurred.emit("媒体引擎未加载")
            return
        if not video_path or not os.path.isfile(video_path):
            self.errorOccurred.emit("音效：视频无效")
            return
        if not sfx_path or not os.path.isfile(sfx_path):
            self.errorOccurred.emit("音效：音效文件无效")
            return
        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.SFX_OVERLAY,
            file_path=video_path,
            state=TaskState.PROCESSING,
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        task_id = task.task_id
        bridge = self._bridge

        def run():
            try:
                from core.progress_eta import EtaTracker, with_eta
                eta = EtaTracker()

                def report(p: float, msg: str):
                    task.progress = p
                    self.sfxOverlayProgress.emit(task_id, p, with_eta(msg, p, eta))

                out = bridge.overlay_sfx(
                    video_path, sfx_path, output_path, params, on_progress=report,
                )
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task_id, TaskState.COMPLETED)
                self.sfxOverlayFinished.emit(task_id, out or output_path)
                self._status_message = f"梗音叠加完成: {os.path.basename(out or output_path)}"
                self.statusMessageChanged.emit(self._status_message)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task_id, TaskState.FAILED)
                self.errorOccurred.emit(str(e))

        import threading
        threading.Thread(target=run, daemon=True).start()

    def start_demucs_separate(self, input_path: str, output_dir: str):
        """可选 Demucs 人声分离。"""
        if not self._bridge:
            self.errorOccurred.emit("媒体引擎未加载")
            return
        if not input_path or not os.path.isfile(input_path):
            self.errorOccurred.emit("分轨：输入无效")
            return
        task = TaskModel(
            task_id=self._next_task_id,
            task_type=TaskType.DEMUCS,
            file_path=input_path,
            state=TaskState.PROCESSING,
        )
        self._next_task_id += 1
        self._state.tasks.append(task)
        task_id = task.task_id
        bridge = self._bridge

        def run():
            try:
                def report(p: float, msg: str):
                    task.progress = p
                    self.demucsProgress.emit(task_id, p, msg)

                result = bridge.separate_demucs(
                    input_path, output_dir, on_progress=report,
                )
                out = getattr(result, "output_dir", None) or output_dir
                task.state = TaskState.COMPLETED
                task.progress = 100.0
                self.taskStateChanged.emit(task_id, TaskState.COMPLETED)
                self.demucsFinished.emit(task_id, out)
                self._status_message = f"人声分离完成: {out}"
                self.statusMessageChanged.emit(self._status_message)
            except Exception as e:
                task.state = TaskState.FAILED
                self.taskStateChanged.emit(task_id, TaskState.FAILED)
                self.errorOccurred.emit(str(e))

        import threading
        threading.Thread(target=run, daemon=True).start()


    @Slot(str, float, float, float)

    def update_slice_params(self, scene: str, min_dur: float, max_dur: float, sensitivity: float):

        self._state.slice_params = SliceParams(

            scene=scene, min_duration=min_dur,

            max_duration=max_dur, sensitivity=sensitivity,

        )



    @Slot(float, float)
    def add_manual_highlight(self, start_sec: float, end_sec: float) -> bool:
        """手动添加高光片段（不依赖 Vosk）。成功返回 True；校验失败只改状态栏。"""
        start = max(0.0, float(start_sec))
        end = max(0.0, float(end_sec))
        if end <= start + 0.05:
            self._status_message = "手动切片：结束时间须大于开始时间"
            self.statusMessageChanged.emit(self._status_message)
            return False
        video = self._state.current_video
        if video and video.duration_sec > 0:
            end = min(end, float(video.duration_sec))
            if end <= start + 0.05:
                self._status_message = "手动切片：区间超出视频时长"
                self.statusMessageChanged.emit(self._status_message)
                return False
        seg = HighlightSegment(
            start_sec=start, end_sec=end, score=1.0, selected=True,
        )
        self._state.highlight_segments.append(seg)
        self.highlightsReady.emit(list(self._state.highlight_segments))
        self._status_message = (
            f"已添加手动片段 #{len(self._state.highlight_segments)} "
            f"({start:.1f}s – {end:.1f}s)"
        )
        self.statusMessageChanged.emit(self._status_message)
        return True

    @Slot(int)
    def remove_highlight_at(self, index: int) -> None:
        segs = self._state.highlight_segments
        if index < 0 or index >= len(segs):
            return
        segs.pop(index)
        self.highlightsReady.emit(list(segs))
        self._status_message = f"已删除片段，剩余 {len(segs)} 段"
        self.statusMessageChanged.emit(self._status_message)

    @Slot()
    def clear_highlights(self) -> None:
        self._state.highlight_segments.clear()
        self.highlightsReady.emit([])
        self._status_message = "已清空片段列表"
        self.statusMessageChanged.emit(self._status_message)

    # ── 批量全流程队列 ─────────────────────────────────────────

    @property
    def pipeline_running(self) -> bool:
        return self._pipeline_running

    @property
    def pipeline_paused(self) -> bool:
        return self._pipeline_running and not self._pipeline_pause.is_set()

    @property
    def pipeline_jobs(self) -> list[PipelineJob]:
        return list(self._pipeline_jobs)

    def start_pipeline_queue(self, paths: list[str], settings: PipelineSettings) -> None:
        ok, tip = self.require_feature("pipeline_queue")
        if not ok:
            self.errorOccurred.emit(tip)
            return
        if self._pipeline_running:
            self.errorOccurred.emit("全流程队列正在运行")
            return
        if not self._bridge:
            self.errorOccurred.emit("全流程队列：媒体引擎未加载")
            return
        clean = [os.path.abspath(p) for p in paths if p and os.path.isfile(p)]
        if not clean:
            self.errorOccurred.emit("全流程队列：没有有效视频文件")
            return
        if not (settings.do_slice or settings.do_enhance or settings.do_watermark):
            self.errorOccurred.emit("全流程队列：请至少启用一个步骤")
            return

        self._pipeline_jobs = [PipelineJob(path=p) for p in clean]
        self._pipeline_cancel.clear()
        self._pipeline_skip.clear()
        self._pipeline_pause.set()
        self._pipeline_running = True
        self._status_message = f"全流程队列启动：{len(clean)} 个任务"
        self.statusMessageChanged.emit(self._status_message)
        self.pipelineStatusChanged.emit(self._status_message)

        bridge = self._bridge
        # 快照模型路径，避免后台线程读配置竞态
        try:
            upscale_model = self._upscale_model_path(
                "opencv" if settings.enhance_backend in ("opencv", "cv", "fast", "bicubic")
                else "realesrgan"
            )
        except Exception as e:
            self._pipeline_running = False
            self.errorOccurred.emit(f"全流程队列：{e}")
            return
        try:
            wm_model = self._watermark_model_path(
                "opencv" if settings.watermark_backend in ("opencv", "cv", "fast") else "lama"
            )
        except Exception as e:
            if settings.do_watermark:
                self._pipeline_running = False
                self.errorOccurred.emit(f"全流程队列：{e}")
                return
            wm_model = "-"

        jobs = self._pipeline_jobs
        snap = PipelineSettings(**settings.__dict__)

        def analyze(video, params, report):
            if params.scene in SPEECH_SCENES:
                return self._analyze_speech_pipeline(video, params, report)
            if params.scene in LOUDNESS_SCENES:
                return self._analyze_loudness_climaxes(video, params, report)
            return self._analyze_game_fallback(video, params, report)

        def on_update(index: int, job: PipelineJob):
            self.pipelineItemUpdated.emit(index, job)
            self._status_message = (
                f"全流程 [{index + 1}/{len(jobs)}] {job.state.value} "
                f"{job.phase.value} {job.message}"
            )
            self.statusMessageChanged.emit(self._status_message)

        def run():
            try:
                run_pipeline_queue(
                    bridge=bridge,
                    jobs=jobs,
                    settings=snap,
                    analyze_fn=analyze,
                    upscale_model_path=upscale_model,
                    watermark_model_path=wm_model,
                    cancel_event=self._pipeline_cancel,
                    skip_event=self._pipeline_skip,
                    pause_event=self._pipeline_pause,
                    on_update=on_update,
                )
            except Exception as e:
                self.errorOccurred.emit(f"全流程队列异常: {e}")
            finally:
                self._pipeline_running = False
                self._pipeline_pause.set()
                self.pipelineFinished.emit()
                self._status_message = "全流程队列结束"
                self.statusMessageChanged.emit(self._status_message)
                self.pipelineStatusChanged.emit(self._status_message)

        threading.Thread(target=run, daemon=True).start()

    def pause_pipeline_queue(self) -> None:
        if self._pipeline_running:
            self._pipeline_pause.clear()
            self.pipelineStatusChanged.emit("全流程队列已暂停")

    def resume_pipeline_queue(self) -> None:
        self._pipeline_pause.set()
        if self._pipeline_running:
            self.pipelineStatusChanged.emit("全流程队列继续")

    def skip_pipeline_current(self) -> None:
        if self._pipeline_running:
            self._pipeline_skip.set()
            self.pipelineStatusChanged.emit("将跳过当前任务…")

    def cancel_pipeline_queue(self) -> None:
        if self._pipeline_running:
            self._pipeline_cancel.set()
            self._pipeline_pause.set()  # 解除暂停以便退出
            self.pipelineStatusChanged.emit("正在取消全流程队列…")

    def get_app_state(self) -> AppState:

        return self._state

