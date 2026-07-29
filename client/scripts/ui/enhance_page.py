"""画质增强 / 4K 超分：左原图 | 右超分结果，中间一条细线；滚轮缩放、拖拽平移。"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Slot
from PySide6.QtGui import QColor, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QFrame, QGraphicsPixmapItem, QGraphicsScene,
    QGraphicsView, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSlider, QTabWidget,
    QVBoxLayout, QWidget,
)

from core.image_loader import load_preview, probe_size
from ui.exif_panel import ExifPanel
from viewmodels.main_vm import MainViewModel

_STYLE = """
QLabel#HintLabel {
    color: #9a9ab0; font-size: 12px; padding: 8px 10px;
    background: #252536; border: 1px solid #3a3a50; border-radius: 6px;
}
QLabel#MetaBadge {
    color: #b8e0ff; font-size: 13px; font-weight: 600; padding: 6px 10px;
    background: #1a2a3a; border: 1px solid #3a5a7a; border-radius: 6px;
}
QLabel#SideTitle {
    color: #c8c8ff; font-size: 13px; font-weight: 700;
    padding: 4px 0;
}
QPushButton#PrimaryBtn {
    background: #5b5bd6; color: white; padding: 10px 20px;
    border-radius: 6px; font-weight: 600;
}
QPushButton#PrimaryBtn:hover { background: #6c6ce0; }
QPushButton#PrimaryBtn:disabled { background: #3a3a55; color: #888; }
QPushButton#GhostBtn {
    background: #2d2d42; color: #ddd; padding: 8px 14px;
    border-radius: 6px; border: 1px solid #4a4a66;
}
QPushButton#GhostBtn:hover { background: #3d3d58; }
QPushButton#GhostBtn:disabled { color: #666; border-color: #333; }
QPushButton#PresetBtn {
    background: #2a2a3c; color: #ccc; padding: 4px 10px;
    border-radius: 4px; border: 1px solid #454560;
}
QPushButton#PresetBtn:hover { background: #4a4a80; color: white; }
QGroupBox {
    border: 1px solid #44445a; border-radius: 8px;
    margin-top: 10px; padding-top: 12px; font-weight: 600; color: #b0b0e0;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #aaf; }
QProgressBar {
    border: 1px solid #555; border-radius: 4px; text-align: center;
    min-height: 18px; background: #1a1a28;
}
QProgressBar::chunk { background: #5b5bd6; border-radius: 3px; }
QFrame#CompareBox {
    background: #0e0e16;
    border: 1px solid #3a3a50;
    border-radius: 8px;
}
QFrame#CenterLine {
    background: #666688;
    max-width: 1px;
    min-width: 1px;
    border: none;
}
QGraphicsView {
    background: #0e0e16;
    border: none;
}
"""


class ZoomImageView(QGraphicsView):
    """滚轮缩放，左键拖拽平移。Ctrl+滚轮时由 peer 同步缩放。"""

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item: QGraphicsPixmapItem | None = None
        self._path = ""
        self._native_size = (0, 0)
        self._peer: ZoomImageView | None = None
        self._syncing = False
        # 不透明底色 + 全量刷新：避免缩小时旧像素残影（透明底/OpenGL 视口易拖影）
        self.setBackgroundBrush(QColor(14, 14, 22))
        self.setCacheMode(QGraphicsView.CacheNone)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setMinimumHeight(280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._load_backend = ""
        self._placeholder(placeholder or "—")

    def set_peer(self, peer: "ZoomImageView | None"):
        self._peer = peer

    def _placeholder(self, text: str):
        self._scene.clear()
        self._item = None
        self._path = ""
        self._native_size = (0, 0)
        self._load_backend = ""
        self.resetTransform()
        t = self._scene.addText(text)
        t.setDefaultTextColor(Qt.gray)
        self._scene.setSceneRect(QRectF(0, 0, 400, 300))
        self.centerOn(t)

    def load_path(self, path: str, fit: bool = True) -> bool:
        preview = load_preview(path, max_side=2560)
        if not preview.ok:
            self._placeholder(f"无法加载\n{os.path.basename(path) if path else ''}")
            return False
        self._scene.clear()
        self._item = self._scene.addPixmap(preview.pixmap)
        self._item.setTransformationMode(Qt.SmoothTransformation)
        self._item.setCacheMode(QGraphicsPixmapItem.NoCache)
        self._path = path
        self._native_size = preview.native_size
        self._load_backend = preview.backend
        self._scene.setSceneRect(QRectF(preview.pixmap.rect()))
        self.resetTransform()
        if fit:
            self.fitInView(self._item, Qt.KeepAspectRatio)
        self.viewport().update()
        return True

    def load_backend(self) -> str:
        return self._load_backend

    def clear_view(self, text: str = "—"):
        self._placeholder(text)

    def has_image(self) -> bool:
        return self._item is not None

    def zoom_factor(self) -> float:
        return float(self.transform().m11())

    def native_size(self) -> tuple[int, int]:
        return self._native_size

    def _apply_zoom(self, factor: float) -> bool:
        if self._item is None:
            return False
        z = self.zoom_factor() * factor
        if z < 0.05 or z > 40:
            return False
        self.scale(factor, factor)
        # 缩小后强制整窗重绘，清掉上一档缩放残留
        self.viewport().update()
        return True

    def wheelEvent(self, event: QWheelEvent):
        if self._item is None:
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        if not self._apply_zoom(factor):
            event.accept()
            return
        # 按住 Ctrl：两侧同步缩放；否则只缩放当前鼠标所在图
        if (
            event.modifiers() & Qt.ControlModifier
            and self._peer is not None
            and self._peer.has_image()
            and not self._syncing
        ):
            self._peer._syncing = True
            try:
                self._peer._apply_zoom(factor)
            finally:
                self._peer._syncing = False
        event.accept()

    def zoom_in(self):
        self._apply_zoom(1.25)

    def zoom_out(self):
        self._apply_zoom(0.8)

    def zoom_fit(self):
        if self._item is not None:
            self.fitInView(self._item, Qt.KeepAspectRatio)
            self.viewport().update()

    def zoom_100(self):
        if self._item is None:
            return
        self.resetTransform()
        self.centerOn(self._item)
        self.viewport().update()

class SideBySideCompare(QWidget):
    """左原图 | 细线 | 右超分结果。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        box = QFrame()
        box.setObjectName("CompareBox")
        row = QHBoxLayout(box)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(0)

        left = QVBoxLayout()
        left.setSpacing(4)
        self._left_title = QLabel("原图")
        self._left_title.setObjectName("SideTitle")
        self._left_title.setAlignment(Qt.AlignCenter)
        left.addWidget(self._left_title)
        self.left_view = ZoomImageView("导入后显示原图")
        left.addWidget(self.left_view, 1)

        line = QFrame()
        line.setObjectName("CenterLine")
        line.setFrameShape(QFrame.NoFrame)
        line.setFixedWidth(1)

        right = QVBoxLayout()
        right.setSpacing(4)
        self._right_title = QLabel("超分结果")
        self._right_title.setObjectName("SideTitle")
        self._right_title.setAlignment(Qt.AlignCenter)
        right.addWidget(self._right_title)
        self.right_view = ZoomImageView("超分完成后显示")
        right.addWidget(self.right_view, 1)

        # 互为 peer：Ctrl+滚轮时同步缩放
        self.left_view.set_peer(self.right_view)
        self.right_view.set_peer(self.left_view)

        row.addLayout(left, 1)
        row.addWidget(line)
        row.addLayout(right, 1)
        outer.addWidget(box, 1)

        zoom_row = QHBoxLayout()
        for text, slot in (
            ("两侧放大", self.zoom_in),
            ("两侧缩小", self.zoom_out),
            ("适应窗口", self.zoom_fit),
            ("1:1", self.zoom_100),
        ):
            b = QPushButton(text)
            b.setObjectName("GhostBtn")
            b.clicked.connect(slot)
            zoom_row.addWidget(b)
        zoom_row.addStretch()
        tip = QLabel("滚轮：缩放当前侧  ·  Ctrl+滚轮：两侧同步  ·  拖拽平移")
        tip.setStyleSheet("color:#888; font-size:11px;")
        zoom_row.addWidget(tip)
        outer.addLayout(zoom_row)

    def set_original(self, path: str) -> bool:
        ok = self.left_view.load_path(path, fit=True)
        return ok

    def set_result(self, path: str) -> bool:
        ok = self.right_view.load_path(path, fit=True)
        return ok

    def clear_result(self, text: str = "超分完成后显示"):
        self.right_view.clear_view(text)

    def clear_all(self, left_text: str = "导入后显示原图", right_text: str = "超分完成后显示"):
        self.left_view.clear_view(left_text)
        self.right_view.clear_view(right_text)

    def zoom_in(self):
        self.left_view.zoom_in()
        self.right_view.zoom_in()

    def zoom_out(self):
        self.left_view.zoom_out()
        self.right_view.zoom_out()

    def zoom_fit(self):
        self.left_view.zoom_fit()
        self.right_view.zoom_fit()

    def zoom_100(self):
        self.left_view.zoom_100()
        self.right_view.zoom_100()


class EnhancePage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._preview_png = ""
        self._result_path = ""
        self._src_image_path = ""
        self._busy = False
        self.setStyleSheet(_STYLE)

        root = QVBoxLayout(self)
        root.setSpacing(8)

        hint = QLabel(
            "左边原图、右边超分结果，中间一条细线。"
            "鼠标在哪边滚轮就缩放哪边；按住 Ctrl 再滚轮则两侧同步缩放。可拖拽平移。"
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_image_tab(), "图片超分")
        self._tabs.addTab(self._build_video_tab(), "视频超分")
        root.addWidget(self._tabs, 1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status = QLabel("就绪")
        self._status.setStyleSheet("color:#8cf;")
        root.addWidget(self._status)

        vm.enhanceProgress.connect(self._on_progress)
        vm.enhanceFinished.connect(self._on_finished)
        vm.errorOccurred.connect(self._show_error)
        vm.videoLoaded.connect(self._on_video_loaded)

    def _build_mode_panel(self, prefix: str, default_ai: bool) -> QWidget:
        box = QGroupBox("处理参数")
        col = QVBoxLayout(box)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("后端"))
        fast = QRadioButton("快速 · OpenCV")
        ai = QRadioButton("AI · Real-ESRGAN")
        (ai if default_ai else fast).setChecked(True)
        g = QButtonGroup(self)
        g.addButton(fast)
        g.addButton(ai)
        mode_row.addWidget(fast)
        mode_row.addWidget(ai)
        mode_row.addStretch()
        col.addLayout(mode_row)

        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("倍率"))
        s2 = QRadioButton("2×")
        s4 = QRadioButton("4×")
        s2.setChecked(True)
        sg = QButtonGroup(self)
        sg.addButton(s2)
        sg.addButton(s4)
        scale_row.addWidget(s2)
        scale_row.addWidget(s4)
        scale_row.addStretch()
        col.addLayout(scale_row)

        str_row = QHBoxLayout()
        str_row.addWidget(QLabel("AI 强度"))
        strength = QSlider(Qt.Horizontal)
        strength.setRange(30, 100)
        strength.setValue(65)
        strength_lbl = QLabel("65%")
        strength.valueChanged.connect(lambda v: strength_lbl.setText(f"{v}%"))
        str_row.addWidget(strength, 1)
        str_row.addWidget(strength_lbl)
        col.addLayout(str_row)

        preset = QHBoxLayout()
        for label, val in (("自然 50%", 50), ("推荐 65%", 65), ("锐利 85%", 85)):
            b = QPushButton(label)
            b.setObjectName("PresetBtn")
            b.clicked.connect(lambda _=False, v=val, s=strength: s.setValue(v))
            preset.addWidget(b)
        preset.addStretch()
        col.addLayout(preset)

        setattr(self, f"_{prefix}_mode_fast", fast)
        setattr(self, f"_{prefix}_mode_ai", ai)
        setattr(self, f"_{prefix}_scale_2", s2)
        setattr(self, f"_{prefix}_scale_4", s4)
        setattr(self, f"_{prefix}_strength", strength)
        return box

    def _build_image_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self._img_path_label = QLabel("未选择图片")
        self._img_path_label.setStyleSheet("color:#ccc;")
        btn_import = QPushButton("导入图片")
        btn_import.setObjectName("GhostBtn")
        btn_import.clicked.connect(self._on_import_image)
        top.addWidget(self._img_path_label, 1)
        top.addWidget(btn_import)
        layout.addLayout(top)

        self._img_meta = QLabel("—")
        self._img_meta.setObjectName("MetaBadge")
        layout.addWidget(self._img_meta)

        self._img_compare = SideBySideCompare()
        layout.addWidget(self._img_compare, 1)

        self._img_exif = ExifPanel(lambda: self._vm.bridge)
        layout.addWidget(self._img_exif)

        layout.addWidget(self._build_mode_panel("img", default_ai=True))

        actions = QHBoxLayout()
        self._btn_run_img = QPushButton("开始超分")
        self._btn_run_img.setObjectName("PrimaryBtn")
        self._btn_run_img.clicked.connect(self._on_run_image)
        self._btn_open_result = QPushButton("打开结果文件")
        self._btn_open_result.setObjectName("GhostBtn")
        self._btn_open_result.setEnabled(False)
        self._btn_open_result.clicked.connect(self._open_result)
        self._btn_folder_result = QPushButton("打开文件夹")
        self._btn_folder_result.setObjectName("GhostBtn")
        self._btn_folder_result.setEnabled(False)
        self._btn_folder_result.clicked.connect(self._open_result_folder)
        actions.addWidget(self._btn_run_img)
        actions.addWidget(self._btn_open_result)
        actions.addWidget(self._btn_folder_result)
        actions.addStretch()
        layout.addLayout(actions)
        return page

    def _build_video_tab(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)

        top = QHBoxLayout()
        self._vid_path_label = QLabel("未选择视频")
        btn_import = QPushButton("导入视频")
        btn_import.setObjectName("GhostBtn")
        btn_import.clicked.connect(self._on_import_video)
        top.addWidget(self._vid_path_label, 1)
        top.addWidget(btn_import)
        layout.addLayout(top)

        self._vid_info = QLabel("—")
        self._vid_info.setObjectName("MetaBadge")
        layout.addWidget(self._vid_info)

        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("预览时刻"))
        self._preview_slider = QSlider(Qt.Horizontal)
        self._preview_time_label = QLabel("0.0s")
        btn_prev = QPushButton("刷新左侧预览")
        btn_prev.setObjectName("GhostBtn")
        btn_prev.clicked.connect(self._refresh_video_preview)
        preview_row.addWidget(self._preview_slider, 1)
        preview_row.addWidget(self._preview_time_label)
        preview_row.addWidget(btn_prev)
        layout.addLayout(preview_row)
        self._preview_slider.valueChanged.connect(self._on_preview_slider)

        self._vid_compare = SideBySideCompare()
        self._vid_compare.clear_all("导入视频后刷新预览", "超分完成后显示结果首帧")
        layout.addWidget(self._vid_compare, 1)

        range_box = QGroupBox("处理时间段（默认前 2 秒）")
        rc = QVBoxLayout(range_box)
        start_row = QHBoxLayout()
        start_row.addWidget(QLabel("起点"))
        self._start_slider = QSlider(Qt.Horizontal)
        self._start_label = QLabel("0.0s")
        start_row.addWidget(self._start_slider, 1)
        start_row.addWidget(self._start_label)
        end_row = QHBoxLayout()
        end_row.addWidget(QLabel("终点"))
        self._end_slider = QSlider(Qt.Horizontal)
        self._end_label = QLabel("2.0s")
        end_row.addWidget(self._end_slider, 1)
        end_row.addWidget(self._end_label)
        rc.addLayout(start_row)
        rc.addLayout(end_row)
        quick = QHBoxLayout()
        for label, secs in (("试 1 秒", 1), ("试 2 秒", 2), ("试 5 秒", 5), ("全程", 0)):
            b = QPushButton(label)
            b.setObjectName("PresetBtn")
            b.clicked.connect(lambda _=False, s=secs: self._set_range_preset(s))
            quick.addWidget(b)
        quick.addStretch()
        rc.addLayout(quick)
        layout.addWidget(range_box)
        self._start_slider.valueChanged.connect(self._on_range_changed)
        self._end_slider.valueChanged.connect(self._on_range_changed)

        layout.addWidget(self._build_mode_panel("vid", default_ai=False))

        actions = QHBoxLayout()
        self._btn_run_vid = QPushButton("开始超分")
        self._btn_run_vid.setObjectName("PrimaryBtn")
        self._btn_run_vid.clicked.connect(self._on_run_video)
        self._btn_open_vid = QPushButton("打开结果文件")
        self._btn_open_vid.setObjectName("GhostBtn")
        self._btn_open_vid.setEnabled(False)
        self._btn_open_vid.clicked.connect(self._open_result)
        self._btn_folder_vid = QPushButton("打开文件夹")
        self._btn_folder_vid.setObjectName("GhostBtn")
        self._btn_folder_vid.setEnabled(False)
        self._btn_folder_vid.clicked.connect(self._open_result_folder)
        actions.addWidget(self._btn_run_vid)
        actions.addWidget(self._btn_open_vid)
        actions.addWidget(self._btn_folder_vid)
        actions.addStretch()
        layout.addLayout(actions)

        scroll.setWidget(body)
        outer.addWidget(scroll)
        return page

    def _current_scale(self, prefix: str) -> int:
        return 4 if getattr(self, f"_{prefix}_scale_4").isChecked() else 2

    def _current_backend(self, prefix: str) -> str:
        return "opencv" if getattr(self, f"_{prefix}_mode_fast").isChecked() else "realesrgan"

    def _current_strength(self, prefix: str) -> int:
        return int(getattr(self, f"_{prefix}_strength").value())

    def _set_busy(self, busy: bool):
        self._busy = busy
        for btn in (getattr(self, "_btn_run_img", None), getattr(self, "_btn_run_vid", None)):
            if btn:
                btn.setEnabled(not busy)

    @staticmethod
    def _file_size_mb(path: str) -> str:
        try:
            n = os.path.getsize(path)
            if n >= 1024 * 1024:
                return f"{n / (1024 * 1024):.1f} MB"
            return f"{n / 1024:.0f} KB"
        except OSError:
            return "—"

    def _set_range_preset(self, seconds: int):
        video = self._vm.get_app_state().current_video
        if not video:
            return
        max_ms = max(1, int(video.duration_sec * 1000))
        self._start_slider.setValue(0)
        self._end_slider.setValue(max_ms if seconds <= 0 else min(max_ms, seconds * 1000))

    @Slot()
    def _on_import_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)",
        )
        if not path:
            return
        self._vm.import_image(path)
        self._src_image_path = path
        self._img_path_label.setText(path)
        w, h = probe_size(path)
        if w > 0:
            self._img_meta.setText(f"原图  {w}×{h}  ·  {self._file_size_mb(path)}")
        self._img_compare.set_original(path)
        self._img_compare.clear_result("超分完成后显示")
        self._img_exif.load_path(path)
        self._btn_open_result.setEnabled(False)
        self._btn_folder_result.setEnabled(False)
        be = self._img_compare.left_view.load_backend() or "—"
        self._status.setText(f"已导入: {os.path.basename(path)}  ·  解码 {be}")

    @Slot()
    def _on_import_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频", "",
            "视频 (*.mp4 *.mov *.mkv *.avi *.webm);;所有文件 (*.*)",
        )
        if path:
            self._vm.import_video(path)

    @Slot(object)
    def _on_video_loaded(self, video):
        if not video:
            return
        self._vid_path_label.setText(video.file_path)
        self._vid_info.setText(
            f"原片  {video.width}×{video.height}  ·  {video.duration_sec:.1f}s  ·  "
            f"{video.fps:.1f} fps  ·  {self._file_size_mb(video.file_path)}"
        )
        max_ms = max(1, int(video.duration_sec * 1000))
        for s in (self._preview_slider, self._start_slider, self._end_slider):
            s.blockSignals(True)
            s.setMaximum(max_ms)
            s.blockSignals(False)
        self._start_slider.setValue(0)
        self._end_slider.setValue(min(max_ms, 2000))
        self._on_range_changed()
        self._refresh_video_preview()
        self._vid_compare.clear_result("超分完成后显示结果首帧")
        self._btn_open_vid.setEnabled(False)
        self._btn_folder_vid.setEnabled(False)

    @Slot()
    def _on_preview_slider(self):
        self._preview_time_label.setText(f"{self._preview_slider.value() / 1000.0:.1f}s")

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
        self._end_label.setText(
            "全程" if end >= video.duration_sec - 0.05 else f"{end:.1f}s"
        )
        self._vm.update_enhance_range(start, end)

    @Slot()
    def _refresh_video_preview(self):
        video = self._vm.get_app_state().current_video
        if not video or not self._vm.bridge:
            return
        t = self._preview_slider.value() / 1000.0
        try:
            if self._preview_png and os.path.isfile(self._preview_png):
                os.remove(self._preview_png)
            fd, self._preview_png = tempfile.mkstemp(suffix=".png", prefix="sr_prev_")
            os.close(fd)
            self._vm.bridge.extract_video_frame(video.file_path, t, self._preview_png)
            if self._vid_compare.set_original(self._preview_png):
                self._status.setText(f"左侧预览 @ {t:.1f}s")
        except Exception as e:
            self._show_error(f"预览失败: {e}")

    def _default_out_path(self, src: str, scale: int, ext: str) -> str:
        p = Path(src)
        return str(p.with_name(f"{p.stem}_sr_x{scale}{ext}"))

    @Slot()
    def _on_run_image(self):
        state = self._vm.get_app_state()
        if not state.current_image_path:
            QMessageBox.warning(self, "提示", "请先导入图片")
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "保存超分图片",
            self._default_out_path(state.current_image_path, self._current_scale("img"), ".png"),
            "PNG (*.png);;JPEG (*.jpg);;所有文件 (*.*)",
        )
        if not out:
            return
        self._result_path = out
        self._src_image_path = state.current_image_path
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._set_busy(True)
        self._img_compare.clear_result("超分处理中…")
        self._status.setText("超分处理中…")
        self._vm.start_enhance_image(
            state.current_image_path, out,
            scale=self._current_scale("img"),
            backend=self._current_backend("img"),
            strength=self._current_strength("img"),
        )

    @Slot()
    def _on_run_video(self):
        video = self._vm.get_app_state().current_video
        if not video:
            QMessageBox.warning(self, "提示", "请先导入视频")
            return
        out, _ = QFileDialog.getSaveFileName(
            self, "保存超分视频",
            str(Path(video.file_path).with_name(
                f"{Path(video.file_path).stem}_sr_x{self._current_scale('vid')}.mp4"
            )),
            "MP4 (*.mp4);;所有文件 (*.*)",
        )
        if not out:
            return
        start = self._start_slider.value() / 1000.0
        end = self._end_slider.value() / 1000.0
        backend = self._current_backend("vid")
        scale = self._current_scale("vid")
        fps = video.fps or 25.0
        est = max(1, int((end - start) * fps))
        if backend == "realesrgan" and est > 90:
            ans = QMessageBox.question(
                self, "处理量较大",
                f"约 {est} 帧，AI 可能较慢。是否继续？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        self._result_path = out
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._set_busy(True)
        self._vid_compare.clear_result("视频超分处理中…")
        self._status.setText("视频超分处理中…")
        self._vm.start_enhance_video(
            out, start, end, scale=scale, backend=backend,
            strength=self._current_strength("vid"),
        )

    @Slot()
    def _open_result(self):
        if not self._result_path or not os.path.isfile(self._result_path):
            QMessageBox.warning(self, "提示", "还没有结果文件")
            return
        self._os_open(self._result_path)

    @Slot()
    def _open_result_folder(self):
        if not self._result_path or not os.path.isfile(self._result_path):
            QMessageBox.warning(self, "提示", "还没有结果文件")
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(self._result_path)])
        else:
            self._os_open(os.path.dirname(self._result_path))

    @staticmethod
    def _os_open(path: str):
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    @Slot(int, float, str)
    def _on_progress(self, _task_id: int, progress: float, msg: str):
        self._busy = True
        self._progress.setVisible(True)
        self._progress.setValue(int(progress))
        self._status.setText(msg)

    @Slot(int, str)
    def _on_finished(self, _task_id: int, output_path: str):
        self._set_busy(False)
        self._progress.setValue(100)
        self._result_path = output_path
        size = self._file_size_mb(output_path)

        if output_path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
            self._tabs.setCurrentIndex(0)
            self._btn_open_result.setEnabled(True)
            self._btn_folder_result.setEnabled(True)
            # 左边保持原图，右边加载超分结果
            if self._src_image_path:
                self._img_compare.set_original(self._src_image_path)
            ok = self._img_compare.set_result(output_path)
            src_sz = self._img_compare.left_view.native_size()
            dst_sz = self._img_compare.right_view.native_size()
            be = self._img_compare.right_view.load_backend()
            scale = self._current_scale("img")
            strength = self._current_strength("img")
            if ok and dst_sz[0] > 0:
                left = f"{src_sz[0]}×{src_sz[1]}" if src_sz[0] > 0 else "原图"
                self._img_meta.setText(
                    f"左 {left}  |  右 {dst_sz[0]}×{dst_sz[1]}"
                    f"  ·  {scale}×  ·  强度 {strength}%  ·  {size}"
                    f"  ·  解码 {be}"
                )
                self._status.setText(f"完成 · {os.path.basename(output_path)}")
            else:
                self._status.setText("完成，但右侧结果图加载失败，请打开文件查看")
                QMessageBox.warning(
                    self, "预览失败",
                    f"结果已保存：\n{output_path}\n\n请点「打开结果文件」。",
                )
            return

        self._tabs.setCurrentIndex(1)
        self._btn_open_vid.setEnabled(True)
        self._btn_folder_vid.setEnabled(True)
        try:
            fd, frame = tempfile.mkstemp(suffix=".png", prefix="sr_out_")
            os.close(fd)
            if self._vm.bridge:
                self._vm.bridge.extract_video_frame(output_path, 0.0, frame)
                self._vid_compare.set_result(frame)
                # 左侧保持当前预览；若为空再抽原片
                if not self._vid_compare.left_view.has_image():
                    self._refresh_video_preview()
                dst_sz = self._vid_compare.right_view.native_size()
                if dst_sz[0] > 0:
                    self._vid_info.setText(
                        f"左原片预览  |  右超分首帧 {dst_sz[0]}×{dst_sz[1]}"
                        f"  ·  {self._current_scale('vid')}×  ·  {size}"
                    )
            try:
                os.remove(frame)
            except OSError:
                pass
        except Exception as e:
            self._vid_compare.clear_result(f"结果已保存，预览失败: {e}")
        self._status.setText(f"完成 · {os.path.basename(output_path)}")

    @Slot(str)
    def _show_error(self, msg: str):
        if not self._busy:
            return
        self._set_busy(False)
        self._progress.setVisible(False)
        self._status.setText(f"失败: {msg}")
        QMessageBox.critical(self, "超分错误", msg)
