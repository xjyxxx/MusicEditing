"""去水印页面：图片 / 视频"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QProgressBar, QPushButton, QSlider, QTabWidget,
    QVBoxLayout, QWidget,
)

from ui.region_selector import RegionSelectorWidget
from viewmodels.main_vm import MainViewModel


class WatermarkPage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._preview_png: str = ""

        root = QVBoxLayout(self)

        hint = QLabel(
            "在预览图上拖拽框选水印区域，可框选多个矩形。"
            "需已编译 ONNX 引擎并下载 models/lama.onnx（scripts/download_lama_model.bat）"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        root.addWidget(hint)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_image_tab(), "图片去水印")
        self._tabs.addTab(self._build_video_tab(), "视频去水印")
        root.addWidget(self._tabs, 1)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #8cf;")
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
        layout.addWidget(self._img_selector, 1)

        side = QHBoxLayout()
        self._img_region_list = QListWidget()
        self._img_region_list.setMaximumWidth(220)
        side.addWidget(self._img_region_list)

        btn_col = QVBoxLayout()
        btn_clear = QPushButton("清除区域")
        btn_clear.clicked.connect(self._img_selector.clear_regions)
        btn_run = QPushButton("开始去水印")
        btn_run.setStyleSheet("background: #5b5bd6; color: white; padding: 8px 16px;")
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
        row.addWidget(self._vid_path_label, 1)
        row.addWidget(btn_import)
        layout.addLayout(row)

        self._vid_info = QLabel("")
        self._vid_info.setStyleSheet("color: #8cf;")
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

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("清除区域")
        btn_clear.clicked.connect(self._vid_selector.clear_regions)
        btn_run = QPushButton("开始视频去水印")
        btn_run.setStyleSheet("background: #5b5bd6; color: white; padding: 8px 16px;")
        btn_run.clicked.connect(self._on_run_video)
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_run)
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
        pix = QPixmap(path)
        if pix.isNull():
            QMessageBox.warning(self, "提示", "无法加载图片")
            return
        self._vm.import_image(path)
        self._img_path_label.setText(os.path.basename(path))
        self._img_selector.load_pixmap(pix, (pix.width(), pix.height()))
        self._status.setText(f"已加载图片: {path}")

    @Slot()
    def _on_import_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频", "",
            "视频 (*.mp4 *.mov *.avi *.mkv *.flv);;所有文件 (*.*)",
        )
        if path:
            self._vm.import_video(path)

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
        t = self._preview_slider.value() / 1000.0
        try:
            if self._preview_png and os.path.isfile(self._preview_png):
                os.remove(self._preview_png)
            fd, self._preview_png = tempfile.mkstemp(suffix=".png", prefix="wm_prev_")
            os.close(fd)
            self._vm.bridge.extract_video_frame(video.file_path, t, self._preview_png)
            pix = QPixmap(self._preview_png)
            if pix.isNull():
                raise RuntimeError("预览帧无效")
            self._vid_selector.load_pixmap(pix, (video.width, video.height))
            self._status.setText(f"预览帧 @ {t:.1f}s")
        except Exception as e:
            self._show_error(f"预览失败: {e}")

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
        self._vm.start_watermark_image(state.current_image_path, out, regions)

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
        fps = video.fps or 25.0
        est_frames = max(1, int((end - start) * fps))
        if est_frames > 150:
            mins = est_frames * 8 / 60
            ans = QMessageBox.question(
                self, "处理量较大",
                f"当前时间段约 {est_frames} 帧，CPU LaMa 预计需 {mins:.0f} 分钟以上。\n"
                "建议先缩短时间段（如 1–5 秒）试效果。\n\n是否继续？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._vm.start_watermark_video(out, regions, start, end)

    @Slot(int, float, str)
    def _on_progress(self, task_id, progress, message):
        self._progress.setValue(int(progress))
        self._status.setText(message)

    @Slot(int, str)
    def _on_finished(self, task_id, output_path):
        self._progress.setValue(100)
        self._status.setText(f"完成: {output_path}")
        QMessageBox.information(self, "去水印完成", f"已保存到:\n{output_path}")

    @Slot(str)
    def _show_error(self, msg):
        self._progress.setVisible(False)
        QMessageBox.critical(self, "错误", msg)
