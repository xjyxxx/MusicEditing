"""去水印页面：图片 / 视频"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot, QObject
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QListWidget,
    QMessageBox, QProgressBar, QPushButton, QRadioButton, QSlider, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)

from core.image_loader import load_preview
from ui.elided_label import ElidedPathLabel
from ui.exif_panel import ExifPanel, attach_exif_overlay
from ui.region_selector import RegionSelectorWidget
from ui.studio_kit import make_fixed_ai_hint, set_ai_hint_text
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
        self._batch_queue: list = []
        self._batch_out_dir = ""
        self._batch_regions: list = []
        self._batch_backend = "opencv"
        self._batch_kind = ""  # image | video
        self._batch_busy = False
        self._batch_results: list = []  # dict path/status/msg
        self._batch_retries: dict = {}  # path -> retry count
        self._batch_current = ""
        self._batch_max_retry = 2

        root = QVBoxLayout(self)

        hint = QLabel(
            "在预览图上拖拽框选水印区域，可框选多个。"
            "视频默认「快速」(OpenCV，秒级)；图片/精修用 LaMa（需 models/lama.onnx）。"
            "同一段视频只启动一次 media_cli，帧间复用后端。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("MutedText")
        hint.setToolTip(hint.text())
        # 限高，避免长说明盖住下方 AI 状态条 / Tab
        hint.setMaximumHeight(hint.fontMetrics().lineSpacing() * 3 + 6)
        hint.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        root.addWidget(hint)

        self._ai_hint = make_fixed_ai_hint()
        root.addWidget(self._ai_hint)
        fn = getattr(vm, "ai_runtime_hint", None)
        set_ai_hint_text(self._ai_hint, fn() if callable(fn) else "")
        vm.gpuNameChanged.connect(
            lambda _n: set_ai_hint_text(self._ai_hint, self._vm.ai_runtime_hint())
        )

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_image_tab(), "图片去水印")
        self._tabs.addTab(self._build_video_tab(), "视频去水印")
        root.addWidget(self._tabs, 1)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._batch_list = QListWidget()
        self._batch_list.setMaximumHeight(120)
        self._batch_list.setVisible(False)
        root.addWidget(self._batch_list)

        self._status = ElidedPathLabel("", object_name="InfoText")
        root.addWidget(self._status)

        vm.watermarkProgress.connect(self._on_progress)
        vm.watermarkFinished.connect(self._on_finished)
        vm.errorOccurred.connect(self._show_error)
        vm.videoLoaded.connect(self._on_video_loaded)
        vm.authTypeChanged.connect(lambda _a: self._refresh_license_gates())
        self._refresh_license_gates()

    def _refresh_license_gates(self):
        licensed = bool(getattr(self._vm, "is_licensed", False))
        tip = "" if licensed else "正式版可用 · 请到「个人中心」兑换卡密"
        for rb in (getattr(self, "_img_mode_lama", None), getattr(self, "_vid_mode_lama", None)):
            if rb is None:
                continue
            rb.setEnabled(licensed)
            rb.setToolTip(tip if not licensed else "LaMa 精修去水印")
            if not licensed and rb.isChecked():
                if rb is self._img_mode_lama:
                    self._img_mode_fast.setChecked(True)
                elif rb is self._vid_mode_lama:
                    self._vid_mode_fast.setChecked(True)

    def _build_image_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        row = QHBoxLayout()
        self._img_path_label = ElidedPathLabel("未选择图片")
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
        btn_suggest = QPushButton("智能建议")
        btn_suggest.setToolTip("根据四角边缘密度建议 1–2 个角标框，可再拖拽修改")
        btn_suggest.clicked.connect(self._on_suggest_image)
        btn_dy = QPushButton("抖音右上")
        btn_dy.setObjectName("GhostBtn")
        btn_dy.setToolTip("右上角标预设（约 22%×10%）")
        btn_dy.clicked.connect(lambda: self._on_corner_preset("image", "douyin"))
        btn_ks = QPushButton("快手右上")
        btn_ks.setObjectName("GhostBtn")
        btn_ks.setToolTip("右上角标预设（约 20%×9%）")
        btn_ks.clicked.connect(lambda: self._on_corner_preset("image", "kuaishou"))
        btn_clear = QPushButton("清除区域")
        btn_clear.clicked.connect(self._img_selector.clear_regions)
        btn_batch = QPushButton("文件夹批量…")
        btn_batch.setToolTip("对文件夹内图片使用当前框选区域批量去水印")
        btn_batch.clicked.connect(self._on_batch_images)
        btn_run = QPushButton("开始去水印")
        btn_run.setObjectName("primaryButton")
        btn_run.clicked.connect(self._on_run_image)
        btn_col.addWidget(btn_suggest)
        btn_col.addWidget(btn_dy)
        btn_col.addWidget(btn_ks)
        btn_col.addWidget(btn_clear)
        btn_col.addWidget(btn_batch)
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
        self._vid_path_label = ElidedPathLabel("未选择视频")
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
        btn_suggest = QPushButton("智能建议")
        btn_suggest.clicked.connect(self._on_suggest_video)
        btn_dy = QPushButton("抖音右上")
        btn_dy.setObjectName("GhostBtn")
        btn_dy.clicked.connect(lambda: self._on_corner_preset("video", "douyin"))
        btn_ks = QPushButton("快手右上")
        btn_ks.setObjectName("GhostBtn")
        btn_ks.clicked.connect(lambda: self._on_corner_preset("video", "kuaishou"))
        btn_clear = QPushButton("清除区域")
        btn_clear.clicked.connect(self._vid_selector.clear_regions)
        btn_batch = QPushButton("多视频批量…")
        btn_batch.setToolTip("多选视频，用当前角标区域与时间比例顺序处理")
        btn_batch.clicked.connect(self._on_batch_videos)
        btn_run = QPushButton("开始视频去水印")
        btn_run.setObjectName("primaryButton")
        btn_run.clicked.connect(self._on_run_video)
        self._btn_send_enhance = QPushButton("送去超分")
        self._btn_send_enhance.setEnabled(False)
        self._btn_send_enhance.setToolTip("将去水印结果导入「画质增强」")
        self._btn_send_enhance.clicked.connect(self._on_send_to_enhance)
        btn_row.addWidget(btn_suggest)
        btn_row.addWidget(btn_dy)
        btn_row.addWidget(btn_ks)
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_batch)
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
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.heic *.heif *.tif *.tiff);;所有文件 (*.*)",
        )
        if path:
            self.open_image(path)

    def open_image(self, path: str) -> bool:
        """供照片图库等页面复用的静图导入入口。"""
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "去水印", "图片文件不存在")
            return False
        preview = load_preview(path, max_side=4096)
        if not preview.ok:
            QMessageBox.warning(self, "去水印", "无法加载图片")
            return False
        self._tabs.setCurrentIndex(0)
        self._vm.import_image(path)
        self._img_path_label.setText(path)
        self._img_selector.load_pixmap(preview.pixmap, preview.native_size)
        self._img_exif.load_path(path)
        self._status.setText(
            f"已加载图片: {path}  ·  {preview.native_width}×{preview.native_height}"
            f"  ·  解码 {preview.backend}"
        )
        return True

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
        self._vid_path_label.setText(video.file_path)
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

    @Slot()
    def _on_suggest_image(self):
        picked = self._img_selector.suggest_corner_regions(2)
        if not picked:
            QMessageBox.information(self, "智能建议", "未检测到明显角标，请手动框选。")
        else:
            self._status.setText(f"已建议 {len(picked)} 个区域，可再调整")

    @Slot()
    def _on_suggest_video(self):
        picked = self._vid_selector.suggest_corner_regions(2)
        if not picked:
            QMessageBox.information(self, "智能建议", "未检测到明显角标，请先刷新预览帧或手动框选。")
        else:
            self._status.setText(f"已建议 {len(picked)} 个区域，可再调整")

    def _on_corner_preset(self, kind: str, platform: str):
        sel = self._img_selector if kind == "image" else self._vid_selector
        picked = sel.apply_platform_corner_preset(platform)
        if not picked:
            QMessageBox.information(self, "角标预设", "请先导入图片/刷新预览帧。")
        else:
            label = "抖音" if platform == "douyin" else "快手"
            self._status.setText(f"已套用{label}右上角标预设，可再微调")

    @Slot()
    def _on_batch_images(self):
        if self._batch_busy:
            QMessageBox.information(self, "提示", "批量任务进行中")
            return
        regions = [r.as_tuple() for r in self._img_selector.regions()]
        if not regions:
            QMessageBox.warning(self, "提示", "请先框选或「智能建议」至少一个区域")
            return
        folder = QFileDialog.getExistingDirectory(self, "选择图片文件夹")
        if not folder:
            return
        out_dir = QFileDialog.getExistingDirectory(self, "选择输出目录", folder)
        if not out_dir:
            return
        exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}
        files = sorted(
            os.path.join(folder, n)
            for n in os.listdir(folder)
            if os.path.splitext(n)[1].lower() in exts
        )
        if not files:
            QMessageBox.warning(self, "提示", "文件夹内没有支持的图片")
            return
        backend = "opencv" if self._img_mode_fast.isChecked() else "lama"
        if backend == "lama":
            ok, tip = self._vm.require_feature("watermark_lama")
            if not ok:
                QMessageBox.warning(self, "正式版", tip)
                return
        self._batch_queue = files
        self._batch_out_dir = out_dir
        self._batch_regions = regions
        self._batch_backend = backend
        self._batch_kind = "image"
        self._batch_busy = True
        self._batch_results = []
        self._batch_retries = {}
        self._batch_list.clear()
        self._batch_list.setVisible(True)
        for f in files:
            self._batch_list.addItem(f"等待 · {os.path.basename(f)}")
        self._progress.setVisible(True)
        self._status.setText(f"批量去水印：0/{len(files)}")
        self._run_next_batch()

    @Slot()
    def _on_batch_videos(self):
        if self._batch_busy:
            QMessageBox.information(self, "提示", "批量任务进行中")
            return
        regions = [r.as_tuple() for r in self._vid_selector.regions()]
        if not regions:
            QMessageBox.warning(self, "提示", "请先框选或「智能建议」至少一个区域")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择多个视频",
            "",
            "视频 (*.mp4 *.mov *.mkv *.avi *.webm);;所有文件 (*.*)",
        )
        if not files:
            return
        out_dir = QFileDialog.getExistingDirectory(self, "选择输出目录")
        if not out_dir:
            return
        backend = "opencv" if self._vid_mode_fast.isChecked() else "lama"
        if backend == "lama":
            ok, tip = self._vm.require_feature("watermark_lama")
            if not ok:
                QMessageBox.warning(self, "正式版", tip)
                return
        self._batch_queue = list(files)
        self._batch_out_dir = out_dir
        self._batch_regions = regions
        self._batch_backend = backend
        self._batch_kind = "video"
        self._batch_busy = True
        self._batch_results = []
        self._batch_retries = {}
        self._batch_list.clear()
        self._batch_list.setVisible(True)
        for f in files:
            self._batch_list.addItem(f"等待 · {os.path.basename(f)}")
        self._progress.setVisible(True)
        self._status.setText(f"批量视频去水印：0/{len(files)}")
        self._run_next_batch()

    def _batch_mark(self, src: str, status: str):
        name = os.path.basename(src)
        for i in range(self._batch_list.count()):
            it = self._batch_list.item(i)
            if it and name in it.text():
                it.setText(f"{status} · {name}")
                break

    def _run_next_batch(self):
        if not self._batch_queue:
            self._batch_busy = False
            self._progress.setValue(100)
            ok = sum(1 for r in self._batch_results if r.get("status") == "成功")
            fail = sum(1 for r in self._batch_results if r.get("status") == "失败")
            self._status.setText(
                f"批量完成 · 成功 {ok} · 失败 {fail} → {self._batch_out_dir}"
            )
            QMessageBox.information(
                self, "批量完成",
                f"成功 {ok} · 失败 {fail}\n结果目录：\n{self._batch_out_dir}",
            )
            return
        src = self._batch_queue.pop(0)
        self._batch_current = src
        stem = os.path.splitext(os.path.basename(src))[0]
        left = len(self._batch_queue)
        retries = self._batch_retries.get(src, 0)
        tag = "重试中" if retries else "处理中"
        self._batch_mark(src, tag)
        self._status.setText(f"批量{tag}… 剩余 {left} · {os.path.basename(src)}")
        if self._batch_kind == "image":
            ext = os.path.splitext(src)[1] or ".png"
            out = os.path.join(self._batch_out_dir, f"{stem}_nowm{ext}")
            # 失败重试时换快速后端
            be = self._batch_backend
            if retries > 0:
                be = "opencv"
            self._vm.start_watermark_image(
                src, out, self._batch_regions, backend=be,
            )
            return
        # 视频：后台线程直接调 bridge，避免 import_video 异步竞态
        out = os.path.join(self._batch_out_dir, f"{stem}_nowm.mp4")
        bridge = self._vm.bridge
        regions = list(self._batch_regions)
        backend = "opencv" if retries > 0 else self._batch_backend
        # 重试时略缩小区域
        if retries > 0 and regions:
            regions = [
                (max(0.0, x + 0.01), max(0.0, y + 0.01),
                 min(1.0, w - 0.02), min(1.0, h - 0.02))
                for x, y, w, h in regions
            ]
        if not bridge:
            self._batch_busy = False
            QMessageBox.critical(self, "错误", "媒体引擎未加载")
            return

        def work():
            try:
                model = self._vm._watermark_model_path(backend)  # noqa: SLF001
                info = bridge.probe_video(src)
                fps = float(getattr(info, "fps", 0) or 25.0)
                dur = float(getattr(info, "duration_sec", 0) or 0.0)
                bridge.watermark_inpaint_video(
                    model, src, out, regions,
                    fps=fps,
                    start_sec=0.0,
                    end_sec=max(0.0, dur),
                    backend=backend,
                )
                return out, ""
            except Exception as e:
                return "", str(e)

        import threading

        def done():
            path, err = result[0], result[1]
            if err:
                n = self._batch_retries.get(src, 0) + 1
                self._batch_retries[src] = n
                if n <= self._batch_max_retry:
                    self._batch_mark(src, f"重试{n}")
                    self._batch_queue.insert(0, src)
                    self._run_next_batch()
                    return
                self._batch_mark(src, "失败")
                self._batch_results.append(
                    {"name": os.path.basename(src), "status": "失败", "detail": err}
                )
                self._run_next_batch()
                return
            self._batch_mark(src, "成功")
            self._batch_results.append(
                {"name": os.path.basename(src), "status": "成功", "detail": path}
            )
            self._last_result_path = path
            self._run_next_batch()

        result: list = ["", "pending"]

        def run():
            path, err = work()
            result[0], result[1] = path, err
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, done)

        threading.Thread(target=run, daemon=True).start()

    @Slot(int, float, str)
    def _on_progress(self, task_id, progress, message):
        self._progress.setValue(int(progress))
        self._status.setText(message)

    @Slot(int, str)
    def _on_finished(self, task_id, output_path):
        self._progress.setValue(100)
        self._status.setText(f"完成: {output_path}")
        self._last_result_path = output_path or ""
        if self._batch_busy:
            src = self._batch_current
            if src:
                self._batch_mark(src, "成功")
                self._batch_results.append(
                    {"name": os.path.basename(src), "status": "成功", "detail": output_path}
                )
            left = len(self._batch_queue)
            self._status.setText(f"批量剩余 {left} · 刚完成 {os.path.basename(output_path or '')}")
            self._run_next_batch()
            return
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
        if self._batch_busy:
            src = self._batch_current
            if src:
                n = self._batch_retries.get(src, 0) + 1
                self._batch_retries[src] = n
                if n <= self._batch_max_retry:
                    self._batch_mark(src, f"重试{n}")
                    self._batch_queue.insert(0, src)
                    self._progress.setVisible(True)
                    self._run_next_batch()
                    return
                self._batch_mark(src, "失败")
                self._batch_results.append(
                    {"name": os.path.basename(src), "status": "失败", "detail": msg}
                )
                self._progress.setVisible(True)
                self._run_next_batch()
                return
            self._batch_busy = False
            self._batch_queue.clear()
        QMessageBox.critical(self, "错误", msg)
