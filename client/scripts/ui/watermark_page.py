"""去水印页面：图片 / 视频"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot, QObject
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QSlider, QTabWidget,
    QVBoxLayout, QWidget,
)

from core.image_loader import load_preview
from ui.exif_panel import ExifPanel, attach_exif_overlay
from ui.region_selector import RegionSelectorWidget
from ui.workflow_link import TAB_ENHANCE, ask_video_handoff
from viewmodels.main_vm import MainViewModel


class _FramePreviewWorker(QObject):
    finished = Signal(str, float)
    failed = Signal(str)

    def __init__(self, bridge, video_path: str, t: float, out_png: str):
        super().__init__()
        self._bridge = bridge
        self._video_path = video_path
        self._t = t
        self._out_png = out_png

    @Slot()
    def run(self):
        try:
            self._bridge.extract_video_frame(self._video_path, self._t, self._out_png)
            self.finished.emit(self._out_png, self._t)
        except Exception as e:
            self.failed.emit(str(e))


class WatermarkPage(QWidget):
    def __init__(self, vm: MainViewModel, handoff=None, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._handoff = handoff
        self._preview_png: str = ""
        self._last_result_path: str = ""
        self._preview_thread: QThread | None = None
        self._preview_debounce = QTimer(self)
        self._preview_debounce.setSingleShot(True)
        self._preview_debounce.setInterval(280)
        self._preview_debounce.timeout.connect(self._refresh_video_preview)

        root = QVBoxLayout(self)

        hint = QLabel(
            "在预览图上拖拽框选水印区域，可框选多个。"
            "视频默认「快速」(OpenCV，秒级)；图片/精修用 LaMa（需 models/lama.onnx）。"
            "同一段视频只启动一次 media_cli，帧间复用后端。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("MutedText")
        root.addWidget(hint)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_image_tab(), "图片去水印")
        self._tabs.addTab(self._build_video_tab(), "视频去水印")
        root.addWidget(self._tabs, 1)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setObjectName("InfoText")
        root.addWidget(self._status)

        vm.watermarkProgress.connect(self._on_progress)
        vm.watermarkFinished.connect(self._on_finished)
        vm.errorOccurred.connect(self._show_error)
        vm.videoLoaded.connect(self._on_video_loaded)

    def _build_image_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        row = QHBoxLayout()
        self._img_path_label = QLabel("未选择图片")
        btn_import = QPushButton("导入图片")
        btn_import.clicked.connect(self._on_import_image)
        row.addWidget(self._img_path_label, 1)
        row.addWidget(btn_import)
        layout.addLayout(row)

        self._img_selector = RegionSelectorWidget()
        self._img_exif = ExifPanel(lambda: self._vm.bridge)
        layout.addWidget(attach_exif_overlay(self._img_selector, self._img_exif), 1)

        side = QHBoxLayout()
        self._img_region_list = QListWidget()
        self._img_region_list.setMaximumWidth(220)
        side.addWidget(self._img_region_list)

        mode_box = QGroupBox("质量模式")
        mode_row = QHBoxLayout(mode_box)
        self._img_mode_fast = QRadioButton("快速 (OpenCV)")
        self._img_mode_lama = QRadioButton("精修 (LaMa)")
        self._img_mode_lama.setChecked(True)
        self._img_mode_group = QButtonGroup(self)
        self._img_mode_group.addButton(self._img_mode_fast)
        self._img_mode_group.addButton(self._img_mode_lama)
        mode_row.addWidget(self._img_mode_fast)
        mode_row.addWidget(self._img_mode_lama)
        side.addWidget(mode_box)

        btn_col = QVBoxLayout()
        btn_clear = QPushButton("清除区域")
        btn_clear.clicked.connect(self._img_selector.clear_regions)
        btn_run = QPushButton("开始去水印")
        btn_run.setObjectName("primaryButton")
        btn_run.clicked.connect(self._on_run_image)
        btn_col.addWidget(btn_clear)
        btn_col.addWidget(btn_run)
        btn_col.addStretch()
        side.addLayout(btn_col)
        layout.addLayout(side)

        self._img_selector.regionsChanged.connect(self._sync_image_region_list)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        return page

    def _build_video_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        row = QHBoxLayout()
        self._vid_path_label = QLabel("未选择视频")
        btn_import = QPushButton("导入视频")
        btn_import.clicked.connect(self._on_import_video)
        btn_use = QPushButton("用当前视频")
        btn_use.setToolTip("使用其它页已导入的共享视频（无需重新选择文件）")
        btn_use.clicked.connect(self._on_use_current_video)
        row.addWidget(self._vid_path_label, 1)
        row.addWidget(btn_import)
        row.addWidget(btn_use)
        layout.addLayout(row)

        self._vid_info = QLabel("")
        self._vid_info.setObjectName("InfoText")
        layout.addWidget(self._vid_info)

        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("预览时刻:"))
        self._preview_slider = QSlider(Qt.Horizontal)
        self._preview_slider.setRange(0, 1000)
        self._preview_slider.valueChanged.connect(self._on_preview_time_changed)
        self._preview_time_label = QLabel("0.0s")
        btn_refresh = QPushButton("刷新预览帧")
        btn_refresh.clicked.connect(self._refresh_video_preview)
        preview_row.addWidget(self._preview_slider, 1)
        preview_row.addWidget(self._preview_time_label)
        preview_row.addWidget(btn_refresh)
        layout.addLayout(preview_row)

        self._vid_selector = RegionSelectorWidget()
        layout.addWidget(self._vid_selector, 1)

        range_box = QGroupBox("处理时间段（固定位置水印适用）")
        range_layout = QHBoxLayout(range_box)
        range_layout.addWidget(QLabel("起始"))
        self._start_slider = QSlider(Qt.Horizontal)
        self._start_slider.setRange(0, 1000)
        self._start_label = QLabel("0.0s")
        range_layout.addWidget(self._start_slider, 1)
        range_layout.addWidget(self._start_label)
        range_layout.addWidget(QLabel("结束"))
        self._end_slider = QSlider(Qt.Horizontal)
        self._end_slider.setRange(0, 1000)
        self._end_slider.setValue(1000)
        self._end_label = QLabel("全程")
        range_layout.addWidget(self._end_slider, 1)
        range_layout.addWidget(self._end_label)
        self._start_slider.valueChanged.connect(self._on_range_changed)
        self._end_slider.valueChanged.connect(self._on_range_changed)
        layout.addWidget(range_box)

        mode_box = QGroupBox("质量模式")
        mode_row = QHBoxLayout(mode_box)
        self._vid_mode_fast = QRadioButton("快速 (OpenCV，推荐视频)")
        self._vid_mode_lama = QRadioButton("精修 (LaMa，较慢)")
        self._vid_mode_fast.setChecked(True)
        self._vid_mode_group = QButtonGroup(self)
        self._vid_mode_group.addButton(self._vid_mode_fast)
        self._vid_mode_group.addButton(self._vid_mode_lama)
        mode_row.addWidget(self._vid_mode_fast)
        mode_row.addWidget(self._vid_mode_lama)
        layout.addWidget(mode_box)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("清除区域")
        btn_clear.clicked.connect(self._vid_selector.clear_regions)
        btn_run = QPushButton("开始视频去水印")
        btn_run.setObjectName("primaryButton")
        btn_run.clicked.connect(self._on_run_video)
        self._btn_send_enhance = QPushButton("送去超分")
        self._btn_send_enhance.setEnabled(False)
        self._btn_send_enhance.setToolTip("将去水印结果导入「画质增强」")
        self._btn_send_enhance.clicked.connect(self._on_send_to_enhance)
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_run)
        btn_row.addWidget(self._btn_send_enhance)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._vid_region_list = QListWidget()
        self._vid_region_list.setMaximumHeight(80)
        layout.addWidget(self._vid_region_list)
        self._vid_selector.regionsChanged.connect(self._sync_video_region_list)
        return page

    @Slot(int)
    def _on_tab_changed(self, index: int):
        if index == 1:
            video = self._vm.get_app_state().current_video
            if video:
                self._apply_video_meta(video)

    @Slot(list)
    def _sync_image_region_list(self, regions):
        self._img_region_list.clear()
        for i, r in enumerate(regions):
            self._img_region_list.addItem(f"区域{i + 1}: x={r.x} y={r.y} w={r.w} h={r.h}")

    @Slot(list)
    def _sync_video_region_list(self, regions):
        self._vid_region_list.clear()
        for i, r in enumerate(regions):
            self._vid_region_list.addItem(f"区域{i + 1}: x={r.x} y={r.y} w={r.w} h={r.h}")

    @Slot()
    def _on_import_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)",
        )
        if not path:
            return
        preview = load_preview(path, max_side=4096)
        if not preview.ok:
            QMessageBox.warning(self, "提示", "无法加载图片")
            return
        self._vm.import_image(path)
        self._img_path_label.setText(os.path.basename(path))
        self._img_selector.load_pixmap(preview.pixmap, preview.native_size)
        self._img_exif.load_path(path)
        self._status.setText(
            f"已加载图片: {path}  ·  {preview.native_width}×{preview.native_height}"
            f"  ·  解码 {preview.backend}"
        )

    def focus_video_tab(self) -> None:
        self._tabs.setCurrentIndex(1)

    @Slot()
    def _on_import_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频", "",
            "视频 (*.mp4 *.mov *.avi *.mkv *.flv);;所有文件 (*.*)",
        )
        if path:
            self._vm.import_video(path)

    @Slot()
    def _on_use_current_video(self):
        video = self._vm.get_app_state().current_video
        if not video or not video.file_path:
            QMessageBox.information(self, "提示", "尚未导入视频，请先在本页或其它功能页导入。")
            return
        self.focus_video_tab()
        self._on_video_loaded(video)
        self._status.setText(f"已使用当前视频: {os.path.basename(video.file_path)}")

    @Slot()
    def _on_send_to_enhance(self):
        if not self._handoff:
            return
        path = self._last_result_path
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "提示", "请先完成视频去水印，再送去超分。")
            return
        if path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
            QMessageBox.information(self, "提示", "当前结果是图片；请对视频结果使用「送去超分」。")
            return
        self._handoff(path, TAB_ENHANCE)

    @Slot(object)
    def _on_video_loaded(self, video):
        if not video:
            return
        self._apply_video_meta(video)

    def _apply_video_meta(self, video):
        self._vid_path_label.setText(os.path.basename(video.file_path))
        self._vid_info.setText(
            f"{video.width}x{video.height} | {video.duration_sec:.1f}s | {video.fps:.1f}fps"
        )
        dur_ms = max(1, int(video.duration_sec * 1000))
        self._preview_slider.setRange(0, dur_ms)
        self._start_slider.setRange(0, dur_ms)
        self._end_slider.setRange(0, dur_ms)
        self._end_slider.setValue(dur_ms)
        self._on_range_changed()
        self._refresh_video_preview()

    @Slot()
    def _on_preview_time_changed(self):
        video = self._vm.get_app_state().current_video
        if not video:
            return
        t = self._preview_slider.value() / 1000.0
        self._preview_time_label.setText(f"{t:.1f}s")
        self._preview_debounce.start()

    @Slot()
    def _on_range_changed(self):
        video = self._vm.get_app_state().current_video
        if not video:
            return
        start = self._start_slider.value() / 1000.0
        end = self._end_slider.value() / 1000.0
        if end <= start:
            end = min(video.duration_sec, start + 0.1)
            self._end_slider.blockSignals(True)
            self._end_slider.setValue(int(end * 1000))
            self._end_slider.blockSignals(False)
        self._start_label.setText(f"{start:.1f}s")
        self._end_label.setText(f"{end:.1f}s" if end < video.duration_sec else "全程")
        self._vm.update_watermark_range(start, end)

    @Slot()
    def _refresh_video_preview(self):
        video = self._vm.get_app_state().current_video
        if not video or not self._vm.bridge:
            return
        if self._preview_thread and self._preview_thread.isRunning():
            return
        t = self._preview_slider.value() / 1000.0
        try:
            if self._preview_png and os.path.isfile(self._preview_png):
                try:
                    os.remove(self._preview_png)
                except OSError:
                    pass
            fd, out_png = tempfile.mkstemp(suffix=".png", prefix="wm_prev_")
            os.close(fd)
            self._preview_png = out_png
            self._status.setText(f"预览抽取中 @ {t:.1f}s…")
            th = QThread(self)
            worker = _FramePreviewWorker(self._vm.bridge, video.file_path, t, out_png)
            worker.moveToThread(th)
            th.started.connect(worker.run)
            worker.finished.connect(self._on_preview_frame_ready)
            worker.failed.connect(self._on_preview_frame_failed)
            worker.finished.connect(th.quit)
            worker.failed.connect(th.quit)
            th.finished.connect(worker.deleteLater)
            th.finished.connect(th.deleteLater)
            th.finished.connect(lambda: setattr(self, "_preview_thread", None))
            self._preview_thread = th
            th.start()
        except Exception as e:
            self._status.setText(f"预览失败: {e}")

    @Slot(str, float)
    def _on_preview_frame_ready(self, png: str, t: float):
        video = self._vm.get_app_state().current_video
        try:
            preview = load_preview(png, max_side=4096) if png and os.path.isfile(png) else None
            if preview is None or not getattr(preview, "ok", True):
                raise RuntimeError("预览帧无效")
            wh = (video.width, video.height) if video else None
            self._vid_selector.load_pixmap(preview.pixmap, wh)
            backend = getattr(preview, "backend", "")
            self._status.setText(
                f"预览帧 @ {t:.1f}s" + (f"  ·  解码 {backend}" if backend else "")
            )
        except Exception as e:
            self._show_error(f"预览失败: {e}")

    @Slot(str)
    def _on_preview_frame_failed(self, msg: str):
        self._show_error(f"预览失败: {msg}")

    @Slot()
    def _on_run_image(self):
        state = self._vm.get_app_state()
        if not state.current_image_path:
            QMessageBox.warning(self, "提示", "请先导入图片")
            return
        regions = [r.as_tuple() for r in self._img_selector.regions()]
        if not regions:
            QMessageBox.warning(self, "提示", "请框选至少一个水印区域")
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "保存去水印图片", "",
            "PNG (*.png);;JPEG (*.jpg);;所有文件 (*.*)",
        )
        if not out:
            return
        self._progress.setVisible(True)
        self._progress.setValue(0)
        backend = "opencv" if self._img_mode_fast.isChecked() else "lama"
        self._vm.start_watermark_image(
            state.current_image_path, out, regions, backend=backend,
        )

    @Slot()
    def _on_run_video(self):
        video = self._vm.get_app_state().current_video
        if not video:
            QMessageBox.warning(self, "提示", "请先导入视频")
            return
        regions = [r.as_tuple() for r in self._vid_selector.regions()]
        if not regions:
            QMessageBox.warning(self, "提示", "请框选至少一个水印区域")
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "保存去水印视频", "",
            "MP4 (*.mp4);;所有文件 (*.*)",
        )
        if not out:
            return
        start = self._start_slider.value() / 1000.0
        end = self._end_slider.value() / 1000.0
        backend = "opencv" if self._vid_mode_fast.isChecked() else "lama"
        fps = video.fps or 25.0
        est_frames = max(1, int((end - start) * fps))
        if backend == "lama" and est_frames > 150:
            mins = est_frames * 8 / 60
            ans = QMessageBox.question(
                self, "处理量较大",
                f"当前时间段约 {est_frames} 帧，LaMa 精修预计需 {mins:.0f} 分钟以上。\n"
                "建议改用「快速」或缩短时间段（如 1–5 秒）试效果。\n\n是否继续？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._vm.start_watermark_video(out, regions, start, end, backend=backend)

    @Slot(int, float, str)
    def _on_progress(self, task_id, progress, message):
        self._progress.setValue(int(progress))
        self._status.setText(message)

    @Slot(int, str)
    def _on_finished(self, task_id, output_path):
        self._progress.setValue(100)
        self._status.setText(f"完成: {output_path}")
        self._last_result_path = output_path or ""
        is_video = bool(output_path) and not output_path.lower().endswith(
            (".png", ".jpg", ".jpeg", ".bmp", ".webp")
        )
        if getattr(self, "_btn_send_enhance", None):
            self._btn_send_enhance.setEnabled(is_video and os.path.isfile(output_path))
        if is_video:
            tab = ask_video_handoff(
                self,
                "去水印完成",
                f"已保存到:\n{output_path}\n\n可继续送去画质增强（无需重新导入）。",
                [("送去超分", TAB_ENHANCE)],
            )
            if tab is not None and self._handoff:
                self._handoff(output_path, tab)
        else:
            QMessageBox.information(self, "去水印完成", f"已保存到:\n{output_path}")

    @Slot(str)
    def _show_error(self, msg):
        self._progress.setVisible(False)
        QMessageBox.critical(self, "错误", msg)
