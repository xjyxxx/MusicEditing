"""主视图模型 - MVVM 双向绑定核心"""



from __future__ import annotations



import os

import tempfile

from typing import List, Optional



from PySide6.QtCore import QObject, Property, Signal, Slot



from core.app_logic import AppLogic

from core.asr_engine import AsrEngine

from core.media_bridge import MediaBridge

from models.video_model import (

    AppState, HighlightSegment, SliceParams, TaskModel, TaskState, TaskType, VideoModel,

)



SPEECH_SCENES = frozenset({"演讲金句", "日常精彩片段", "自定义识别"})





class MainViewModel(QObject):

    """主窗口 ViewModel，连接 Model 与 View"""



    videoLoaded = Signal(object)

    progressUpdated = Signal(int, float, str)

    taskStateChanged = Signal(int, int)

    highlightsReady = Signal(list)

    watermarkProgress = Signal(int, float, str)

    watermarkFinished = Signal(int, str)

    errorOccurred = Signal(str)

    statusMessageChanged = Signal(str)



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



        try:

            self._bridge = MediaBridge()


            self._bridge.set_prefer_hw_decode(self._app.prefer_hw_decode)

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



    @Property(str, constant=True)

    def version(self) -> str:

        return self._app.version



    @Slot(str)

    def import_video(self, file_path: str):

        if not self._bridge:

            self.errorOccurred.emit("媒体引擎未加载，请先编译 C++ 核心库")

            return



        if not os.path.isfile(file_path):

            self.errorOccurred.emit(f"文件不存在: {file_path}")

            return



        try:

            info = self._bridge.probe_video(file_path)

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

                f"已导入: {os.path.basename(file_path)} "

                f"({video.width}x{video.height}, {video.duration_sec:.1f}s)"

            )

            self.statusMessageChanged.emit(self._status_message)

            self.videoLoaded.emit(video)

        except Exception as e:

            self.errorOccurred.emit(f"导入失败: {e}")



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

                "未找到 LaMa 模型 models/lama.onnx，请运行 scripts/download_lama_model.bat"

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

                def report(p: float, msg: str):

                    task.progress = p

                    self.watermarkProgress.emit(task_id, p, msg)



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



    @Slot()

    def start_slice_analysis(self):

        video = self._state.current_video

        if not video or not self._bridge:

            self.errorOccurred.emit("请先导入视频")

            return



        params = self._state.slice_params

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



        def report(progress: float, msg: str):

            task.progress = progress

            self.progressUpdated.emit(task.task_id, progress, msg)



        try:

            if params.scene in SPEECH_SCENES:

                segments = self._analyze_speech_pipeline(video, params, report)

            else:

                segments = self._analyze_game_fallback(video, params, report)



            self._state.highlight_segments = segments

            task.state = TaskState.COMPLETED

            task.progress = 100.0

            self.taskStateChanged.emit(task.task_id, TaskState.COMPLETED)

            self.progressUpdated.emit(task.task_id, 100.0, "分析完成")

            self.highlightsReady.emit(segments)



            mode = "LLM+ASR" if params.scene in SPEECH_SCENES else "规则"

            self._status_message = f"[{mode}] 识别出 {len(segments)} 个高光片段"

            self.statusMessageChanged.emit(self._status_message)

        except Exception as e:

            task.state = TaskState.FAILED

            self.taskStateChanged.emit(task.task_id, TaskState.FAILED)

            self.errorOccurred.emit(f"分析失败: {e}")



    def _analyze_speech_pipeline(

        self, video: VideoModel, params: SliceParams, report

    ) -> List[HighlightSegment]:

        """演讲/解说类：FFmpeg 抽音频 → Vosk ASR → llama 语义高光"""

        if not self._asr.is_available():

            raise RuntimeError(

                "语音识别未就绪：请 pip install vosk，并下载模型到 models/vosk-model-small-cn-0.22"

            )



        with tempfile.TemporaryDirectory(prefix="music_edit_") as tmp:

            wav_path = os.path.join(tmp, "audio.wav")

            json_path = os.path.join(tmp, "transcript.json")



            report(5.0, "正在提取音频…")

            self._bridge.extract_audio(video.file_path, wav_path)



            report(15.0, "正在进行语音识别 (Vosk)…")



            def asr_progress(pct, msg):

                report(15.0 + pct * 0.45, msg)



            asr_segments = self._asr.transcribe(wav_path, on_progress=asr_progress)

            if not asr_segments:

                raise RuntimeError("语音识别结果为空，请确认视频含清晰人声")



            self._asr.save_transcript_json(asr_segments, json_path)

            report(65.0, f"识别 {len(asr_segments)} 句，LLM 分析高光…")



            llm_path = self._app.llm_model_path or ""
            if llm_path and not os.path.isfile(llm_path):
                llm_path = ""

            highlights = self._bridge.analyze_speech(

                json_path, llm_path, params.scene,

                params.min_duration, params.max_duration, params.sensitivity,

            )



            if not highlights:

                raise RuntimeError("未识别出高光片段，可尝试调高敏感度")



            report(95.0, "整理结果…")

            return [

                HighlightSegment(

                    start_sec=h.start_sec,

                    end_sec=h.end_sec,

                    score=h.score,

                    selected=True,

                )

                for h in highlights

            ]



    def _analyze_game_fallback(

        self, video: VideoModel, params: SliceParams, report

    ) -> List[HighlightSegment]:

        """游戏高光：视觉模型待接入，暂用时间轴规则兜底"""

        report(10.0, "游戏模式：视觉模型开发中，使用音频/时间规则…")



        try:

            with tempfile.TemporaryDirectory(prefix="music_edit_") as tmp:

                wav_path = os.path.join(tmp, "audio.wav")

                self._bridge.extract_audio(video.file_path, wav_path)

                report(40.0, "已提取音频（后续接入动作检测）")

        except Exception:

            pass



        report(60.0, "生成候选片段…")

        return self._simulate_highlights(video.duration_sec, params)



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

        self.gpuNameChanged.emit(self.gpu_name)



    @Slot(str)

    def set_output_dir(self, path: str):

        self._state.output_dir = path

        self._app.output_dir = path



    @Slot(str, float, float, float)

    def update_slice_params(self, scene: str, min_dur: float, max_dur: float, sensitivity: float):

        self._state.slice_params = SliceParams(

            scene=scene, min_duration=min_dur,

            max_duration=max_dur, sensitivity=sensitivity,

        )



    def get_app_state(self) -> AppState:

        return self._state

