"""本地视频播放器 — Python GUI + C++ FFmpeg 解码（统一播放器）"""



from __future__ import annotations



import math
import os
import time



from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QSurfaceFormat

from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QSlider, QVBoxLayout, QWidget,
)



from core.player_backend import PlayerBackend
from core.qt_audio_output import QtAudioOutput
from core.app_logic import AppLogic, load_app_config
from core.app_logger import setup_logging
from core.subtitle_track import SubtitleTrack, find_sidecar_subtitles
from ui.gl_video_widget import GlVideoWidget, _default_surface_format
from ui.waveform_widget import WaveformWidget

log = setup_logging("VideoPlayer", __import__("os").environ.get("MUSIC_LOG_LEVEL", "INFO"))

_AUDIO_EXTS = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma", ".opus", ".aiff", ".ape",
}
_VIDEO_EXTS = {
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".m4v", ".ts", ".mpeg", ".mpg",
}


def _is_audio_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _AUDIO_EXTS


def _format_time(sec: float) -> str:

    if sec < 0:

        sec = 0

    s = int(sec)

    m, s = divmod(s, 60)

    h, m = divmod(m, 60)

    if h > 0:

        return f"{h}:{m:02d}:{s:02d}"

    return f"{m}:{s:02d}"





class VideoPlayerWidget(QWidget):

    """

    统一播放器组件

    - 视频：media_player.exe (FFmpeg) → OpenGL 纹理显示（GlVideoWidget）

    - 音频：Qt QMediaPlayer（仅音频轨，Windows 下更稳定）

    """



    fileOpened = Signal(str)



    def __init__(self, parent=None):

        super().__init__(parent)

        self._backend: PlayerBackend | None = None

        self._audio = QtAudioOutput()

        self._current_path = ""

        self._duration_sec = 0.0

        self._fps = 25.0

        self._position_sec = 0.0

        self._has_audio = False

        self._seeking = False

        self._playing = False

        self._was_playing_before_seek = False
        self._opening = False
        self._frame_rgb_buf: bytearray | None = None
        self._last_progress_wall = 0.0
        self._frame_interval = 1.0 / 25.0
        self._sync_timer_ms = 33
        self._last_shown_frame_ts = -1.0
        self._opencv_filter = load_app_config().get("opencv_filter", "clahe")
        _cfg = load_app_config()
        _pb = _cfg.get("opencv_filter_playback", "off").strip().lower()
        self._opencv_filter_playback = _pb not in ("0", "false", "off", "no")
        self._opencv_filter_device = _cfg.get("opencv_filter_device", "auto").strip().lower() or "auto"
        self._opencv_filter_active_device = "cpu"
        self._hw_decode_preferred = AppLogic().prefer_hw_decode
        self._hw_decode_active = False
        self._audio_only = False
        self._subtitles = SubtitleTrack()
        self._audio_viz_token = 0



        # OpenGL 显示区：须在创建 QOpenGLWidget 前设置默认 SurfaceFormat
        QSurfaceFormat.setDefaultFormat(_default_surface_format())

        self._title = QLabel("未加载 · 支持视频 / 音乐")
        self._title.setObjectName("MutedText")

        self._display = GlVideoWidget()
        self._display.set_placeholder("请打开本地视频或音乐\n点击画面可暂停 / 继续")

        self._btn_open = QPushButton("打开文件")
        self._btn_play = QPushButton("播放")

        self._btn_pause = QPushButton("暂停")

        self._btn_stop = QPushButton("停止")

        self._btn_sub = QPushButton("字幕…")
        self._btn_sub.setToolTip("加载外挂字幕（SRT / VTT）；打开视频时自动匹配同名字幕")
        self._btn_clear_sub = QPushButton("关字幕")
        self._btn_clear_sub.setEnabled(False)
        self._btn_live_sub = QPushButton("实时字幕")
        self._btn_live_sub.setToolTip(
            "流式 ASR 两遍管线（草稿→稳态）+ 字幕分路接口\n"
            "当前为预留；见 app.conf live_subtitle_* 与 core/live_subtitle/"
        )
        self._live_pipeline = None

        self._waveform = WaveformWidget()
        self._waveform.setToolTip(
            "FFmpeg showwavespic 波形 + ebur128 响度曲线\n点击跳转时间"
        )




        self._progress = QSlider(Qt.Horizontal)

        self._progress.setRange(0, 1000)

        self._time_label = QLabel("00:00 / 00:00")

        self._time_label.setObjectName("MutedText")
        self._time_label.setMinimumWidth(110)



        self._volume = QSlider(Qt.Horizontal)

        self._volume.setRange(0, 100)

        self._volume.setValue(70)

        self._volume.setFixedWidth(90)

        self._volume.setToolTip("音量")

        self._filter_combo = QComboBox()
        self._filter_combo.setToolTip("OpenCV 实时滤镜（播放时也会生效）")
        for label, mode in (
            ("滤镜:关闭", "off"),
            ("明亮", "clahe"),
            ("降噪", "denoise"),
            ("锐化", "sharpen"),
            ("胶片", "film"),
            ("电影暖调", "warm"),
            ("冷调", "cool"),
            ("复古", "vintage"),
            ("霓虹", "neon"),
            ("漫画", "comic"),
            ("像素", "pixel"),
        ):
            self._filter_combo.addItem(label, mode)
        idx = self._filter_combo.findData(self._opencv_filter)
        if idx < 0:
            idx = 0
        self._filter_combo.setCurrentIndex(idx)

        ctrl = QHBoxLayout()

        ctrl.addWidget(self._btn_open)

        ctrl.addWidget(self._btn_play)

        ctrl.addWidget(self._btn_pause)

        ctrl.addWidget(self._btn_stop)

        ctrl.addWidget(self._btn_sub)
        ctrl.addWidget(self._btn_clear_sub)
        ctrl.addWidget(self._btn_live_sub)

        ctrl.addWidget(self._filter_combo)

        ctrl.addStretch()

        ctrl.addWidget(QLabel("音量"))

        ctrl.addWidget(self._volume)



        seek_row = QHBoxLayout()

        seek_row.addWidget(self._progress, 1)

        seek_row.addWidget(self._time_label)



        layout = QVBoxLayout(self)

        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self._title)

        layout.addWidget(self._display, 1)

        layout.addWidget(self._waveform)

        layout.addLayout(seek_row)

        layout.addLayout(ctrl)



        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)



        self._btn_open.clicked.connect(self._on_open)

        self._btn_play.clicked.connect(self.play)

        self._btn_pause.clicked.connect(self.pause)

        self._btn_stop.clicked.connect(self.stop)

        self._btn_sub.clicked.connect(self._on_load_subtitle)
        self._btn_clear_sub.clicked.connect(self._on_clear_subtitle)
        self._btn_live_sub.clicked.connect(self._on_live_subtitle)

        self._waveform.seekRequested.connect(self._on_waveform_seek)

        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)

        self._display.clicked.connect(self._on_display_clicked)

        self._progress.sliderPressed.connect(self._on_seek_pressed)

        self._progress.sliderReleased.connect(self._on_seek_released)

        self._volume.valueChanged.connect(self._on_volume_changed)

        self._audio.set_duration_callback(self._on_audio_duration)



        try:

            self._backend = PlayerBackend()
            self._backend.set_hwaccel(self._hw_decode_preferred)

        except FileNotFoundError as e:

            self._title.setText(str(e))



    @property

    def current_path(self) -> str:

        return self._current_path



    @Slot()

    def _on_open(self):

        path, _ = QFileDialog.getOpenFileName(

            self, "选择视频或音乐",

            self._current_path or "",

            "媒体文件 (*.mp4 *.mov *.avi *.mkv *.flv *.wmv *.webm "
            "*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.wma);;"
            "视频 (*.mp4 *.mov *.avi *.mkv *.flv *.wmv *.webm);;"
            "音乐 (*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.wma);;"
            "所有文件 (*.*)",

        )

        if path:

            self.open_file(path)



    def open_file(self, path: str, auto_play: bool = False):
        if not os.path.isfile(path):
            return
        # 纯音乐不依赖 media_player；视频才需要 backend
        if not _is_audio_file(path) and not self._backend:
            return
        if self._opening:
            return

        self._opening = True
        try:
            self._do_open_file(path, auto_play)
        finally:
            self._opening = False

    def _reset_transport_controls(self, *, playing: bool = False):
        """同步播放/暂停按钮与内部 playing 状态"""
        self._playing = playing
        self._btn_play.setEnabled(not playing)
        self._btn_pause.setEnabled(playing)
        # 已加载媒体且暂停时显示暂停标志；播放中或未加载则隐藏
        show_pause = (not playing) and bool(self._current_path)
        self._display.set_paused_overlay(show_pause)

    @Slot()
    def _on_display_clicked(self):
        """点击画面：暂停 / 继续；未加载时打开文件。"""
        if not self._current_path:
            self._on_open()
            return
        if self._playing:
            self.pause()
        else:
            self.play()

    @Slot(float)
    def _on_audio_duration(self, duration_sec: float):
        if duration_sec <= 0:
            return
        if self._audio_only or self._duration_sec <= 0:
            self._duration_sec = duration_sec
            self._progress.setRange(0, max(int(duration_sec * 1000), 1))
            self._update_time_label()

    def _make_music_cover(self, playing: bool) -> QImage:
        w, h = 960, 540
        img = QImage(w, h, QImage.Format_RGB888)
        img.fill(QColor(14, 16, 32))
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        # 背景渐变块
        p.fillRect(0, 0, w, h, QColor(18, 22, 48))
        p.fillRect(80, 60, w - 160, h - 120, QColor(28, 34, 68))
        name = os.path.basename(self._current_path) if self._current_path else "音乐"
        p.setPen(QColor(200, 210, 255))
        font = QFont()
        font.setPointSize(28)
        font.setBold(True)
        p.setFont(font)
        p.drawText(img.rect().adjusted(40, 0, -40, -80), Qt.AlignCenter, f"♪  {name}")
        tip = "播放中 · 点击暂停" if playing else "已暂停 · 点击继续"
        p.setPen(QColor(140, 160, 200))
        font.setPointSize(16)
        font.setBold(False)
        p.setFont(font)
        p.drawText(img.rect().adjusted(40, 80, -40, 0), Qt.AlignCenter, tip)
        p.end()
        return img

    def _show_music_cover(self, playing: bool | None = None):
        if playing is None:
            playing = self._playing
        self._display.set_qimage(self._make_music_cover(playing))

    def _do_open_audio(self, path: str, auto_play: bool = False):
        self._timer.stop()
        self._audio.stop()
        self._reset_transport_controls(playing=False)
        self._clear_subtitles(silent=True)
        self._audio_only = True
        self._hw_decode_active = False
        self._has_audio = True
        self._current_path = os.path.abspath(path)
        self._duration_sec = 0.0
        self._fps = 25.0
        self._frame_interval = 0.04
        self._sync_timer_ms = 50
        self._timer.setInterval(self._sync_timer_ms)
        self._position_sec = 0.0
        self._last_shown_frame_ts = -1.0

        # 停掉视频解码子进程占用（若有）
        if self._backend:
            try:
                self._backend.pause()
            except Exception:
                pass

        self._audio.open(self._current_path)
        self._audio.set_volume(self._volume.value() / 100.0)
        dur = self._audio.duration_sec()
        if dur > 0:
            self._duration_sec = dur

        self._filter_combo.setEnabled(False)
        self._progress.setRange(0, max(int(self._duration_sec * 1000), 1))
        self._progress.setValue(0)
        self._update_time_label()
        self._title.setText(
            f"{os.path.basename(path)}  ·  音乐  ·  Qt 音频  ·  点击画面暂停/继续"
        )
        self._show_music_cover(playing=False)
        self._display.set_paused_overlay(True)
        log.info("音乐已打开 %s", path)
        self._waveform.set_duration(self._duration_sec)
        self._start_audio_viz(self._current_path)
        self.fileOpened.emit(self._current_path)
        if auto_play:
            self.play()

    def _do_open_file(self, path: str, auto_play: bool = False):
        if _is_audio_file(path):
            self._do_open_audio(path, auto_play)
            return

        self._timer.stop()
        self._audio.stop()
        self._reset_transport_controls(playing=False)
        self._clear_subtitles(silent=True)
        self._audio_only = False
        self._filter_combo.setEnabled(True)

        if self._backend:
            self._backend.set_hwaccel(self._hw_decode_preferred)

        try:
            info = self._backend.open(path)
        except RuntimeError as e:
            log.error("打开视频失败: %s", e)
            self._title.setText(f"打开失败: {e}")
            return

        self._hw_decode_active = info.hw_decode
        self._apply_opencv_filter()

        self._current_path = os.path.abspath(path)
        self._duration_sec = info.duration_sec
        self._fps = max(info.fps, 1.0)
        self._frame_interval = 1.0 / self._fps
        self._sync_timer_ms = max(16, int(1000 / self._fps))
        self._timer.setInterval(self._sync_timer_ms)
        self._position_sec = 0.0
        self._last_shown_frame_ts = -1.0
        self._has_audio = info.has_audio

        if self._has_audio:
            self._audio.open(self._current_path)
            self._audio.set_volume(self._volume.value() / 100.0)

        audio_hint = "有声音" if self._has_audio else "无音频轨"
        decode_hint = info.hw_name.upper() if info.hw_decode else "CPU解码"
        title_parts = [
            os.path.basename(path),
            f"{info.width}x{info.height}",
            decode_hint,
            "OpenGL",
            audio_hint,
            "点击画面暂停/继续",
        ]
        if self._opencv_filter and self._opencv_filter != "off":
            tag = self._opencv_title_tag()
            if tag:
                title_parts.append(tag)
        self._title.setText("  ·  ".join(title_parts))
        log.info(
            "视频已打开 %s %dx%d %s hw=%s",
            os.path.basename(path), info.width, info.height, decode_hint, info.hw_decode,
        )
        self._progress.setRange(0, max(int(self._duration_sec * 1000), 1))
        self._progress.setValue(0)
        self._update_time_label()

        self._pull_and_show_frame(apply_filter=True)
        self._refresh_filter_status()
        # 首帧滤镜后刷新标题中的 opencl/cpu
        if self._opencv_filter and self._opencv_filter != "off":
            tag = self._opencv_title_tag()
            if tag and title_parts:
                # 重建标题末尾滤镜标签
                base = [p for p in title_parts if not str(p).startswith("OpenCV:")]
                base.append(tag)
                self._title.setText("  ·  ".join(base))
        self._display.set_paused_overlay(True)

        # 自动加载同目录同名字幕
        self._try_autoload_sidecar_subtitles(path)

        self._waveform.set_duration(self._duration_sec)
        self._start_audio_viz(self._current_path)

        # 同步到 ViewModel（此时 current_path 已设置，不会触发重复 open）
        self.fileOpened.emit(self._current_path)

        if auto_play:
            self.play()

    def _apply_opencv_filter(self):
        """应用当前滤镜模式与设备（未编译 OpenCV 时静默忽略）"""
        if not self._backend or not self._opencv_filter:
            return
        try:
            if self._opencv_filter_device:
                self._backend.set_filter_device(self._opencv_filter_device)
            self._backend.set_filter(self._opencv_filter)
            self._refresh_filter_status()
        except RuntimeError:
            pass

    def _refresh_filter_status(self):
        if not self._backend:
            return
        try:
            resp = self._backend.filter_status()
            for part in str(resp).split():
                if part.startswith("active="):
                    self._opencv_filter_active_device = part.split("=", 1)[1]
        except RuntimeError:
            pass

    def _opencv_title_tag(self) -> str:
        if not self._opencv_filter or self._opencv_filter == "off":
            return ""
        dev = self._opencv_filter_active_device or "cpu"
        # 硬解 + 未开播放滤镜：只在暂停预览时套滤镜，但仍显示实际设备
        if self._hw_decode_active and not self._opencv_filter_playback:
            return f"OpenCV:{self._opencv_filter}/{dev}·预览"
        return f"OpenCV:{self._opencv_filter}/{dev}"

    def set_filter_mode(self, mode: str) -> bool:
        """外部设置滤镜（天气氛围推荐等）；下拉已是目标值时也会刷新一帧。"""
        if not isinstance(mode, str) or not mode:
            return False
        idx = self._filter_combo.findData(mode)
        if idx < 0:
            return False
        if self._filter_combo.currentIndex() == idx:
            self._on_filter_changed(idx)
        else:
            self._filter_combo.setCurrentIndex(idx)
        return True

    @Slot(int)
    def _on_filter_changed(self, _index: int):
        mode = self._filter_combo.currentData()
        if not isinstance(mode, str):
            mode = "off"
        self._opencv_filter = mode
        # 用户主动选滤镜：播放中也开滤镜（趣味滤镜才看得见）
        self._opencv_filter_playback = mode not in ("off", "", None)
        self._apply_opencv_filter()
        if self._backend:
            on = bool(self._opencv_filter_playback and mode != "off")
            self._backend.set_playback_filter(on)
            # 暂停时 seek 回当前位置再拉一帧，立刻看到效果
            if not self._playing:
                pos = max(0.0, self._position_sec)
                try:
                    self._backend.seek(pos)
                except RuntimeError:
                    pass
                self._last_shown_frame_ts = pos - self._frame_interval
                self._pull_and_show_frame(apply_filter=True)
                self._refresh_filter_status()
        self._refresh_title_filter_hint()
        log.info(
            "滤镜切换 mode=%s playback=%s device=%s active=%s",
            mode, self._opencv_filter_playback,
            self._opencv_filter_device, self._opencv_filter_active_device,
        )

    def _refresh_title_filter_hint(self):
        text = self._title.text()
        parts = [p.strip() for p in text.split("·")]
        parts = [p for p in parts if not p.startswith("OpenCV:")]
        tag = self._opencv_title_tag()
        if tag:
            parts.append(tag)
        self._title.setText("  ·  ".join(parts))



    def _playback_scale_dims(self, src_w: int, src_h: int) -> tuple[int, int]:
        """播放时缩小 RGB，降低读盘/显示开销"""
        max_w, max_h = 640, 360
        if src_w <= max_w and src_h <= max_h:
            return 0, 0
        scale = min(max_w / src_w, max_h / src_h)
        w = int(src_w * scale)
        w = max(w & ~3, 4)
        h = int(src_h * scale) & ~1
        return w, max(h, 2)

    def _frame_index(self, sec: float) -> int:
        if sec < 0:
            return -1
        return int(math.floor(sec / self._frame_interval + 1e-9))

    def play(self):

        if not self._current_path:
            return

        if self._audio_only:
            if self._duration_sec <= 0:
                dur = self._audio.duration_sec()
                if dur > 0:
                    self._duration_sec = dur
                    self._progress.setRange(0, max(int(dur * 1000), 1))
            self._audio.play(self._position_sec)
            self._playing = True
            self._reset_transport_controls(playing=True)
            self._show_music_cover(playing=True)
            self._schedule_tick()
            log.info("音乐播放开始 pos=%.2f", self._position_sec)
            return

        if not self._backend:
            return

        # 硬解 + 重滤镜每帧开销大：默认 conf 可关；用户从下拉选滤镜后会打开
        use_filter = self._opencv_filter_playback and self._opencv_filter not in ("off", "")
        pw = ph = 0
        if self._backend:
            self._backend.set_playback_filter(use_filter)
            pw, ph = self._playback_scale_dims(
                self._backend.info.width, self._backend.info.height
            )
            self._backend.set_playback_scale(pw, ph)

        self._backend.resume()

        if self._has_audio:
            self._audio.play(self._position_sec)

        self._last_shown_frame_ts = self._position_sec - self._frame_interval

        self._playing = True
        self._reset_transport_controls(playing=True)
        self._schedule_tick()

        log.info(
            "播放开始 filter_on=%s hw=%s timer=%dms scale=%dx%d",
            use_filter, self._hw_decode_active, self._sync_timer_ms,
            pw, ph,
        )



    def pause(self):

        self._timer.stop()

        if self._audio_only:
            self._audio.pause()
            self._reset_transport_controls(playing=False)
            self._show_music_cover(playing=False)
            return

        if self._backend:
            self._backend.set_playback_scale(0, 0)
            self._backend.pause()
            # 暂停时恢复预览滤镜（单帧）
            self._backend.set_playback_filter(
                bool(self._opencv_filter and self._opencv_filter != "off")
            )

        if self._has_audio:

            self._audio.pause()

        self._reset_transport_controls(playing=False)



    def stop(self):

        self.pause()

        self._position_sec = 0.0
        self._last_shown_frame_ts = -1.0

        self._progress.setValue(0)
        self._update_time_label()

        if self._has_audio:

            self._audio.stop()

        if self._audio_only:
            self._show_music_cover(playing=False)
            return

        if self._backend and self._current_path:

            try:

                self._backend.seek(0)

                self._pull_and_show_frame()

            except RuntimeError:

                pass



    @Slot()

    def _on_seek_pressed(self):

        self._was_playing_before_seek = self._playing

        self._seeking = True

        if self._playing:

            self._timer.stop()

            if self._has_audio:

                self._audio.pause()



    @Slot()

    def _on_seek_released(self):

        self._seeking = False

        if not self._current_path or self._duration_sec <= 0:

            return

        ratio = self._progress.value() / max(self._progress.maximum(), 1)

        self._seek_to(ratio * self._duration_sec, resume=self._was_playing_before_seek)

    def _seek_to(self, position_sec: float, *, resume: bool | None = None):
        """统一 seek（进度条 / 波形点击）。"""
        if not self._current_path or self._duration_sec <= 0:
            return
        self._position_sec = max(0.0, min(float(position_sec), self._duration_sec))
        self._progress.setValue(int(self._position_sec * 1000))
        if self._audio_only:
            self._audio.seek(self._position_sec)
            self._update_time_label()
            if resume:
                self.play()
            return
        if not self._backend:
            return
        try:
            self._backend.seek(self._position_sec)
            if self._has_audio:
                self._audio.seek(self._position_sec)
            self._pull_and_show_frame()
        except RuntimeError as e:
            self._title.setText(f"Seek 失败: {e}")
            return
        self._update_time_label()
        if resume:
            self.play()

    @Slot(float)
    def _on_waveform_seek(self, sec: float):
        was = self._playing
        if was:
            self.pause()
        self._seek_to(sec, resume=was)

    def _start_audio_viz(self, path: str):
        """后台生成 showwavespic + ebur128，完成后刷新波形条。"""
        self._audio_viz_token += 1
        token = self._audio_viz_token
        self._waveform.clear()
        self._waveform.set_duration(self._duration_sec)
        self._waveform.set_busy(True, "分析波形 / 响度…")
        if not path or not os.path.isfile(path):
            return

        from PySide6.QtCore import QObject

        class _Sig(QObject):
            done = Signal(object)
            fail = Signal(str)

        sig = _Sig(self)

        def on_ok(result):
            if token != self._audio_viz_token:
                return
            if not result:
                return
            self._waveform.set_duration(self._duration_sec or result.duration_hint)
            if result.waveform_png:
                self._waveform.set_waveform_png(result.waveform_png)
            self._waveform.set_loudness(
                result.samples,
                integrated_lufs=result.integrated_lufs,
                lra=result.lra,
            )
            log.info(
                "音频可视化就绪 samples=%d I=%.1f PNG=%s",
                len(result.samples),
                result.integrated_lufs,
                bool(result.waveform_png),
            )

        def on_err(msg: str):
            if token != self._audio_viz_token:
                return
            self._waveform.set_busy(False, f"可视化失败: {msg[:80]}")
            log.warning("音频可视化失败: %s", msg)

        sig.done.connect(on_ok)
        sig.fail.connect(on_err)

        import threading
        from core.audio_viz import analyze_media_audio

        media = path
        dur = self._duration_sec

        def run():
            try:
                w = max(640, int(self._waveform.width()) * 2 or 1280)
                res = analyze_media_audio(media, wave_width=w, wave_height=72)
                if dur > 0:
                    res.duration_hint = dur
                sig.done.emit(res)
            except Exception as e:
                sig.fail.emit(str(e))

        threading.Thread(target=run, daemon=True).start()



    @Slot(int)

    def _on_volume_changed(self, value: int):

        if self._has_audio:

            self._audio.set_volume(value / 100.0)



    def _schedule_tick(self, delay_ms: int | None = None):
        if not self._playing or self._seeking:
            return
        ms = self._sync_timer_ms if delay_ms is None else max(1, delay_ms)
        QTimer.singleShot(ms, self._on_tick)

    @Slot()
    def _on_tick(self):

        if not self._playing or self._seeking:

            return

        t0 = time.monotonic()
        if self._audio_only:
            result = self._tick_audio_only()
        elif self._has_audio:
            result = self._sync_video_to_audio()
        else:
            result = self._pull_and_show_frame(apply_filter=None)

        if result is None:

            self.pause()
            return

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        self._schedule_tick(max(1, self._sync_timer_ms - elapsed_ms))

    def _tick_audio_only(self) -> bool | None:
        audio_sec = self._audio.position_sec()
        if self._duration_sec <= 0:
            dur = self._audio.duration_sec()
            if dur > 0:
                self._duration_sec = dur
                self._progress.setRange(0, max(int(dur * 1000), 1))

        self._position_sec = audio_sec
        if not self._seeking:
            self._progress.setValue(int(audio_sec * 1000))
        self._update_time_label()

        if self._duration_sec > 0 and audio_sec >= self._duration_sec - 0.05:
            self._position_sec = self._duration_sec
            self._progress.setValue(self._progress.maximum())
            self._update_time_label()
            return None
        return True

    def _sync_video_to_audio(self) -> bool | None:
        """每 tick 取下一帧显示；target 对齐 want_idx，避免重复取帧丢弃"""
        if not self._backend:
            return False

        audio_sec = self._audio.position_sec()
        now = time.monotonic()
        fi = self._frame_interval
        audio_idx = self._frame_index(audio_sec)

        if now - self._last_progress_wall >= 0.15:
            self._position_sec = audio_sec
            if not self._seeking:
                self._progress.setValue(int(audio_sec * 1000))
            self._update_time_label()
            self._last_progress_wall = now

        shown_idx = self._frame_index(self._last_shown_frame_ts)
        if audio_idx <= shown_idx:
            return True

        want_idx = shown_idx + 1
        if audio_idx - shown_idx > 6:
            want_idx = audio_idx - 1

        target_min = max(0.0, want_idx * fi - fi * 0.02)
        t0 = time.monotonic()

        try:
            # None：跟随 set_playback_filter；此前写死 False 导致趣味滤镜完全看不见
            frame = self._backend.next_frame(min_ts=target_min, apply_filter=None)
        except RuntimeError as e:
            log.error("同步解码失败: %s", e)
            self._title.setText(f"解码错误: {e}")
            self._playing = False
            self._timer.stop()
            return None
        if frame is None:
            return None

        ts, rgb, w, h = frame
        new_idx = self._frame_index(ts)
        if new_idx < want_idx:
            return True

        stats = self._backend.last_frame_stats
        ui_ms = int((time.monotonic() - t0) * 1000)
        paint_t0 = time.monotonic()
        self._show_frame(ts, rgb, w, h, update_progress=False)
        paint_ms = int((time.monotonic() - paint_t0) * 1000)

        if stats.decode_ms > 25 or ui_ms > 30 or paint_ms > 15:
            log.debug(
                "同步 idx=%d/%d want=%d ts=%.3f audio=%.3f decode=%dms ui=%dms paint=%dms skipped=%d",
                new_idx, audio_idx, want_idx, ts, audio_sec,
                stats.decode_ms, ui_ms, paint_ms, stats.skipped,
            )
        return True

    def _show_frame(self, ts: float, rgb: bytes, w: int, h: int, update_progress: bool = True):
        self._last_shown_frame_ts = ts
        if update_progress and not self._seeking:
            self._position_sec = ts
            self._progress.setValue(int(ts * 1000))
            self._update_time_label()

        need = w * h * 3
        if self._frame_rgb_buf is None or len(self._frame_rgb_buf) != need:
            self._frame_rgb_buf = bytearray(need)
        self._frame_rgb_buf[:] = rgb

        self._display.set_rgb_frame(self._frame_rgb_buf, w, h)

    def _pull_and_show_frame(self, apply_filter: bool | None = None) -> bool | None:

        if not self._backend:

            return False

        try:
            min_ts = max(0.0, self._position_sec - self._frame_interval * 0.5)
            frame = self._backend.next_frame(min_ts=min_ts, apply_filter=apply_filter)

        except RuntimeError as e:

            self._title.setText(f"解码错误: {e}")

            self._playing = False

            self._timer.stop()

            return None

        if frame is None:

            return None



        ts, rgb, w, h = frame
        self._position_sec = ts
        self._show_frame(ts, rgb, w, h)
        return True



    def _update_time_label(self):
        self._time_label.setText(
            f"{_format_time(self._position_sec)} / {_format_time(self._duration_sec)}"
        )
        self._waveform.set_position(self._position_sec)
        self._sync_subtitle()

    def _sync_subtitle(self):
        if self._subtitles.empty:
            return
        text = self._subtitles.text_at(self._position_sec)
        self._display.set_subtitle_text(text)

    def _try_autoload_sidecar_subtitles(self, video_path: str):
        side = find_sidecar_subtitles(video_path)
        if not side:
            return
        try:
            self._load_subtitle_path(side)
            log.info("自动加载字幕 %s (%d cues)", side, len(self._subtitles.cues))
        except Exception as e:
            log.warning("自动加载字幕失败: %s", e)

    def _load_subtitle_path(self, path: str):
        track = SubtitleTrack.from_file(path)
        if track.empty:
            raise RuntimeError("未解析到字幕条目")
        self._subtitles = track
        self._btn_clear_sub.setEnabled(True)
        self._sync_subtitle()
        # 标题追加字幕提示
        tip = f"字幕:{os.path.basename(path)}"
        cur = self._title.text()
        parts = [p.strip() for p in cur.split("·")]
        parts = [p for p in parts if not p.startswith("字幕:")]
        parts.append(tip)
        self._title.setText("  ·  ".join(parts))

    @Slot()
    def _on_load_subtitle(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择字幕文件",
            os.path.dirname(self._current_path) if self._current_path else "",
            "字幕 (*.srt *.vtt *.ass);;所有文件 (*.*)",
        )
        if not path:
            return
        try:
            self._load_subtitle_path(path)
            log.info("已加载字幕 %s (%d cues)", path, len(self._subtitles.cues))
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "字幕", f"加载失败: {e}")

    def _clear_subtitles(self, *, silent: bool = False):
        self._subtitles.clear()
        self._display.set_subtitle_text("")
        self._btn_clear_sub.setEnabled(False)
        if not silent:
            cur = self._title.text()
            parts = [p.strip() for p in cur.split("·") if not p.strip().startswith("字幕:")]
            self._title.setText("  ·  ".join(parts) if parts else cur)

    @Slot()
    def _on_clear_subtitle(self):
        self._clear_subtitles(silent=False)
        log.info("已关闭字幕")

    @Slot()
    def _on_live_subtitle(self):
        """实时字幕：尝试启动预留管线；后端未接时展示接入说明。"""
        from core.live_subtitle import (
            LiveSubtitleConfig,
            create_pipeline,
            provider_status,
        )

        # 若已在跑，则停止
        if self._live_pipeline is not None and getattr(self._live_pipeline, "running", False):
            try:
                self._live_pipeline.stop()
            except Exception:
                log.exception("停止实时字幕失败")
            self._live_pipeline = None
            self._btn_live_sub.setText("实时字幕")
            self._display.set_subtitle_text("")
            QMessageBox.information(self, "实时字幕", "已关闭实时字幕会话。")
            return

        cfg_map = load_app_config()
        config = LiveSubtitleConfig.from_mapping(cfg_map)
        # AppLogic 若已解析配置，优先覆盖
        app = AppLogic()
        if getattr(app, "live_subtitle_config", None):
            config = app.live_subtitle_config

        status = provider_status(config)
        try:
            pipeline = create_pipeline(
                config,
                self._display.set_subtitle_text,
                enable_ws=True,
            )
            pipeline.start()
        except Exception as e:
            QMessageBox.information(
                self,
                "实时字幕（接口预留）",
                f"{e}\n\n—— 当前配置 ——\n{status}",
            )
            return

        self._live_pipeline = pipeline
        self._btn_live_sub.setText("停实时字幕")
        QMessageBox.information(
            self,
            "实时字幕",
            "实时字幕会话已启动。\n"
            "请向 pipeline.feed_pcm() 喂入 16kHz PCM（播放器音轨抽头尚未接通）。\n\n"
            f"{status}",
        )

    def load_from_video_model(self, video, auto_play: bool = False):

        if video and getattr(video, "file_path", ""):

            self.open_file(video.file_path, auto_play=auto_play)



    def resizeEvent(self, event):
        super().resizeEvent(event)



    def shutdown(self):
        """停止播放并释放子进程（应用退出时调用）"""
        self._timer.stop()
        self._playing = False
        self._has_audio = False
        self._current_path = ""
        if self._live_pipeline is not None:
            try:
                self._live_pipeline.stop()
            except Exception:
                pass
            self._live_pipeline = None
        self._audio.shutdown()
        if self._backend:
            self._backend.shutdown()
        if isinstance(self._display, GlVideoWidget):
            self._display.set_paused_overlay(False)
            self._display.clear_frame()
            self._display.cleanup_gl()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)


