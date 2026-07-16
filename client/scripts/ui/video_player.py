"""本地视频播放器 — Python GUI + C++ FFmpeg 解码（统一播放器）"""



from __future__ import annotations



import math
import os
import time



from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QImage, QSurfaceFormat

from PySide6.QtWidgets import (

    QFileDialog, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget,

)



from core.player_backend import PlayerBackend
from core.qt_audio_output import QtAudioOutput
from core.app_logic import AppLogic, load_app_config
from core.app_logger import setup_logging
from ui.gl_video_widget import GlVideoWidget, _default_surface_format

log = setup_logging("VideoPlayer", __import__("os").environ.get("MUSIC_LOG_LEVEL", "INFO"))





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
        self._hw_decode_preferred = AppLogic().prefer_hw_decode
        self._hw_decode_active = False



        # OpenGL 显示区：须在创建 QOpenGLWidget 前设置默认 SurfaceFormat
        QSurfaceFormat.setDefaultFormat(_default_surface_format())

        self._title = QLabel("未加载视频 · FFmpeg 解码 · OpenGL 显示")

        self._title.setStyleSheet("color: #ccc; font-size: 13px;")



        self._display = GlVideoWidget()
        self._display.set_placeholder("请打开本地视频")



        self._btn_open = QPushButton("打开视频")

        self._btn_play = QPushButton("播放")

        self._btn_pause = QPushButton("暂停")

        self._btn_stop = QPushButton("停止")



        self._progress = QSlider(Qt.Horizontal)

        self._progress.setRange(0, 1000)

        self._time_label = QLabel("00:00 / 00:00")

        self._time_label.setStyleSheet("color: #888; min-width: 110px;")



        self._volume = QSlider(Qt.Horizontal)

        self._volume.setRange(0, 100)

        self._volume.setValue(70)

        self._volume.setFixedWidth(90)

        self._volume.setToolTip("音量")



        ctrl = QHBoxLayout()

        ctrl.addWidget(self._btn_open)

        ctrl.addWidget(self._btn_play)

        ctrl.addWidget(self._btn_pause)

        ctrl.addWidget(self._btn_stop)

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

        layout.addLayout(seek_row)

        layout.addLayout(ctrl)



        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._on_tick)



        self._btn_open.clicked.connect(self._on_open)

        self._btn_play.clicked.connect(self.play)

        self._btn_pause.clicked.connect(self.pause)

        self._btn_stop.clicked.connect(self.stop)

        self._progress.sliderPressed.connect(self._on_seek_pressed)

        self._progress.sliderReleased.connect(self._on_seek_released)

        self._volume.valueChanged.connect(self._on_volume_changed)



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

            self, "选择视频",

            self._current_path or "",

            "视频文件 (*.mp4 *.mov *.avi *.flv *.mkv *.wmv);;所有文件 (*.*)",

        )

        if path:

            self.open_file(path)



    def open_file(self, path: str, auto_play: bool = False):
        if not self._backend or not os.path.isfile(path):
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

    def _do_open_file(self, path: str, auto_play: bool = False):
        self._timer.stop()
        self._audio.stop()
        self._reset_transport_controls(playing=False)

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
        ]
        if self._opencv_filter and self._opencv_filter != "off":
            if self._opencv_filter_playback or not info.hw_decode:
                title_parts.append(f"OpenCV:{self._opencv_filter}")
            else:
                title_parts.append("OpenCV:预览")
        self._title.setText("  ·  ".join(title_parts))
        log.info(
            "视频已打开 %s %dx%d %s hw=%s",
            os.path.basename(path), info.width, info.height, decode_hint, info.hw_decode,
        )
        self._progress.setRange(0, max(int(self._duration_sec * 1000), 1))
        self._progress.setValue(0)
        self._update_time_label()

        self._pull_and_show_frame(apply_filter=True)

        # 同步到 ViewModel（此时 current_path 已设置，不会触发重复 open）
        self.fileOpened.emit(self._current_path)

        if auto_play:
            self.play()

    def _apply_opencv_filter(self):
        """应用 app.conf 中的 opencv_filter（未编译 OpenCV 时静默忽略）"""
        if not self._backend or not self._opencv_filter:
            return
        try:
            self._backend.set_filter(self._opencv_filter)
        except RuntimeError:
            pass



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

        if not self._backend or not self._current_path:

            return

        # 硬解 + CLAHE 每帧开销大：播放时默认关闭 OpenCV 滤镜
        use_filter = self._opencv_filter_playback
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
            pw if self._backend else 0, ph if self._backend else 0,
        )



    def pause(self):

        self._timer.stop()

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

        if not self._backend or self._duration_sec <= 0:

            return

        ratio = self._progress.value() / max(self._progress.maximum(), 1)

        self._position_sec = ratio * self._duration_sec

        try:

            self._backend.seek(self._position_sec)

            if self._has_audio:

                self._audio.seek(self._position_sec)

            self._pull_and_show_frame()

        except RuntimeError as e:

            self._title.setText(f"Seek 失败: {e}")

            return



        if self._was_playing_before_seek:
            self.play()



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
        if self._has_audio:
            result = self._sync_video_to_audio()
        else:
            result = self._pull_and_show_frame()

        if result is None:

            self.pause()
            return

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        self._schedule_tick(max(1, self._sync_timer_ms - elapsed_ms))

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
            frame = self._backend.next_frame(min_ts=target_min, apply_filter=False)
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

    def _pull_and_show_frame(self, apply_filter: bool = False) -> bool | None:

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
        self._audio.shutdown()
        if self._backend:
            self._backend.shutdown()
        if isinstance(self._display, GlVideoWidget):
            self._display.clear_frame()
            self._display.cleanup_gl()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)


