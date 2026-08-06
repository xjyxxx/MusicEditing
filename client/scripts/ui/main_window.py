"""主窗口 UI"""

from __future__ import annotations

import os
import threading

from PySide6.QtCore import Qt, Signal, Slot, QEvent, QPoint, QSize, QTimer
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QSlider, QComboBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core.time_format import format_range, format_timestamp
from ui.audio_fun_page import AudioFunPage
from ui.bgm_page import BgmPage
from ui.comment_marquee import (
    AREA_FULL, AREA_HALF, AREA_QUARTER, CommentMarquee,
)
from ui.cover_page import CoverPage
from ui.download_page import DownloadPage
from ui.enhance_page import EnhancePage
from ui.export_options_dialog import ExportOptionsDialog
from ui.highlight_timeline import HighlightTimelineWidget
from ui.media_library_page import MediaLibraryPage
from ui.pipeline_queue_page import PipelineQueuePage
from ui.profile_page import ProfilePage
from ui.setup_wizard import SetupWizardDialog
from ui.stego_page import StegoPage
from ui.theme import app_stylesheet, style_spinbox
from ui.video_player import VideoPlayerWidget, _is_audio_file
from ui.watermark_page import WatermarkPage
from ui.workflow_link import (
    MENU_GROUPS,
    PAGE_TITLES,
    TAB_AUDIO_FUN,
    TAB_COVER,
    TAB_DOWNLOAD,
    TAB_ENHANCE,
    TAB_HOME,
    TAB_LIBRARY,
    TAB_PIPELINE,
    TAB_PROFILE,
    TAB_SLICE,
    TAB_STEGO,
    TAB_WATERMARK,
    ask_video_handoff,
)
from viewmodels.main_vm import MainViewModel


class HomePage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._loading_with_comments = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(10)

        title = QLabel("MusicEditing")
        title.setObjectName("HomeTitle")
        layout.addWidget(title)
        subtitle = QLabel("本地音视频打开 · 预览 · 点击画面暂停/继续 · 可叠弹幕")
        subtitle.setObjectName("HomeSubtitle")
        layout.addWidget(subtitle)

        player_box = QGroupBox("本地预览")
        player_layout = QVBoxLayout(player_box)
        self._player_stage = QWidget()
        stage_layout = QVBoxLayout(self._player_stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.setSpacing(0)
        self._player = VideoPlayerWidget()
        stage_layout.addWidget(self._player)
        # 弹幕叠在画面区域（相对 stage 定位，避免做 OpenGL 子控件）
        self._marquee = CommentMarquee(self._player_stage)
        player_layout.addWidget(self._player_stage, 1)

        # 弹幕控制：速度 / 密度 / 显示区域
        danmaku_bar = QHBoxLayout()
        danmaku_bar.setSpacing(10)
        cap = QLabel("弹幕")
        cap.setObjectName("MutedText")
        danmaku_bar.addWidget(cap)

        danmaku_bar.addWidget(QLabel("速度"))
        self._dm_speed = QSlider(Qt.Horizontal)
        self._dm_speed.setRange(40, 250)  # ×0.01 → 0.40～2.50
        self._dm_speed.setValue(100)
        self._dm_speed.setFixedWidth(120)
        self._dm_speed.setToolTip("弹幕滚动速度")
        self._dm_speed_label = QLabel("1.00×")
        self._dm_speed_label.setObjectName("MutedText")
        self._dm_speed_label.setMinimumWidth(40)
        danmaku_bar.addWidget(self._dm_speed)
        danmaku_bar.addWidget(self._dm_speed_label)

        danmaku_bar.addWidget(QLabel("密度"))
        self._dm_density = QSlider(Qt.Horizontal)
        self._dm_density.setRange(40, 250)
        self._dm_density.setValue(100)
        self._dm_density.setFixedWidth(120)
        self._dm_density.setToolTip("弹幕生成密度与同屏数量")
        self._dm_density_label = QLabel("1.00×")
        self._dm_density_label.setObjectName("MutedText")
        self._dm_density_label.setMinimumWidth(40)
        danmaku_bar.addWidget(self._dm_density)
        danmaku_bar.addWidget(self._dm_density_label)

        danmaku_bar.addWidget(QLabel("区域"))
        self._dm_area = QComboBox()
        self._dm_area.addItem("全屏", AREA_FULL)
        self._dm_area.addItem("半屏", AREA_HALF)
        self._dm_area.addItem("四分之一", AREA_QUARTER)
        self._dm_area.setToolTip("弹幕占用画面高度（自顶部向下）")
        danmaku_bar.addWidget(self._dm_area)
        danmaku_bar.addStretch()
        player_layout.addLayout(danmaku_bar)

        layout.addWidget(player_box, 1)

        self._dm_speed.valueChanged.connect(self._on_dm_speed)
        self._dm_density.valueChanged.connect(self._on_dm_density)
        self._dm_area.currentIndexChanged.connect(self._on_dm_area)

        # 打开视频时同步导入到 ViewModel（供其他模块使用）；纯音频不走 probe_video
        self._player.fileOpened.connect(self._on_player_opened_for_vm)
        self._player.fileOpened.connect(self._on_player_file_opened)
        vm.videoLoaded.connect(self._on_video_loaded)
        # 下载完成不自动打开：由「送首页播放」/ previewPlayRequested 显式触发

        # 画面尺寸变化时重铺弹幕层
        self._player.display_widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self._player.display_widget and event.type() in (
            QEvent.Resize, QEvent.Show,
        ):
            self._layout_marquee()
        return super().eventFilter(obj, event)

    @Slot(int)
    def _on_dm_speed(self, value: int):
        scale = value / 100.0
        self._dm_speed_label.setText(f"{scale:.2f}×")
        self._marquee.set_speed(scale)

    @Slot(int)
    def _on_dm_density(self, value: int):
        dens = value / 100.0
        self._dm_density_label.setText(f"{dens:.2f}×")
        self._marquee.set_density(dens)

    @Slot(int)
    def _on_dm_area(self, _index: int):
        mode = self._dm_area.currentData()
        self._marquee.set_area_mode(str(mode or AREA_FULL))

    @Slot(str)
    def _on_player_opened_for_vm(self, path: str):
        """音频用 Qt 播放即可；仅视频才导入 ViewModel（避免 probe_video 报「导入失败」）。"""
        if not path or _is_audio_file(path):
            return
        self._vm.import_video(path)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_marquee()

    def showEvent(self, event):
        super().showEvent(event)
        self._layout_marquee()

    def _layout_marquee(self):
        host = self._player.display_widget
        top_left = host.mapTo(self._player_stage, QPoint(0, 0))
        w = max(1, host.width())
        h = max(1, host.height())
        self._marquee.setGeometry(top_left.x(), top_left.y(), w, h)
        self._marquee.raise_()

    @Slot(str)
    def _on_player_file_opened(self, _path: str):
        if not self._loading_with_comments:
            self._marquee.stop()

    def play_with_comments(self, path: str, comments, auto_play: bool = True):
        """打开媒体并叠加热评弹幕（由下载页「送首页播放」触发）。"""
        if not path or not os.path.isfile(path):
            return
        self._loading_with_comments = True
        try:
            self._player.open_file(path, auto_play=auto_play)
            self._layout_marquee()
            self._marquee.set_comments(list(comments or []))
        finally:
            self._loading_with_comments = False

    @Slot(object)
    def _on_video_loaded(self, video):
        """其他页面导入视频后，主页播放器同步加载（避免与当前已打开文件重复加载）"""
        if not video or not getattr(video, "file_path", ""):
            return
        cur = os.path.normcase(os.path.abspath(self._player.current_path or ""))
        vid = os.path.normcase(os.path.abspath(video.file_path))
        if cur != vid:
            self._player.load_from_video_model(video, auto_play=False)

    def shutdown_player(self):
        self._marquee.stop()
        self._player.shutdown()

    def apply_opencv_filter(self, mode: str) -> bool:
        """应用首页播放器滤镜（今日氛围等）。"""
        return self._player.set_filter_mode(mode)

    def prompt_open_media(self):
        """菜单「打开文件」：弹出播放器文件对话框。"""
        self._player._on_open()  # noqa: SLF001

class SlicePage(QWidget):
    """智能切片页：分析高光 → 缩略图时间轴 + 列表。"""

    thumbnailReady = Signal(int, int, str)  # gen, index, path

    def __init__(self, vm: MainViewModel, handoff=None, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._handoff = handoff  # Callable[[str, int], None]
        self._pending_publish = None
        self._duration_sec = 0.0
        self._syncing_selection = False
        self._last_result_path = ""
        layout = QVBoxLayout(self)

        # 导入区
        import_row = QHBoxLayout()
        self._file_label = QLabel("未选择视频")
        btn_import = QPushButton("导入视频")
        btn_import.clicked.connect(self._on_import)
        btn_use = QPushButton("用当前视频")
        btn_use.setToolTip("使用其它页已导入的共享视频")
        btn_use.clicked.connect(self._on_use_current_video)
        import_row.addWidget(self._file_label, 1)
        import_row.addWidget(btn_import)
        import_row.addWidget(btn_use)
        layout.addLayout(import_row)

        # 视频信息
        self._info_label = QLabel("")
        self._info_label.setObjectName("InfoText")
        layout.addWidget(self._info_label)

        # 参数配置
        params_box = QGroupBox("AI 识别参数")
        params_layout = QGridLayout(params_box)

        self._scene_combo = QComboBox()
        self._scene_combo.addItems(["游戏高光", "演讲金句", "日常精彩片段", "响度高潮", "自定义识别"])
        self._scene_combo.setToolTip(
            "演讲金句：有 Vosk 则转写+金句词/LLM；无模型则用人声段兜底\n"
            "响度高潮：FFmpeg ebur128 找响度峰值\n"
            "下载模型: scripts\\download_vosk_model.bat"
        )
        self._scene_hint = QLabel("")
        self._scene_hint.setObjectName("MutedText")
        self._scene_hint.setWordWrap(True)
        self._scene_combo.currentTextChanged.connect(self._on_scene_changed)
        params_layout.addWidget(QLabel("场景:"), 0, 0)
        params_layout.addWidget(self._scene_combo, 0, 1)
        params_layout.addWidget(self._scene_hint, 0, 2, 1, 2)

        self._min_slider = QSlider(Qt.Horizontal)
        self._min_slider.setRange(3, 30)
        self._min_slider.setValue(3)
        self._min_label = QLabel("3s")
        params_layout.addWidget(QLabel("最短片段:"), 1, 0)
        params_layout.addWidget(self._min_slider, 1, 1)
        params_layout.addWidget(self._min_label, 1, 2)

        self._max_slider = QSlider(Qt.Horizontal)
        self._max_slider.setRange(10, 120)
        self._max_slider.setValue(60)
        self._max_label = QLabel("60s")
        params_layout.addWidget(QLabel("最长片段:"), 2, 0)
        params_layout.addWidget(self._max_slider, 2, 1)
        params_layout.addWidget(self._max_label, 2, 2)

        self._sens_slider = QSlider(Qt.Horizontal)
        self._sens_slider.setRange(0, 100)
        self._sens_slider.setValue(50)
        self._sens_label = QLabel("50%")
        params_layout.addWidget(QLabel("敏感度:"), 3, 0)
        params_layout.addWidget(self._sens_slider, 3, 1)
        params_layout.addWidget(self._sens_label, 3, 2)

        self._min_slider.valueChanged.connect(lambda v: self._min_label.setText(f"{v}s"))
        self._max_slider.valueChanged.connect(lambda v: self._max_label.setText(f"{v}s"))
        self._sens_slider.valueChanged.connect(lambda v: self._sens_label.setText(f"{v}%"))

        layout.addWidget(params_box)

        # 手动切片（不依赖 Vosk）
        manual_box = QGroupBox("手动切片（无需 AI / Vosk）")
        manual_layout = QGridLayout(manual_box)
        self._manual_start = QDoubleSpinBox()
        self._manual_start.setRange(0.0, 86400.0)
        self._manual_start.setDecimals(1)
        self._manual_start.setSuffix(" s")
        self._manual_start.setSingleStep(0.5)
        style_spinbox(self._manual_start)
        self._manual_end = QDoubleSpinBox()
        self._manual_end.setRange(0.0, 86400.0)
        self._manual_end.setDecimals(1)
        self._manual_end.setSuffix(" s")
        self._manual_end.setSingleStep(0.5)
        self._manual_end.setValue(10.0)
        style_spinbox(self._manual_end)
        self._manual_range_label = QLabel("0:00 – 0:10")
        self._manual_range_label.setObjectName("InfoText")
        self._manual_start.valueChanged.connect(self._on_manual_spin)
        self._manual_end.valueChanged.connect(self._on_manual_spin)
        manual_layout.addWidget(QLabel("开始:"), 0, 0)
        manual_layout.addWidget(self._manual_start, 0, 1)
        manual_layout.addWidget(QLabel("结束:"), 0, 2)
        manual_layout.addWidget(self._manual_end, 0, 3)
        manual_layout.addWidget(self._manual_range_label, 0, 4)
        btn_add_manual = QPushButton("添加到列表")
        btn_add_manual.setToolTip("按起止时间添加片段，可与 AI 结果混用")
        btn_add_manual.clicked.connect(self._on_add_manual)
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._on_remove_selected)
        btn_clear = QPushButton("清空列表")
        btn_clear.clicked.connect(self._on_clear_segments)
        manual_layout.addWidget(btn_add_manual, 1, 0, 1, 2)
        manual_layout.addWidget(btn_del, 1, 2, 1, 1)
        manual_layout.addWidget(btn_clear, 1, 3, 1, 1)
        layout.addWidget(manual_box)

        # 进度
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # 高光时间轴（色块 + 片段缩略图）
        layout.addWidget(QLabel("高光时间轴（缩略图）"))
        self._timeline = HighlightTimelineWidget()
        self._timeline.segmentClicked.connect(self._on_timeline_segment)
        layout.addWidget(self._timeline)

        # 高光列表（带缩略图图标）
        self._highlight_list = QListWidget()
        self._highlight_list.setIconSize(QSize(96, 54))
        self._highlight_list.currentRowChanged.connect(self._on_list_row_changed)
        layout.addWidget(self._highlight_list)
        self._thumb_gen = 0
        self.thumbnailReady.connect(self._on_thumbnail_ready)

        # 操作按钮
        btn_row = QHBoxLayout()
        self._btn_analyze = QPushButton("AI 智能分析")
        self._btn_analyze.setObjectName("primaryButton")
        self._btn_analyze.setToolTip(
            "演讲类需 Vosk 模型；无模型请用「游戏高光」或上方「手动切片」"
        )
        self._btn_analyze.clicked.connect(self._on_analyze)
        btn_analyze = self._btn_analyze
        btn_export = QPushButton("一键高光成片")
        btn_export.setToolTip("导出列表中的片段，并拼接成 highlights_merged.mp4")
        btn_export.clicked.connect(self._on_export)
        btn_vertical = QPushButton("竖屏短视频")
        btn_vertical.setToolTip(
            "切片成片 → 9:16 裁切；若有同名 .srt/.vtt/.ass 则烧录字幕（片段会重定时）"
        )
        btn_vertical.clicked.connect(self._on_vertical_export)
        btn_silence = QPushButton("静音剪掉")
        btn_silence.setToolTip("检测静音段并裁掉，生成紧凑口播版")
        btn_silence.clicked.connect(self._on_compact_speech)
        btn_enhance = QPushButton("送去超分")
        btn_enhance.setToolTip("将高光成片（或当前视频）导入「画质增强」")
        btn_enhance.clicked.connect(lambda: self._send_to(TAB_ENHANCE))
        btn_wm = QPushButton("送去去水印")
        btn_wm.setToolTip("将高光成片（或当前视频）导入「去水印」")
        btn_wm.clicked.connect(lambda: self._send_to(TAB_WATERMARK))
        btn_row.addWidget(btn_analyze)
        btn_row.addWidget(btn_export)
        btn_row.addWidget(btn_vertical)
        btn_row.addWidget(btn_silence)
        btn_row.addWidget(btn_enhance)
        btn_row.addWidget(btn_wm)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        vm.videoLoaded.connect(self._on_video_loaded)
        vm.progressUpdated.connect(self._on_progress)
        vm.highlightsReady.connect(self._on_highlights)
        vm.exportFinished.connect(self._on_export_done)
        vm.silenceFinished.connect(self._on_silence_done)
        vm.verticalExportFinished.connect(self._on_vertical_done)
        vm.errorOccurred.connect(self._show_error)
        self._on_scene_changed(self._scene_combo.currentText())

    @Slot(str)
    def _on_scene_changed(self, scene: str):
        tips = {
            "游戏高光": "PySceneDetect 视觉场景切点（Adaptive）；失败则时间轴规则兜底。"
                        "未安装可运行 scripts\\install_scenedetect.bat。",
            "演讲金句": "优先 Vosk 转写 + 金句词/LLM；无模型则用人声段候选。"
                        "完整识别请运行 scripts\\download_vosk_model.bat。",
            "日常精彩片段": "同演讲链路，偏向口语兴奋词；无 Vosk 用人声段。",
            "响度高潮": "FFmpeg ebur128 瞬时响度峰值找高潮；敏感度控制阈值，无需 Vosk。",
            "自定义识别": "通用转写/人声切段，可自行再手动增删。",
        }
        self._scene_hint.setText(tips.get(scene, ""))

    @Slot()
    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频",
            "", "视频文件 (*.mp4 *.mov *.avi *.flv *.mkv);;所有文件 (*.*)"
        )
        if path:
            self._vm.import_video(path)

    @Slot()
    def _on_use_current_video(self):
        video = self._vm.get_app_state().current_video
        if not video or not video.file_path:
            QMessageBox.information(self, "提示", "尚未导入视频，请先在本页或其它功能页导入。")
            return
        self._on_video_loaded(video)

    @Slot(object)
    def _on_video_loaded(self, video):
        name = os.path.basename(video.file_path)
        self._file_label.setText(name)
        self._duration_sec = float(video.duration_sec or 0.0)
        self._info_label.setText(
            f"分辨率: {video.width}x{video.height} | "
            f"时长: {format_timestamp(self._duration_sec)} ({self._duration_sec:.1f}s) | "
            f"帧率: {video.fps:.1f}fps | "
            f"编码: {video.codec_name}"
        )
        self._timeline.set_duration(self._duration_sec)
        # 换片时同步清空 VM 与 UI 片段
        self._vm.clear_highlights()
        self._last_result_path = ""
        # 手动切片起止范围随时长调整
        max_sec = max(1.0, self._duration_sec)
        for spin in (self._manual_start, self._manual_end):
            spin.blockSignals(True)
            spin.setMaximum(max_sec)
            spin.blockSignals(False)
        self._manual_start.setValue(0.0)
        default_end = min(10.0, max_sec)
        self._manual_end.setValue(default_end)
        self._on_manual_spin()

    @Slot()
    def _on_analyze(self):
        self._vm.update_slice_params(
            self._scene_combo.currentText(),
            self._min_slider.value(),
            self._max_slider.value(),
            self._sens_slider.value() / 100.0,
        )
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._thumb_gen += 1
        self._highlight_list.clear()
        self._timeline.clear()
        self._timeline.set_duration(self._duration_sec)
        self._btn_analyze.setEnabled(False)
        self._btn_analyze.setText("分析中…")
        self._vm.start_slice_analysis()

    @Slot(int, float, str)
    def _on_progress(self, task_id, progress, message):
        self._progress.setVisible(True)
        self._progress.setValue(int(progress))

    @Slot(list)
    def _on_highlights(self, segments):
        self._btn_analyze.setEnabled(True)
        self._btn_analyze.setText("AI 智能分析")
        if self._progress.isVisible():
            self._progress.setValue(100)
        # 若视频信息尚未写入时长，用片段末尾兜底
        if self._duration_sec <= 0 and segments:
            self._duration_sec = max(float(s.end_sec) for s in segments)
            self._timeline.set_duration(self._duration_sec)
        self._timeline.set_segments(segments)
        self._highlight_list.clear()
        for i, seg in enumerate(segments):
            dur = max(0.0, float(seg.end_sec) - float(seg.start_sec))
            tag = "手动" if abs(float(seg.score) - 1.0) < 1e-6 else f"得分 {seg.score:.2f}"
            text = (
                f"#{i + 1}  {format_range(seg.start_sec, seg.end_sec)}  ·  "
                f"{format_timestamp(dur)}  ·  {tag}"
            )
            item = QListWidgetItem(text)
            path = getattr(seg, "thumbnail_path", "") or ""
            if path and os.path.isfile(path):
                item.setIcon(QIcon(QPixmap(path)))
            self._highlight_list.addItem(item)
        self._start_thumbnail_load(segments)

    def _start_thumbnail_load(self, segments) -> None:
        """后台抽取各片段中点缩略图 → 时间轴 / 列表图标。"""
        video = self._vm.get_app_state().current_video
        bridge = getattr(self._vm, "_bridge", None)
        if not video or not bridge or not segments:
            return
        self._thumb_gen += 1
        gen = self._thumb_gen
        path = video.file_path
        jobs = []
        for i, seg in enumerate(segments):
            mid = (float(seg.start_sec) + float(seg.end_sec)) * 0.5
            jobs.append((i, mid))

        def worker():
            for index, mid in jobs:
                if gen != self._thumb_gen:
                    return
                try:
                    out = bridge.extract_thumbnail(path, mid, max_width=160)
                except Exception:
                    out = ""
                if gen != self._thumb_gen:
                    return
                if out:
                    segs = self._vm.get_app_state().highlight_segments
                    if 0 <= index < len(segs):
                        segs[index].thumbnail_path = out
                    self.thumbnailReady.emit(gen, index, out)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(int, int, str)
    def _on_thumbnail_ready(self, gen: int, index: int, path: str):
        if gen != self._thumb_gen or not path:
            return
        self._timeline.set_thumbnail_at(index, path)
        if 0 <= index < self._highlight_list.count():
            item = self._highlight_list.item(index)
            pix = QPixmap(path)
            if item and not pix.isNull():
                item.setIcon(QIcon(pix))

    @Slot()
    def _on_manual_spin(self):
        a = float(self._manual_start.value())
        b = float(self._manual_end.value())
        self._manual_range_label.setText(format_range(a, b))

    @Slot()
    def _on_add_manual(self):
        video = self._vm.get_app_state().current_video
        if not video:
            QMessageBox.warning(self, "提示", "请先导入视频")
            return
        start = float(self._manual_start.value())
        end = float(self._manual_end.value())
        if not self._vm.add_manual_highlight(start, end):
            QMessageBox.warning(
                self, "手动切片",
                self._vm.status_message or "添加失败，请检查起止时间",
            )

    @Slot()
    def _on_remove_selected(self):
        row = self._highlight_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先在列表中选中一段")
            return
        self._vm.remove_highlight_at(row)

    @Slot()
    def _on_clear_segments(self):
        if not self._vm.get_app_state().highlight_segments:
            return
        if QMessageBox.question(self, "清空列表", "确定清空全部片段？") != QMessageBox.Yes:
            return
        self._vm.clear_highlights()

    @Slot(int)
    def _on_timeline_segment(self, index: int):
        if index < 0 or index >= self._highlight_list.count():
            return
        self._syncing_selection = True
        self._highlight_list.setCurrentRow(index)
        self._syncing_selection = False

    @Slot(int)
    def _on_list_row_changed(self, row: int):
        if self._syncing_selection:
            return
        self._timeline.set_selected_index(row)

    @Slot()
    def _on_export(self):
        if not self._vm.get_app_state().highlight_segments:
            QMessageBox.warning(self, "提示", "请先添加片段（AI 分析或手动切片）")
            return
        opts_dlg = ExportOptionsDialog(self, title="高光成片导出参数")
        if opts_dlg.exec() != QDialog.Accepted:
            return
        opts = opts_dlg.options()
        out_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not out_dir:
            return
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._vm.export_highlights(
            out_dir,
            concat=True,
            max_height=opts.max_height,
            quality=opts.quality,
            container=opts.container,
        )

    @Slot()
    def _on_vertical_export(self):
        video = self._vm.get_app_state().current_video
        if not video:
            QMessageBox.warning(self, "提示", "请先导入视频")
            return
        segs = [
            s for s in self._vm.get_app_state().highlight_segments
            if s.selected and s.end_sec > s.start_sec
        ]
        use_hl = bool(segs)
        if not use_hl:
            tip = (
                "当前没有高光片段。\n"
                "将对整段视频做 9:16 竖屏裁切。\n\n继续？"
            )
            if QMessageBox.question(self, "竖屏短视频", tip) != QMessageBox.Yes:
                return

        # 裁切位置
        bias_box = QMessageBox(self)
        bias_box.setWindowTitle("竖屏裁切位置")
        bias_box.setText(
            "选择画面裁切锚点（横屏素材变 9:16 时保留哪一侧）："
            + ("\n将先拼接高光成片再竖屏导出。" if use_hl else "")
            + "\n口播建议用「智能跟脸」。"
        )
        btn_face = bias_box.addButton("智能跟脸", QMessageBox.AcceptRole)
        btn_c = bias_box.addButton("居中", QMessageBox.AcceptRole)
        btn_t = bias_box.addButton("偏上", QMessageBox.AcceptRole)
        btn_b = bias_box.addButton("偏下", QMessageBox.AcceptRole)
        bias_box.addButton("取消", QMessageBox.RejectRole)
        bias_box.exec()
        clicked = bias_box.clickedButton()
        if clicked is None or clicked not in (btn_face, btn_c, btn_t, btn_b):
            return
        track_mode = "fixed"
        if clicked is btn_face:
            track_mode = "face"
            bias = "center"
        elif clicked is btn_t:
            bias = "top"
        elif clicked is btn_b:
            bias = "bottom"
        else:
            bias = "center"

        opts_dlg = ExportOptionsDialog(self, title="竖屏导出参数")
        if opts_dlg.exec() != QDialog.Accepted:
            return
        opts = opts_dlg.options()
        vw, vh = opts.vertical_size

        base = os.path.splitext(os.path.basename(video.file_path))[0]
        default = f"{base}_vertical.{opts.container}"
        filt = "MP4 (*.mp4);;MOV (*.mov);;所有文件 (*.*)"
        out, _ = QFileDialog.getSaveFileName(
            self, "保存竖屏短视频", default, filt,
        )
        if not out:
            return
        # 后缀与容器对齐
        root, ext = os.path.splitext(out)
        if ext.lower().lstrip(".") != opts.container:
            out = f"{root}.{opts.container}"
        self._pending_publish = opts
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._vm.export_vertical_short(
            out,
            crop_bias=bias,
            track_mode=track_mode,
            use_highlights=use_hl,
            width=vw,
            height=vh,
            quality=opts.quality,
        )

    @Slot()
    def _on_compact_speech(self):
        video = self._vm.get_app_state().current_video
        if not video:
            QMessageBox.warning(self, "提示", "请先导入视频")
            return
        base = os.path.splitext(os.path.basename(video.file_path))[0]
        default = f"{base}_compact.mp4"
        out, _ = QFileDialog.getSaveFileName(
            self, "保存紧凑口播", default,
            "MP4 (*.mp4);;所有文件 (*.*)",
        )
        if not out:
            return
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._vm.compact_speech(out)

    def _handoff_path(self) -> str:
        """优先最近导出结果，否则当前共享视频。"""
        if self._last_result_path and os.path.isfile(self._last_result_path):
            return self._last_result_path
        video = self._vm.get_app_state().current_video
        if video and video.file_path and os.path.isfile(video.file_path):
            return video.file_path
        return ""

    def _send_to(self, tab_index: int):
        if not self._handoff:
            return
        path = self._handoff_path()
        if not path:
            QMessageBox.warning(
                self, "提示",
                "请先导入视频，或先「一键高光成片 / 静音剪掉」得到成片后再送去处理。",
            )
            return
        if not self._last_result_path or not os.path.isfile(self._last_result_path):
            tip = "将把当前完整视频送去下一功能。\n若只要高光，请先「一键高光成片」。\n\n继续？"
            if QMessageBox.question(self, "功能串联", tip) != QMessageBox.Yes:
                return
        self._handoff(path, tab_index)

    @Slot(str)
    def _on_export_done(self, path: str):
        self._progress.setValue(100)
        self._last_result_path = path or ""
        tab = ask_video_handoff(
            self,
            "导出完成",
            f"高光成片已生成：\n{path}\n\n同目录还有各片段 highlight_XXX.mp4\n\n"
            "可直接送去画质增强或去水印（无需重新导入）。",
            [("送去超分", TAB_ENHANCE), ("送去去水印", TAB_WATERMARK)],
        )
        if tab is not None and self._handoff:
            self._handoff(path, tab)

    @Slot(str)
    def _on_silence_done(self, path: str):
        self._progress.setValue(100)
        self._last_result_path = path or ""
        tab = ask_video_handoff(
            self,
            "完成",
            f"紧凑口播已保存：\n{path}\n\n可继续送去超分或去水印。",
            [("送去超分", TAB_ENHANCE), ("送去去水印", TAB_WATERMARK)],
        )
        if tab is not None and self._handoff:
            self._handoff(path, tab)

    @Slot(str)
    def _on_vertical_done(self, path: str):
        self._progress.setValue(100)
        self._last_result_path = path or ""
        extra = ""
        opts = getattr(self, "_pending_publish", None)
        self._pending_publish = None
        if path and opts and (getattr(opts, "make_cover", False) or getattr(opts, "make_topic_draft", False)):
            try:
                from core.publish_pack import make_publish_pack, write_topic_draft
                cover = draft = ""
                if opts.make_cover and self._vm.bridge:
                    cover, draft = make_publish_pack(
                        self._vm.bridge, path,
                        width=opts.vertical_size[0], height=opts.vertical_size[1],
                    )
                elif opts.make_topic_draft:
                    draft = write_topic_draft(path)
                bits = []
                if cover:
                    bits.append(f"封面：{os.path.basename(cover)}")
                if draft:
                    bits.append(f"话题草稿：{os.path.basename(draft)}")
                if bits:
                    extra = "\n" + " · ".join(bits)
            except Exception as e:
                extra = f"\n（发布包生成失败：{e}）"
        tab = ask_video_handoff(
            self,
            "竖屏短视频完成",
            f"9:16 成片已保存：\n{path}{extra}\n\n"
            "可继续送去超分或去水印。",
            [("送去超分", TAB_ENHANCE), ("送去去水印", TAB_WATERMARK)],
        )
        if tab is not None and self._handoff:
            self._handoff(path, tab)

    @Slot(str)
    def _show_error(self, msg):
        self._btn_analyze.setEnabled(True)
        self._btn_analyze.setText("AI 智能分析")
        self._progress.setVisible(False)
        QMessageBox.critical(self, "错误", msg)


class PlaceholderPage(QWidget):
    """个人中心等占位页"""

    def __init__(self, title: str, desc: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        lbl = QLabel(title)
        lbl.setObjectName("HomeTitle")
        desc_lbl = QLabel(desc)
        desc_lbl.setObjectName("HomeSubtitle")
        desc_lbl.setWordWrap(True)
        layout.addWidget(lbl)
        layout.addWidget(desc_lbl)
        layout.addStretch()


class MainWindow(QMainWindow):
    # WeatherInfo | None（失败时为 None）
    weatherUpdated = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MusicEditing · 本地音视频工作室")
        self.setMinimumSize(1024, 720)
        self.setStyleSheet(app_stylesheet())

        self._vm = MainViewModel()
        self._weather_mood = None
        self._weather_mood_hinted = False
        self._weather_pulse_timer: QTimer | None = None
        self._weather_pulse_n = 0
        self._weather_base_qss = ""
        self._setup_wizard_shown = False
        self._weather_default_qss = (
            "QLabel#ChromeWeather {"
            " background: #2A4A48; color: #B8EDE4; border: 1px solid #3A6A64;"
            " border-radius: 999px; padding: 4px 12px; font-size: 12px;"
            " }"
        )

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(14, 12, 14, 10)
        main_layout.setSpacing(10)

        # 顶部状态栏（胶囊条）
        chrome = QFrame()
        chrome.setObjectName("TopChrome")
        status_bar = QHBoxLayout(chrome)
        status_bar.setContentsMargins(14, 8, 14, 8)
        status_bar.setSpacing(8)

        brand = QLabel("MusicEditing")
        brand.setObjectName("ChromeBrand")
        self._gpu_label = QLabel()
        self._gpu_label.setObjectName("ChromePill")
        self._auth_label = QLabel()
        self._auth_label.setObjectName("ChromePill")
        self._weather_label = QLabel("天气: …")
        self._weather_label.setObjectName("ChromeWeather")
        self._weather_label.setToolTip("按本机公网 IP 定位本地城市，经 Open-Meteo 显示天气")
        self._weather_label.installEventFilter(self)
        self._version_label = QLabel(f"v{self._vm.version}")
        self._version_label.setObjectName("ChromeVersion")

        self._page_label = QLabel(PAGE_TITLES[TAB_HOME])
        self._page_label.setObjectName("ChromePage")
        self._page_label.setToolTip("当前功能页（由菜单切换）")

        status_bar.addWidget(brand)
        status_bar.addSpacing(8)
        status_bar.addWidget(self._page_label)
        status_bar.addWidget(self._gpu_label)
        status_bar.addWidget(self._auth_label)
        status_bar.addWidget(self._weather_label)
        status_bar.addStretch()
        status_bar.addWidget(self._version_label)
        main_layout.addWidget(chrome)

        self._vm.gpuNameChanged.connect(lambda n: self._gpu_label.setText(f"GPU  {n}"))
        self._vm.authTypeChanged.connect(lambda a: self._auth_label.setText(f"授权  {a}"))
        self.weatherUpdated.connect(self._on_weather_updated)
        self._gpu_label.setText(f"GPU  {self._vm.gpu_name}")
        self._auth_label.setText(f"授权  {self._vm.auth_type}")

        # 功能页：堆叠容器 + 菜单导航（不再平铺大量 Tab）
        self._stack = QStackedWidget()
        self._stack.setObjectName("MainStack")
        self._home_page = HomePage(self._vm)
        self._slice_page = SlicePage(self._vm, handoff=self.open_with_video)
        self._enhance_page = EnhancePage(self._vm, handoff=self.open_with_video)
        self._watermark_page = WatermarkPage(self._vm, handoff=self.open_with_video)
        self._download_page = DownloadPage(self._vm)
        self._pipeline_page = PipelineQueuePage(self._vm)
        self._cover_page = CoverPage(self._vm)
        self._audio_fun_page = AudioFunPage(self._vm)
        self._bgm_page = BgmPage(self._vm)
        self._profile_page = ProfilePage(self._vm)
        self._library_page = MediaLibraryPage(self._vm, handoff=self.open_with_video)
        self._stego_page = StegoPage(self._vm)
        for page in (
            self._home_page,
            self._slice_page,
            self._enhance_page,
            self._watermark_page,
            self._download_page,
            self._pipeline_page,
            self._cover_page,
            self._audio_fun_page,
            self._bgm_page,
            self._profile_page,
            self._library_page,
            self._stego_page,
        ):
            self._stack.addWidget(page)
        main_layout.addWidget(self._stack, 1)

        self._nav_group = QActionGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_actions: dict[int, QAction] = {}
        self._build_menus()
        self._goto_page(TAB_HOME)

        self._download_page.previewPlayRequested.connect(self._on_preview_play)
        self._download_page.playWithCommentsRequested.connect(self._on_play_with_comments)

        # 底部状态
        self._status_label = QLabel(self._vm.status_message)
        self._status_label.setObjectName("FooterStatus")
        self._vm.statusMessageChanged.connect(self._status_label.setText)
        main_layout.addWidget(self._status_label)

        # 天气刷新依赖底栏提示，放在 status_label 之后
        self._start_weather_refresh()

        # GPU 提示（向导未弹出时再提示）
        from core.app_logic import AppLogic
        from core.setup_status import should_show_setup_wizard
        app = AppLogic()
        QTimer.singleShot(400, lambda: self._maybe_show_setup_wizard(app))
        if not should_show_setup_wizard(app) and not app.gpu_info["cuda_available"]:
            QMessageBox.information(
                self, "硬件提示",
                "当前为 CPU 模式，处理速度较慢。\n支持 NVIDIA 显卡硬件加速（CUDA）。"
            )

    def _maybe_show_setup_wizard(self, app=None):
        if self._setup_wizard_shown:
            return
        from core.setup_status import should_show_setup_wizard
        if not should_show_setup_wizard(app):
            return
        self._setup_wizard_shown = True
        dlg = SetupWizardDialog(self._vm, self)
        dlg.exec()

    def open_setup_wizard(self):
        dlg = SetupWizardDialog(self._vm, self)
        dlg.exec()

    def navigate_to(self, name: str):
        """向导 / 首页卡片用字符串导航。"""
        key = (name or "").strip().lower()
        mapping = {
            "home": TAB_HOME,
            "slice": TAB_SLICE,
            "enhance": TAB_ENHANCE,
            "watermark": TAB_WATERMARK,
            "download": TAB_DOWNLOAD,
            "pipeline": TAB_PIPELINE,
            "profile": TAB_PROFILE,
            "library": TAB_LIBRARY,
            "cover": TAB_COVER,
            "stego": TAB_STEGO,
        }
        idx = mapping.get(key)
        if idx is None:
            return
        if key == "pipeline" and getattr(self, "_pending_library_path", ""):
            path = self._pending_library_path
            self._pending_library_path = ""
            self._goto_page(TAB_PIPELINE)
            self._pipeline_page.enqueue_paths([path])
            return
        self._goto_page(idx)

    def _start_weather_refresh(self):
        """后台拉取天气，不阻塞 UI；每 30 分钟刷新。"""
        self._weather_timer = QTimer(self)
        self._weather_timer.setInterval(30 * 60 * 1000)
        self._weather_timer.timeout.connect(self._refresh_weather)
        self._weather_timer.start()
        self._refresh_weather()

    def _refresh_weather(self):
        def worker():
            info = None
            try:
                from core.weather_service import fetch_local_weather
                info = fetch_local_weather(timeout=5.0)
            except Exception:
                info = None
            self.weatherUpdated.emit(info)

        threading.Thread(target=worker, daemon=True).start()

    @Slot(object)
    def _on_weather_updated(self, info):
        from core.weather_service import (
            format_status_error,
            format_status_text,
            mood_pill_stylesheet,
            recommend_mood,
        )

        if info is None:
            self._weather_mood = None
            self._stop_weather_pulse()
            self._weather_label.setStyleSheet(self._weather_default_qss)
            self._weather_label.setText(format_status_error())
            self._weather_label.setToolTip("天气暂不可用（网络或定位失败）")
            self._weather_label.setCursor(Qt.ArrowCursor)
            return

        mood = recommend_mood(info.weather_code)
        self._weather_mood = mood
        self._weather_label.setText(format_status_text(info))
        if mood:
            self._weather_base_qss = mood_pill_stylesheet(mood.accent)
            self._weather_label.setStyleSheet(self._weather_base_qss)
            tip = (
                f"{info.city} · {info.weather_text} {info.temperature_c:.0f}°C\n"
                f"今日氛围：{mood.label}（{mood.reason}）\n"
                f"{mood.cta or '点击套用到首页播放器'}"
            )
            self._weather_label.setToolTip(tip)
            self._weather_label.setCursor(Qt.PointingHandCursor)
            self._start_weather_pulse()
            if not self._weather_mood_hinted:
                self._weather_mood_hinted = True
                self._status_label.setText(
                    f"今日氛围 · {mood.glyph} {mood.label}：{mood.reason}。"
                    f"点击顶栏天气胶囊即可套用"
                )
        else:
            self._stop_weather_pulse()
            self._weather_label.setStyleSheet(self._weather_default_qss)
            self._weather_label.setToolTip(
                f"{info.city} · {info.weather_text} {info.temperature_c:.0f}°C\n"
                "按本机公网 IP 定位，经 Open-Meteo 显示天气"
            )
            self._weather_label.setCursor(Qt.ArrowCursor)

    def _start_weather_pulse(self):
        """胶囊边框闪两下，提示「可点」。"""
        self._stop_weather_pulse()
        self._weather_pulse_n = 0
        self._weather_pulse_timer = QTimer(self)
        self._weather_pulse_timer.setInterval(380)
        self._weather_pulse_timer.timeout.connect(self._on_weather_pulse_tick)
        self._weather_pulse_timer.start()

    def _stop_weather_pulse(self):
        if self._weather_pulse_timer is not None:
            self._weather_pulse_timer.stop()
            self._weather_pulse_timer.deleteLater()
            self._weather_pulse_timer = None
        if self._weather_mood is not None and self._weather_base_qss:
            self._weather_label.setStyleSheet(self._weather_base_qss)

    def _on_weather_pulse_tick(self):
        self._weather_pulse_n += 1
        if self._weather_pulse_n > 6:
            self._stop_weather_pulse()
            return
        # 奇偶切换：加亮边框
        if self._weather_pulse_n % 2 == 1:
            self._weather_label.setStyleSheet(
                self._weather_base_qss.replace(
                    "border: 1px solid",
                    "border: 2px solid",
                )
            )
        else:
            self._weather_label.setStyleSheet(self._weather_base_qss)

    def _on_weather_clicked(self):
        mood = self._weather_mood
        if mood is None:
            return
        self._stop_weather_pulse()
        self._goto_page(TAB_HOME)
        ok = self._home_page.apply_opencv_filter(mood.filter_mode)
        if ok:
            self._status_label.setText(
                f"今日氛围 · 已套用「{mood.glyph} {mood.label}」"
                f"（{mood.reason}）。首页滤镜下拉可改回"
            )
            # 短暂加亮胶囊，表示已生效
            if self._weather_base_qss:
                self._weather_label.setStyleSheet(
                    self._weather_base_qss.replace("font-weight: 600", "font-weight: 700")
                )
        else:
            self._status_label.setText(
                f"今日氛围 · 无法应用「{mood.label}」"
                f"（请先在首页打开一段视频，再点天气胶囊）"
            )

    def _build_menus(self):
        """菜单栏导航：文件 / 核心 / 工作流 / 趣味 / 帮助。"""
        bar = self.menuBar()
        bar.setNativeMenuBar(False)

        file_menu = bar.addMenu("文件(&F)")
        act_open = QAction("打开媒体到首页…", self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self._on_menu_open_media)
        file_menu.addAction(act_open)
        file_menu.addSeparator()
        act_quit = QAction("退出", self)
        act_quit.setShortcut(QKeySequence("Ctrl+Q"))
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        help_menu = None
        for menu_title, items in MENU_GROUPS:
            menu = bar.addMenu(menu_title)
            if menu_title == "帮助":
                help_menu = menu
            for label, page_index in items:
                act = QAction(label, self)
                act.setCheckable(True)
                act.setData(page_index)
                if label == "热评弹幕":
                    act.triggered.connect(self._goto_hot_comments_tab)
                else:
                    act.triggered.connect(
                        lambda _checked=False, idx=page_index: self._goto_page(idx)
                    )
                self._nav_group.addAction(act)
                # 同页多入口时保留先注册的（工作流「下载与热评」）
                if page_index not in self._nav_actions:
                    self._nav_actions[page_index] = act
                menu.addAction(act)

        if help_menu is not None:
            help_menu.addSeparator()
            act_about = QAction("关于 MusicEditing", self)
            act_about.triggered.connect(self._on_about)
            help_menu.addAction(act_about)

    def _goto_page(self, index: int):
        """切换功能页（菜单 / 接力 / 下载完成共用）。"""
        if index < 0 or index >= self._stack.count():
            return
        self._stack.setCurrentIndex(index)
        title = PAGE_TITLES.get(index, f"页面 {index}")
        self._page_label.setText(title)
        act = self._nav_actions.get(index)
        if act is not None and not act.isChecked():
            act.setChecked(True)
        self.setWindowTitle(f"MusicEditing · {title}")

    @Slot()
    def _goto_hot_comments_tab(self):
        """趣味菜单：进入下载与热评页并滚到评论结果区。"""
        self._goto_page(TAB_DOWNLOAD)
        self._download_page.focus_comments()

    @Slot()
    def _on_menu_open_media(self):
        self._goto_page(TAB_HOME)
        self._home_page.prompt_open_media()

    @Slot()
    def _on_about(self):
        QMessageBox.about(
            self,
            "关于 MusicEditing",
            f"MusicEditing {self._vm.version}\n"
            "本地音视频打开 · 预览 · 切片 · 增强 · 去水印\n\n"
            "功能入口在顶部菜单：核心 / 工作流 / 趣味 / 帮助。",
        )

    def eventFilter(self, obj, event):
        if obj is self._weather_label and event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.LeftButton:
                self._on_weather_clicked()
                return True
        return super().eventFilter(obj, event)

    def open_with_video(self, path: str, tab_index: int) -> None:
        """切功能页 + 异步 import_video（probe 在后台，不卡主线程）。"""
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "提示", f"文件不存在：\n{path}")
            return
        # 先切页，再后台探测；videoLoaded 到达后各页刷新
        self._goto_page(tab_index)
        if tab_index == TAB_ENHANCE:
            self._enhance_page.focus_video_tab()
        elif tab_index == TAB_WATERMARK:
            self._watermark_page.focus_video_tab()
        elif tab_index == TAB_COVER:
            self._cover_page.set_video(path)
        elif tab_index == TAB_AUDIO_FUN:
            self._audio_fun_page.set_media(path)
        self._vm.import_video(path)

    @Slot(str)
    def _on_preview_play(self, path: str):
        """列表试听：打开并自动播放（无热评）。"""
        if not path or not os.path.isfile(path):
            return
        self._home_page.play_with_comments(path, [], auto_play=True)
        self._goto_page(TAB_HOME)

    @Slot(str, object)
    def _on_play_with_comments(self, path: str, comments):
        """「送首页播放」：打开媒体并叠弹幕（评论可为空）。"""
        if not path or not os.path.isfile(path):
            return
        self._home_page.play_with_comments(path, comments, auto_play=True)
        self._goto_page(TAB_HOME)
        n = len(comments) if comments else 0
        if n:
            self._status_label.setText(f"首页播放 · 已叠加 {n} 条热评弹幕")
        else:
            self._status_label.setText("首页播放")

    def shutdown(self):
        """退出前释放播放器与子进程"""
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        self._home_page.shutdown_player()
        if getattr(self, "_download_page", None):
            self._download_page.shutdown()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)


def run_app():
    import sys
    from ui.theme import app_stylesheet, apply_dark_palette

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_dark_palette(app)
    # 应用到 QApplication，下拉弹出层也能吃到深色 QSS（避免白边）
    app.setStyleSheet(app_stylesheet())
    app.setQuitOnLastWindowClosed(True)
    win = MainWindow()
    app.aboutToQuit.connect(win.shutdown)
    win.show()
    sys.exit(app.exec())
