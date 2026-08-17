"""本地视频播放器 — Python GUI + C++ FFmpeg 解码（统一播放器）"""



from __future__ import annotations



import math
import os
import time
from concurrent.futures import Future, ThreadPoolExecutor

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
from ui.gl_video_widget import GlVideoWidget, SoftVideoWidget, _default_surface_format
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

    - 视频：media_player.exe (FFmpeg) → SoftVideoWidget 软件显示（可选 GlVideoWidget）
    - 音频：Qt QMediaPlayer（仅音频轨，Windows 下更稳定）

    """



    fileOpened = Signal(str)
    displayWidgetChanged = Signal(object)



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
        self._decode_pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="me_decode",
        )
        self._decode_future: Future | None = None
        self._decode_token = 0
        self._seek_pending_resume: bool | None = None
        self._seek_busy = False
        self._opencv_filter = load_app_config().get("opencv_filter", "clahe")
        _cfg = load_app_config()
        _pb = _cfg.get("opencv_filter_playback", "off").strip().lower()
        self._opencv_filter_playback = _pb not in ("0", "false", "off", "no")
        self._opencv_filter_device = _cfg.get("opencv_filter_device", "auto").strip().lower() or "auto"
        self._opencv_filter_active_device = "cpu"
        self._hw_decode_preferred = AppLogic().prefer_hw_decode
        self._hw_decode_active = False
        self._audio_only = False
        self._audio_viz_token = 0
        # 音画双时钟：仅大偏差时软校正（常态 200~300ms 解码滞后不触发）
        self._drift_streak = 0
        self._last_soft_resync_wall = 0.0
        self._play_started_wall = 0.0
        self._info_busy = False

        # OpenGL 显示区：须在创建 QOpenGLWidget 前设置默认 SurfaceFormat
        QSurfaceFormat.setDefaultFormat(_default_surface_format())

        self._title = QLabel("未加载 · 支持视频 / 音乐")
        self._title.setObjectName("MutedText")

        # 首页预览默认软件绘制：部分环境（远程桌面/Mesa/软件 GL）Shader「成功」但纹理全黑，
        # 表现为「有声音无画面」。照片编辑器仍用 GlVideoWidget。要试 GPU 显示设 MUSIC_GL_VIDEO=1。
        use_gl = (os.environ.get("MUSIC_GL_VIDEO") or "").strip().lower() in (
            "1", "true", "yes", "on",
        )
        force_soft = (os.environ.get("MUSIC_SOFTWARE_GL") or "").strip().lower() in (
            "1", "true", "yes", "on",
        )
        self._display: GlVideoWidget | SoftVideoWidget
        if use_gl and not force_soft:
            self._display = GlVideoWidget()
        else:
            self._display = SoftVideoWidget()
        self._display.set_placeholder(
            "请打开本地视频或音乐\n点击画面可选文件；播放中点击可暂停 / 继续"
        )
        self._display.renderFailed.connect(self._on_gl_render_failed)
        self._gl_failed_once = False
        self._eof_streak = 0
        self._btn_open = QPushButton("打开文件")
        self._btn_play = QPushButton("播放")

        self._btn_pause = QPushButton("暂停")

        self._btn_stop = QPushButton("停止")
        self._btn_info = QPushButton("信息")
        self._btn_info.setToolTip("ffprobe 查看封装 / 编码 / 分辨率 / 码率（VideoEye 精简）")
        self._btn_info.setEnabled(False)

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
        ctrl.addWidget(self._btn_info)

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
        self._btn_info.clicked.connect(self._on_media_info)


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

    @property
    def display_widget(self) -> QWidget:
        """画面控件（供首页弹幕层叠放）。"""
        return self._display



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

    def _set_media_loaded(self, loaded: bool):
        self._btn_info.setEnabled(bool(loaded) and not self._info_busy)

    @Slot()
    def _on_media_info(self):
        """异步 ffprobe，弹出媒体信息对话框。"""
        path = self._current_path
        if not path or not os.path.isfile(path) or self._info_busy:
            return
        self._info_busy = True
        self._btn_info.setEnabled(False)
        self._btn_info.setText("探测…")

        from PySide6.QtCore import QObject

        class _Sig(QObject):
            done = Signal(object)
            fail = Signal(str)

        sig = _Sig(self)

        def on_ok(result):
            self._info_busy = False
            self._btn_info.setText("信息")
            self._set_media_loaded(bool(self._current_path))
            tip = getattr(result, "tooltip_line", lambda: "")()
            if tip:
                self._title.setToolTip(tip)
            from ui.media_info_dialog import MediaInfoDialog
            MediaInfoDialog(result, self).exec()

        def on_fail(msg: str):
            self._info_busy = False
            self._btn_info.setText("信息")
            self._set_media_loaded(bool(self._current_path))
            QMessageBox.warning(self, "媒体信息", msg or "探测失败")

        sig.done.connect(on_ok)
        sig.fail.connect(on_fail)

        def work():
            try:
                from core.media_probe import probe_media
                sig.done.emit(probe_media(path))
            except Exception as e:
                sig.fail.emit(str(e))

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _refresh_media_tooltip_async(self, path: str):
        """打开文件后后台写标题 Tooltip，不弹窗。"""
        if not path:
            return
        token_path = path

        from PySide6.QtCore import QObject

        class _Sig(QObject):
            done = Signal(str, str)  # path, tip

        sig = _Sig(self)

        def on_done(p: str, tip: str):
            if p == self._current_path and tip:
                self._title.setToolTip(tip)

        sig.done.connect(on_done)

        def work():
            try:
                from core.media_probe import probe_media
                r = probe_media(token_path)
                sig.done.emit(token_path, r.tooltip_line())
            except Exception:
                pass

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _maybe_soft_resync(self, audio_sec: float) -> bool:
        """仅在大偏差时把画面追到音频时钟；不碰音轨，避免「咔」一下。

        双通道常态会有约 100~250ms 解码/显示滞后，属正常，靠跳帧追赶即可。
        """
        if self._seeking or self._audio_only or not self._backend:
            return False
        if self._last_shown_frame_ts < 0:
            return False
        now = time.monotonic()
        # 开播宽限期：时钟尚未稳态（略缩短，更快进入可校正）
        if self._play_started_wall > 0 and (now - self._play_started_wall) < 2.0:
            self._drift_streak = 0
            return False
        if now - self._last_soft_resync_wall < 2.8:
            return False

        video_ts = self._last_shown_frame_ts
        drift = video_ts - audio_sec  # >0 画面超前；<0 画面落后
        abs_drift = abs(drift)

        # 画面略落后：交给 next_frame(min_ts) 跳帧，不 seek
        if drift < 0 and abs_drift < 0.35:
            self._drift_streak = 0
            return False
        # 画面略超前：等音频追上即可
        if drift > 0 and abs_drift < 0.28:
            self._drift_streak = 0
            return False

        self._drift_streak += 1
        if self._drift_streak < 8:
            return False

        log.info(
            "音画软校正(仅视频) drift=%+.0fms audio=%.3f video=%.3f",
            drift * 1000.0, audio_sec, video_ts,
        )
        self._drift_streak = 0
        self._last_soft_resync_wall = now
        # 只把画面对齐到音频，绝不 seek 音轨（seek 音频会出爆音/卡顿感）
        self._soft_resync_video_only(audio_sec)
        return True

    def _soft_resync_video_only(self, audio_sec: float) -> None:
        """仅 seek 视频解码位置到音频时钟；音轨保持播放。"""
        target = max(0.0, float(audio_sec))
        if self._duration_sec > 0:
            target = min(target, self._duration_sec)
        self._decode_token += 1
        self._decode_future = None
        self._last_shown_frame_ts = -1.0
        try:
            if not self._backend:
                return
            frame = self._backend.seek_and_frame(
                target,
                min_ts=max(0.0, target - self._frame_interval * 0.5),
                apply_filter=None,
            )
            if frame:
                ts, rgb, w, h = frame
                self._show_frame(ts, rgb, w, h, update_progress=False)
                self._submit_lookahead_decode(self._frame_index(ts))
            if self._playing:
                self._backend.resume()
        except RuntimeError as e:
            log.warning("视频软校正失败: %s", e)

    def _soft_resync_to(self, sec: float) -> None:
        """兼容旧名：改为仅校正视频。"""
        self._soft_resync_video_only(sec)

    @Slot()
    def _on_display_clicked(self):
        """点击画面：未加载时与「打开文件」相同；已加载则暂停/继续。"""
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
        self._set_media_loaded(True)
        self._refresh_media_tooltip_async(self._current_path)
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
        self._audio_only = False
        self._filter_combo.setEnabled(True)
        self._decode_token += 1
        self._decode_future = None
        self._last_shown_frame_ts = -1.0

        if not self._backend:
            self._title.setText("打开失败: 未找到 media_player.exe（请用完整便携包）")
            return

        self._backend.set_hwaccel(self._hw_decode_preferred)

        try:
            info = self._backend.open(path)
        except RuntimeError as e:
            # 部分干净机硬解驱动异常：自动关硬解再试一次
            if self._hw_decode_preferred:
                log.warning("硬解开失败，改 CPU 重试: %s", e)
                try:
                    self._backend.set_hwaccel(False)
                    self._hw_decode_preferred = False
                    info = self._backend.open(path)
                except RuntimeError as e2:
                    log.error("打开视频失败(CPU): %s", e2)
                    self._title.setText(f"打开失败: {e2}")
                    return
            else:
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
            "软件画面" if isinstance(self._display, SoftVideoWidget) else "OpenGL",
            audio_hint,
            "点击画面暂停/继续",
        ]
        if self._opencv_filter and self._opencv_filter != "off":
            tag = self._opencv_title_tag()
            if tag:
                title_parts.append(tag)
        self._title.setText("  ·  ".join(title_parts))
        self._set_media_loaded(True)
        self._drift_streak = 0
        self._last_soft_resync_wall = 0.0
        self._refresh_media_tooltip_async(self._current_path)
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

        # 自动加载同目录同名字幕（UI 隐藏期间不自动叠加，接口仍保留）

        self._waveform.set_duration(self._duration_sec)
        self._start_audio_viz(self._current_path)

        # 同步到 ViewModel（此时 current_path 已设置，不会触发重复 open）
        self.fileOpened.emit(self._current_path)

        if auto_play:
            self.play()

    def _on_gl_render_failed(self, reason: str):
        """差显卡 / 远程桌面 / 便携包：换 SoftVideoWidget，避免坏 GL 上下文上有声黑屏。"""
        if self._gl_failed_once:
            return
        self._gl_failed_once = True
        log.warning("OpenGL 显示失败，切换软件绘制: %s", reason)

        old = self._display
        soft = SoftVideoWidget()
        soft.set_placeholder(
            "请打开本地视频或音乐\n点击画面可选文件；播放中点击可暂停 / 继续"
        )
        # 继承当前帧 / 暂停态，避免切换瞬间空白
        try:
            if getattr(old, "_current_image", None) is not None and not old._current_image.isNull():
                soft.set_qimage(old._current_image)
            soft.set_paused_overlay(bool(getattr(old, "_paused_overlay", False)))
        except Exception:
            pass

        lay = self.layout()
        if lay is not None:
            lay.replaceWidget(old, soft)
        soft.clicked.connect(self._on_display_clicked)
        self._display = soft
        try:
            if isinstance(old, GlVideoWidget):
                old.cleanup_gl()
            old.deleteLater()
        except Exception:
            pass

        tip = "画面已改用软件绘制（OpenGL 不可用）"
        cur = self._title.text() or ""
        if tip not in cur:
            self._title.setText(f"{cur}  ·  {tip}" if cur else tip)
        self.displayWidgetChanged.emit(soft)

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
                    frame = self._backend.seek_and_frame(
                        pos,
                        min_ts=max(0.0, pos - self._frame_interval * 0.5),
                        apply_filter=True,
                    )
                    if frame:
                        ts, rgb, w, h = frame
                        self._show_frame(ts, rgb, w, h)
                except RuntimeError:
                    pass
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

    def _at_playback_end(self) -> bool:
        """是否已播到结尾（再点播放应从头开始）。"""
        if self._duration_sec <= 0:
            return False
        # 进度条已到头，或时钟贴近片尾
        if self._progress.maximum() > 0 and self._progress.value() >= self._progress.maximum() - 1:
            return True
        return self._position_sec >= self._duration_sec - 0.15

    def _prepare_restart_from_start(self) -> None:
        """播完后重播前：seek 到 0，避免卡在 EOF。"""
        self._position_sec = 0.0
        self._last_shown_frame_ts = -1.0
        self._progress.setValue(0)
        self._decode_token += 1
        self._decode_future = None
        if self._audio_only:
            self._audio.seek(0.0)
            self._update_time_label()
            return
        if not self._backend:
            return
        try:
            if self._has_audio:
                self._audio.seek(0.0)
            frame = self._backend.seek_and_frame(0.0, min_ts=0.0, apply_filter=None)
            if frame:
                ts, rgb, w, h = frame
                self._show_frame(ts, rgb, w, h)
        except RuntimeError:
            pass
        self._update_time_label()

    def play(self):

        if not self._current_path:
            return

        # 播放完成后点「播放」/点画面：从头开始，而不是停在片尾无反应
        if self._at_playback_end():
            self._prepare_restart_from_start()

        if self._audio_only:
            if self._duration_sec <= 0:
                dur = self._audio.duration_sec()
                if dur > 0:
                    self._duration_sec = dur
                    self._progress.setRange(0, max(int(dur * 1000), 1))
            self._audio.play(self._position_sec)
            self._playing = True
            self._eof_streak = 0
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
        self._drift_streak = 0
        self._play_started_wall = time.monotonic()

        self._playing = True
        self._reset_transport_controls(playing=True)
        self._eof_streak = 0
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
        self._frame_rgb_buf = None
        self._decode_token += 1

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
            else:
                # 首帧已显示后丢掉 Python 侧多余缓冲，降低停播 RSS
                self._frame_rgb_buf = None



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
        # 保持 _seeking，直到异步首帧回来，避免空窗 tick 抢 IPC
        if not self._current_path or self._duration_sec <= 0:
            self._seeking = False
            return
        ratio = self._progress.value() / max(self._progress.maximum(), 1)
        self._seek_to(ratio * self._duration_sec, resume=self._was_playing_before_seek)

    def _seek_to(self, position_sec: float, *, resume: bool | None = None):
        """统一 seek（进度条 / 波形点击）：后台 SEEK+首帧，避免卡住 UI。"""
        if not self._current_path or self._duration_sec <= 0:
            self._seeking = False
            return
        self._position_sec = max(0.0, min(float(position_sec), self._duration_sec))
        self._progress.setValue(int(self._position_sec * 1000))
        self._decode_token += 1
        self._decode_future = None
        self._last_shown_frame_ts = -1.0
        self._drift_streak = 0
        self._last_soft_resync_wall = time.monotonic()
        self._seeking = True
        self._seek_busy = True
        self._seek_pending_resume = resume
        if self._audio_only:
            self._audio.seek(self._position_sec)
            self._update_time_label()
            self._seeking = False
            self._seek_busy = False
            if resume:
                self.play()
            return
        if not self._backend:
            self._seeking = False
            self._seek_busy = False
            return
        try:
            self._title.setText(self._title.text().split(" · ")[0] + " · Seek…")
            if self._has_audio:
                self._audio.seek(self._position_sec)
        except RuntimeError as e:
            self._title.setText(f"Seek 失败: {e}")
            self._seeking = False
            self._seek_busy = False
            return

        token = self._decode_token
        backend = self._backend
        pos = self._position_sec
        fi = self._frame_interval

        def _job():
            if token != self._decode_token:
                return False
            return backend.seek_and_frame(
                pos,
                min_ts=max(0.0, pos - fi * 0.5),
                apply_filter=None,
            )

        self._decode_future = self._decode_pool.submit(_job)
        QTimer.singleShot(5, self._poll_seek_result)

    @Slot()
    def _poll_seek_result(self):
        """收割异步 Seek 首帧。"""
        if not self._seek_busy:
            return
        fut = self._decode_future
        if fut is None:
            self._seeking = False
            self._seek_busy = False
            return
        if not fut.done():
            QTimer.singleShot(5, self._poll_seek_result)
            return

        self._decode_future = None
        resume = self._seek_pending_resume
        self._seek_pending_resume = None
        self._seek_busy = False
        try:
            frame = fut.result()
        except RuntimeError as e:
            self._title.setText(f"Seek 失败: {e}")
            self._seeking = False
            return
        except Exception as e:
            log.warning("Seek 异常: %s", e)
            self._seeking = False
            return

        if frame and frame is not False:
            ts, rgb, w, h = frame
            self._show_frame(ts, rgb, w, h)
            # 预热下一帧，恢复播放时少空一拍
            self._submit_lookahead_decode(self._frame_index(ts))
            base = self._title.text().split(" · ")[0]
            self._title.setText(base)

        self._update_time_label()
        self._seeking = False
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
            # 单次 FRAME_EOF 可能是音频时钟异常追帧误伤；连续确认后再锁片尾
            self._eof_streak = getattr(self, "_eof_streak", 0) + 1
            near_end = (
                self._duration_sec > 0
                and self._position_sec >= self._duration_sec - 0.35
            )
            if self._eof_streak < 3 and not near_end:
                log.warning(
                    "疑似假 EOF streak=%d pos=%.2f dur=%.2f，继续播",
                    self._eof_streak, self._position_sec, self._duration_sec,
                )
                self._schedule_tick(self._sync_timer_ms)
                return
            if self._duration_sec > 0:
                self._position_sec = self._duration_sec
                self._progress.setValue(self._progress.maximum())
                self._update_time_label()
            self.pause()
            return

        self._eof_streak = 0
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
        """音频时钟对齐：解码在后台线程，UI 只贴帧。"""
        if not self._backend:
            return False

        audio_sec = self._audio.position_sec()
        now = time.monotonic()

        # 开播保护：便携包若 Qt 音频时钟误跳到片尾，改走视频时钟，避免立刻追到 EOF
        if (
            self._play_started_wall
            and now - self._play_started_wall < 2.5
            and self._duration_sec > 1.0
            and audio_sec >= max(0.0, self._duration_sec - 0.4)
        ):
            log.warning(
                "音频时钟异常跳尾 audio=%.2f dur=%.2f，改用视频时钟",
                audio_sec, self._duration_sec,
            )
            return self._pull_and_show_frame(apply_filter=None)

        audio_idx = self._frame_index(audio_sec)

        # 双时钟长期漂移 → 软校正（冷却 3.5s，连续约 12 次超阈值）
        if self._maybe_soft_resync(audio_sec):
            return True

        if now - self._last_progress_wall >= 0.15:
            self._position_sec = audio_sec
            if not self._seeking:
                self._progress.setValue(int(audio_sec * 1000))
            self._update_time_label()
            self._last_progress_wall = now

        shown_idx = self._frame_index(self._last_shown_frame_ts)
        # 音频尚未追上画面：预热下一帧解码，但先不贴帧
        if audio_idx <= shown_idx:
            if self._decode_future is None:
                self._submit_lookahead_decode(shown_idx)
            return True

        # 收割后台解码结果
        fut = self._decode_future
        if fut is not None:
            if not fut.done():
                return True
            self._decode_future = None
            try:
                frame = fut.result()
            except RuntimeError as e:
                log.error("同步解码失败: %s", e)
                self._title.setText(f"解码错误: {e}")
                self._playing = False
                self._timer.stop()
                return None
            except Exception as e:
                log.error("同步解码异常: %s", e)
                return True
            if frame is None:
                return None
            if frame is False:
                return True
            ts, rgb, w, h = frame
            new_idx = self._frame_index(ts)
            paint_t0 = time.monotonic()
            self._show_frame(ts, rgb, w, h, update_progress=False)
            paint_ms = int((time.monotonic() - paint_t0) * 1000)
            stats = self._backend.last_frame_stats
            if stats.decode_ms > 25 or paint_ms > 15 or stats.from_prefetch:
                log.debug(
                    "同步 idx=%d/%d ts=%.3f audio=%.3f decode=%dms paint=%dms skipped=%d prefetch=%s",
                    new_idx, audio_idx, ts, audio_sec,
                    stats.decode_ms, paint_ms, stats.skipped, stats.from_prefetch,
                )
            shown_idx = self._frame_index(self._last_shown_frame_ts)
            if audio_idx <= shown_idx:
                self._submit_lookahead_decode(shown_idx)
                return True

        # 提交下一帧解码（若空闲）
        if self._decode_future is not None and not self._decode_future.done():
            return True

        self._submit_lookahead_decode(shown_idx, audio_idx=audio_idx)
        return True

    def _submit_lookahead_decode(self, shown_idx: int, audio_idx: int | None = None) -> None:
        """保持 1 帧预取：解码 shown_idx+1（落后过多则追到 audio 附近）。"""
        if not self._backend:
            return
        if self._decode_future is not None and not self._decode_future.done():
            return
        fi = self._frame_interval
        want_idx = shown_idx + 1
        # 开播 2s 内禁止大跨度追帧，避免音频时钟异常把画面拽到片尾
        catch_up_ok = (
            not self._play_started_wall
            or (time.monotonic() - self._play_started_wall) >= 2.0
        )
        if catch_up_ok and audio_idx is not None and audio_idx - shown_idx > 6:
            want_idx = audio_idx - 1
        target_min = max(0.0, want_idx * fi - fi * 0.02)
        token = self._decode_token
        backend = self._backend

        def _job():
            if token != self._decode_token:
                return False
            return backend.next_frame(min_ts=target_min, apply_filter=None)

        self._decode_future = self._decode_pool.submit(_job)

    def _show_frame(self, ts: float, rgb: bytes, w: int, h: int, update_progress: bool = True):
        self._last_shown_frame_ts = ts
        if update_progress and not self._seeking:
            self._position_sec = ts
            self._progress.setValue(int(ts * 1000))
            self._update_time_label()
        # 不再做 bytearray 二次拷贝，直接交给 OpenGL 上传路径
        self._display.set_rgb_frame(rgb, w, h)

    def _pull_and_show_frame(self, apply_filter: bool | None = None) -> bool | None:
        """无音轨或单次拉帧：同样走后台解码，避免卡 UI。"""
        if not self._backend:
            return False

        fut = self._decode_future
        if fut is not None and not fut.done():
            return True
        if fut is not None and fut.done():
            self._decode_future = None
            try:
                frame = fut.result()
            except RuntimeError as e:
                self._title.setText(f"解码错误: {e}")
                self._playing = False
                self._timer.stop()
                return None
            except Exception:
                return True
            if frame is None:
                return None
            if frame is False:
                return True
            ts, rgb, w, h = frame
            self._position_sec = ts
            self._show_frame(ts, rgb, w, h)
            return True

        min_ts = max(0.0, self._position_sec - self._frame_interval * 0.5)
        token = self._decode_token
        backend = self._backend

        def _job():
            if token != self._decode_token:
                return False
            return backend.next_frame(min_ts=min_ts, apply_filter=apply_filter)

        self._decode_future = self._decode_pool.submit(_job)
        return True



    def _update_time_label(self):
        self._time_label.setText(
            f"{_format_time(self._position_sec)} / {_format_time(self._duration_sec)}"
        )
        self._waveform.set_position(self._position_sec)

    def load_from_video_model(self, video, auto_play: bool = False):

        if video and getattr(video, "file_path", ""):

            self.open_file(video.file_path, auto_play=auto_play)



    def shutdown(self):
        """停止播放并释放子进程（应用退出时调用）"""
        self._timer.stop()
        self._playing = False
        self._has_audio = False
        self._current_path = ""
        self._set_media_loaded(False)
        self._title.setToolTip("")
        self._decode_token += 1
        self._decode_future = None
        self._frame_rgb_buf = None
        try:
            self._decode_pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self._decode_pool.shutdown(wait=False)
        except Exception:
            pass
        self._audio.shutdown()
        if self._backend:
            try:
                self._backend.release_media_buffers()
            except Exception:
                pass
            self._backend.shutdown()
        if isinstance(self._display, (GlVideoWidget, SoftVideoWidget)):
            self._display.set_paused_overlay(False)
            self._display.clear_frame()
            self._display.cleanup_gl()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)


