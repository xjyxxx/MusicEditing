"""画质增强 / 4K 超分：左原图 | 右超分结果，中间一条细线；滚轮缩放、拖拽平移。"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QThread, QTimer, Signal, Slot, QObject
from PySide6.QtGui import QColor, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFrame, QGraphicsPixmapItem, QGraphicsScene,
    QGraphicsView, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSlider, QTabWidget,
    QVBoxLayout, QWidget,
)

from core.image_loader import load_preview, probe_size
from ui.elided_label import ElidedPathLabel
from ui.exif_panel import ExifPanel, attach_exif_overlay
from ui.theme import BG, PLAYER_BG, TEXT_MUTED, enhance_page_stylesheet
from ui.studio_kit import make_fixed_ai_hint, make_studio_hero, set_ai_hint_text, studio_page_stylesheet
from ui.workflow_link import TAB_WATERMARK, ask_video_handoff
from viewmodels.main_vm import MainViewModel

_STYLE = enhance_page_stylesheet() + "\n" + studio_page_stylesheet("EnhancePage")


class _FramePreviewWorker(QObject):
    finished = Signal(str, float)  # png_path, t
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


def _paint_scroll_dark(scroll: QScrollArea, body: QWidget) -> None:
    """强制滚动区/视口深色，避免 Fusion 默认白底；禁止内容按长文本横向撑开。"""
    from PySide6.QtGui import QPalette

    body.setMinimumWidth(0)
    body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    scroll.setMinimumWidth(0)
    scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    body.setObjectName("EnhanceScrollBody")
    body.setAttribute(Qt.WA_StyledBackground, True)
    scroll.setObjectName("EnhanceScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidget(body)
    bg = QColor(BG)
    for w in (scroll, scroll.viewport(), body):
        w.setAutoFillBackground(True)
        pal = w.palette()
        pal.setColor(QPalette.Window, bg)
        pal.setColor(QPalette.Base, bg)
        pal.setColor(QPalette.Button, bg)
        w.setPalette(pal)
    scroll.viewport().setStyleSheet(f"background: {BG};")
    body.setStyleSheet(f"background: {BG}; color: #E8EDF5;")


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
        self.setBackgroundBrush(QColor(8, 10, 14))
        self.setStyleSheet(f"background: {PLAYER_BG}; border: none;")
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
        t.setDefaultTextColor(QColor(TEXT_MUTED))
        self._scene.setBackgroundBrush(QColor(8, 10, 14))
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
        tip.setObjectName("MutedText")
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
    def __init__(self, vm: MainViewModel, handoff=None, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._handoff = handoff
        self._preview_png = ""
        self._result_path = ""
        self._src_image_path = ""
        self._busy = False
        self._preview_thread: QThread | None = None
        self._preview_worker: _FramePreviewWorker | None = None
        self._preview_debounce = QTimer(self)
        self._preview_debounce.setSingleShot(True)
        self._preview_debounce.setInterval(280)
        self._preview_debounce.timeout.connect(self._refresh_video_preview)
        self.setObjectName("EnhancePage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_STYLE)
        # 允许在窄窗口内收缩，避免子控件 sizeHint 把整窗撑开
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        root.addWidget(make_studio_hero(
            "画质增强",
            "图片/视频超分（左原图右结果）· 补帧 · 一键调色。视频超分默认试前 2 秒。",
            "超分",
        ))

        self._ai_hint = make_fixed_ai_hint()
        root.addWidget(self._ai_hint)
        self._refresh_ai_hint()
        vm.gpuNameChanged.connect(lambda _n: self._refresh_ai_hint())

        self._tabs = QTabWidget()
        self._tabs.setObjectName("EnhanceInnerTabs")
        self._tabs.setMinimumWidth(0)
        self._tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._tabs.addTab(self._build_image_tab(), "图片超分")
        self._tabs.addTab(self._build_video_tab(), "视频超分")
        self._tabs.addTab(self._build_interp_tab(), "视频补帧")
        self._tabs.addTab(self._build_grade_tab(), "一键调色")
        root.addWidget(self._tabs, 1)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status = ElidedPathLabel("就绪", object_name="InfoText")
        root.addWidget(self._status)

        vm.enhanceProgress.connect(self._on_progress)
        vm.enhanceFinished.connect(self._on_finished)
        vm.interpolateProgress.connect(self._on_progress)
        vm.interpolateFinished.connect(self._on_interp_finished)
        vm.colorGradeProgress.connect(self._on_progress)
        vm.colorGradeFinished.connect(self._on_grade_finished)
        vm.errorOccurred.connect(self._show_error)
        vm.videoLoaded.connect(self._on_video_loaded)
        vm.authTypeChanged.connect(lambda _a: self._refresh_license_gates())
        self._refresh_license_gates()

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

        tile_row = QHBoxLayout()
        tile_row.addWidget(QLabel("高级 tile"))
        tile = QComboBox()
        tile.addItem("自动（GPU≈512）", 0)
        tile.addItem("256（省显存）", 256)
        tile.addItem("384", 384)
        tile.addItem("512", 512)
        tile.addItem("768（大图）", 768)
        tile.setToolTip("Real-ESRGAN 分块；自动时有 CUDA EP 用 512，否则 384")
        tile_row.addWidget(tile)
        tile_row.addStretch()
        col.addLayout(tile_row)

        setattr(self, f"_{prefix}_mode_fast", fast)
        setattr(self, f"_{prefix}_mode_ai", ai)
        setattr(self, f"_{prefix}_scale_2", s2)
        setattr(self, f"_{prefix}_scale_4", s4)
        setattr(self, f"_{prefix}_strength", strength)
        setattr(self, f"_{prefix}_tile", tile)
        ai.toggled.connect(lambda _=False, p=prefix: self._refresh_license_gates())
        return box

    def _build_image_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self._img_path_label = ElidedPathLabel("未选择图片", object_name="MutedText")
        btn_import = QPushButton("导入图片")
        btn_import.setObjectName("GhostBtn")
        btn_import.clicked.connect(self._on_import_image)
        top.addWidget(self._img_path_label, 1)
        top.addWidget(btn_import)
        layout.addLayout(top)

        self._img_meta = QLabel("—")
        self._img_meta.setObjectName("MetaBadge")
        self._img_meta.setWordWrap(True)
        self._img_meta.setMaximumHeight(self._img_meta.fontMetrics().lineSpacing() * 2 + 16)
        layout.addWidget(self._img_meta)

        self._img_compare = SideBySideCompare()
        self._img_exif = ExifPanel(lambda: self._vm.bridge)
        layout.addWidget(attach_exif_overlay(self._img_compare, self._img_exif), 1)

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
        body = QWidget()
        layout = QVBoxLayout(body)

        top = QHBoxLayout()
        self._vid_path_label = ElidedPathLabel("未选择视频")
        btn_import = QPushButton("导入视频")
        btn_import.setObjectName("GhostBtn")
        btn_import.clicked.connect(self._on_import_video)
        btn_use = QPushButton("用当前视频")
        btn_use.setObjectName("GhostBtn")
        btn_use.setToolTip("使用其它页已导入的共享视频（无需重新选择文件）")
        btn_use.clicked.connect(self._on_use_current_video)
        top.addWidget(self._vid_path_label, 1)
        top.addWidget(btn_import)
        top.addWidget(btn_use)
        layout.addLayout(top)

        self._vid_info = QLabel("—")
        self._vid_info.setObjectName("MetaBadge")
        self._vid_info.setWordWrap(True)
        self._vid_info.setMaximumHeight(self._vid_info.fontMetrics().lineSpacing() * 2 + 16)
        layout.addWidget(self._vid_info)

        preview_row = QHBoxLayout()
        preview_row.addWidget(QLabel("预览时刻"))
        self._preview_slider = QSlider(Qt.Horizontal)
        self._preview_time_label = QLabel("0.0s")
        self._preview_time_label.setObjectName("PathLabel")
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
        self._start_label.setObjectName("PathLabel")
        start_row.addWidget(self._start_slider, 1)
        start_row.addWidget(self._start_label)
        end_row = QHBoxLayout()
        end_row.addWidget(QLabel("终点"))
        self._end_slider = QSlider(Qt.Horizontal)
        self._end_label = QLabel("2.0s")
        self._end_label.setObjectName("PathLabel")
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
        self._btn_send_wm = QPushButton("送去去水印")
        self._btn_send_wm.setObjectName("GhostBtn")
        self._btn_send_wm.setEnabled(False)
        self._btn_send_wm.setToolTip("将超分结果导入「去水印」")
        self._btn_send_wm.clicked.connect(self._on_send_to_watermark)
        actions.addWidget(self._btn_run_vid)
        actions.addWidget(self._btn_open_vid)
        actions.addWidget(self._btn_folder_vid)
        actions.addWidget(self._btn_send_wm)
        actions.addStretch()
        layout.addLayout(actions)

        scroll = QScrollArea()
        _paint_scroll_dark(scroll, body)
        outer.addWidget(scroll)
        return page

    def _build_interp_tab(self) -> QWidget:
        """视频补帧：FFmpeg minterpolate，与超分并列。"""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        layout = QVBoxLayout(body)

        tip = QLabel(
            "把 24/30fps 提到 48/60fps（或 4×）。"
            "默认「快速」模式（帧混合，明显更快）；「精细」用运动补偿，更顺但很慢。"
            "建议先「试 5/15 秒」；全程会随片长变慢。补帧会重编码，锐度可能略逊原片。"
        )
        tip.setObjectName("HintLabel")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self._interp_path_label = ElidedPathLabel(
            "未选择视频（请导入或「用当前视频」）"
        )
        layout.addWidget(self._interp_path_label)

        row = QHBoxLayout()
        btn_use = QPushButton("用当前视频")
        btn_use.setObjectName("GhostBtn")
        btn_use.clicked.connect(self._on_use_current_for_interp)
        btn_import = QPushButton("导入视频")
        btn_import.setObjectName("GhostBtn")
        btn_import.clicked.connect(self._on_import_video)
        row.addWidget(btn_import)
        row.addWidget(btn_use)
        row.addStretch()
        layout.addLayout(row)

        fac_box = QGroupBox("倍率")
        fac_l = QHBoxLayout(fac_box)
        self._interp_x2 = QRadioButton("2×（如 30→60fps）")
        self._interp_x4 = QRadioButton("4×（如 30→120fps）")
        self._interp_x2.setChecked(True)
        self._interp_fac_group = QButtonGroup(self)
        self._interp_fac_group.addButton(self._interp_x2)
        self._interp_fac_group.addButton(self._interp_x4)
        fac_l.addWidget(self._interp_x2)
        fac_l.addWidget(self._interp_x4)
        fac_l.addStretch()
        layout.addWidget(fac_box)

        q_box = QGroupBox("速度 / 质量")
        q_l = QHBoxLayout(q_box)
        self._interp_q_fast = QRadioButton("快速（推荐）")
        self._interp_q_fine = QRadioButton("精细（慢）")
        self._interp_q_fast.setChecked(True)
        self._interp_q_fast.setToolTip("帧混合插值，速度快，适合先出片")
        self._interp_q_fine.setToolTip("运动补偿 MCI，更顺滑但可能慢十几倍")
        self._interp_q_group = QButtonGroup(self)
        self._interp_q_group.addButton(self._interp_q_fast)
        self._interp_q_group.addButton(self._interp_q_fine)
        q_l.addWidget(self._interp_q_fast)
        q_l.addWidget(self._interp_q_fine)
        q_l.addStretch()
        layout.addWidget(q_box)

        be_box = QGroupBox("补帧引擎")
        be_l = QHBoxLayout(be_box)
        self._interp_be_ffmpeg = QRadioButton("FFmpeg（默认）")
        self._interp_be_rife = QRadioButton("RIFE ONNX（可选）")
        self._interp_be_ffmpeg.setChecked(True)
        self._interp_be_rife.setToolTip(
            "需 models/rife.onnx；失败自动回退 FFmpeg minterpolate"
        )
        self._interp_be_group = QButtonGroup(self)
        self._interp_be_group.addButton(self._interp_be_ffmpeg)
        self._interp_be_group.addButton(self._interp_be_rife)
        be_l.addWidget(self._interp_be_ffmpeg)
        be_l.addWidget(self._interp_be_rife)
        be_l.addStretch()
        layout.addWidget(be_box)

        range_box = QGroupBox("处理时间段（默认试 15 秒，可改全程）")
        rc = QVBoxLayout(range_box)
        start_row = QHBoxLayout()
        start_row.addWidget(QLabel("起点"))
        self._interp_start_slider = QSlider(Qt.Horizontal)
        self._interp_start_label = QLabel("0.0s")
        start_row.addWidget(self._interp_start_slider, 1)
        start_row.addWidget(self._interp_start_label)
        end_row = QHBoxLayout()
        end_row.addWidget(QLabel("终点"))
        self._interp_end_slider = QSlider(Qt.Horizontal)
        self._interp_end_label = QLabel("—")
        end_row.addWidget(self._interp_end_slider, 1)
        end_row.addWidget(self._interp_end_label)
        rc.addLayout(start_row)
        rc.addLayout(end_row)
        quick = QHBoxLayout()
        for label, secs in (("试 2 秒", 2), ("试 5 秒", 5), ("试 15 秒", 15), ("全程", 0)):
            b = QPushButton(label)
            b.setObjectName("PresetBtn")
            b.clicked.connect(lambda _=False, s=secs: self._set_interp_range_preset(s))
            quick.addWidget(b)
        quick.addStretch()
        rc.addLayout(quick)
        self._interp_range_hint = QLabel("将处理：15.0 秒")
        self._interp_range_hint.setObjectName("MetaBadge")
        rc.addWidget(self._interp_range_hint)
        layout.addWidget(range_box)
        self._interp_start_slider.valueChanged.connect(self._on_interp_range_changed)
        self._interp_end_slider.valueChanged.connect(self._on_interp_range_changed)

        self._interp_info = QLabel("—")
        self._interp_info.setObjectName("MetaBadge")
        layout.addWidget(self._interp_info)

        actions = QHBoxLayout()
        self._btn_run_interp = QPushButton("开始补帧")
        self._btn_run_interp.setObjectName("PrimaryBtn")
        self._btn_run_interp.clicked.connect(self._on_run_interp)
        self._btn_open_interp = QPushButton("打开结果文件")
        self._btn_open_interp.setObjectName("GhostBtn")
        self._btn_open_interp.setEnabled(False)
        self._btn_open_interp.clicked.connect(self._open_result)
        self._btn_folder_interp = QPushButton("打开文件夹")
        self._btn_folder_interp.setObjectName("GhostBtn")
        self._btn_folder_interp.setEnabled(False)
        self._btn_folder_interp.clicked.connect(self._open_result_folder)
        actions.addWidget(self._btn_run_interp)
        actions.addWidget(self._btn_open_interp)
        actions.addWidget(self._btn_folder_interp)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addStretch()

        scroll = QScrollArea()
        _paint_scroll_dark(scroll, body)
        outer.addWidget(scroll)
        return page

    def _build_grade_tab(self) -> QWidget:
        """一键调色：与 FrameProcessor warm/cool/vintage 同层，导出走 lut3d。"""
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        layout = QVBoxLayout(body)

        tip = QLabel(
            "电影暖调 / 冷调 / 复古：与首页播放器滤镜同一套矩阵。"
            "预览用 OpenCV；导出图片同矩阵，视频用 FFmpeg lut3d（.cube）。"
            "也可在首页滤镜下拉直接预览播放效果。"
        )
        tip.setObjectName("HintLabel")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        top = QHBoxLayout()
        self._grade_path_label = ElidedPathLabel("未选择文件")
        btn_img = QPushButton("导入图片")
        btn_img.setObjectName("GhostBtn")
        btn_img.clicked.connect(self._on_grade_import_image)
        btn_vid = QPushButton("导入视频")
        btn_vid.setObjectName("GhostBtn")
        btn_vid.clicked.connect(self._on_grade_import_video)
        btn_use = QPushButton("用当前视频")
        btn_use.setObjectName("GhostBtn")
        btn_use.clicked.connect(self._on_grade_use_current)
        top.addWidget(self._grade_path_label, 1)
        top.addWidget(btn_img)
        top.addWidget(btn_vid)
        top.addWidget(btn_use)
        layout.addLayout(top)

        preset_box = QGroupBox("调色预设（LUT）")
        pr = QHBoxLayout(preset_box)
        self._grade_preset = QComboBox()
        from core.color_grade import list_presets
        for key, label in list_presets():
            self._grade_preset.addItem(label, key)
        pr.addWidget(QLabel("风格"))
        pr.addWidget(self._grade_preset, 1)
        btn_prev = QPushButton("刷新预览")
        btn_prev.setObjectName("GhostBtn")
        btn_prev.setToolTip("对当前图片或视频预览帧套用调色（不写文件）")
        btn_prev.clicked.connect(self._on_grade_preview)
        pr.addWidget(btn_prev)
        layout.addWidget(preset_box)

        self._grade_compare = SideBySideCompare()
        self._grade_compare.clear_all("导入图片/视频", "预览或导出后显示调色结果")
        layout.addWidget(self._grade_compare, 1)

        range_box = QGroupBox("视频导出时间段（图片忽略）")
        rc = QVBoxLayout(range_box)
        start_row = QHBoxLayout()
        start_row.addWidget(QLabel("起点"))
        self._grade_start = QSlider(Qt.Horizontal)
        self._grade_start_lbl = QLabel("0.0s")
        start_row.addWidget(self._grade_start, 1)
        start_row.addWidget(self._grade_start_lbl)
        end_row = QHBoxLayout()
        end_row.addWidget(QLabel("终点"))
        self._grade_end = QSlider(Qt.Horizontal)
        self._grade_end_lbl = QLabel("—")
        end_row.addWidget(self._grade_end, 1)
        end_row.addWidget(self._grade_end_lbl)
        rc.addLayout(start_row)
        rc.addLayout(end_row)
        quick = QHBoxLayout()
        for label, secs in (("试 5 秒", 5), ("试 15 秒", 15), ("全程", 0)):
            b = QPushButton(label)
            b.setObjectName("PresetBtn")
            b.clicked.connect(lambda _=False, s=secs: self._set_grade_range_preset(s))
            quick.addWidget(b)
        quick.addStretch()
        rc.addLayout(quick)
        layout.addWidget(range_box)
        self._grade_start.valueChanged.connect(self._on_grade_range_changed)
        self._grade_end.valueChanged.connect(self._on_grade_range_changed)

        self._grade_info = QLabel("—")
        self._grade_info.setObjectName("MetaBadge")
        layout.addWidget(self._grade_info)

        actions = QHBoxLayout()
        self._btn_run_grade = QPushButton("导出调色结果")
        self._btn_run_grade.setObjectName("PrimaryBtn")
        self._btn_run_grade.clicked.connect(self._on_run_grade)
        self._btn_open_grade = QPushButton("打开结果文件")
        self._btn_open_grade.setObjectName("GhostBtn")
        self._btn_open_grade.setEnabled(False)
        self._btn_open_grade.clicked.connect(self._open_result)
        self._btn_folder_grade = QPushButton("打开文件夹")
        self._btn_folder_grade.setObjectName("GhostBtn")
        self._btn_folder_grade.setEnabled(False)
        self._btn_folder_grade.clicked.connect(self._open_result_folder)
        self._btn_grade_to_player = QPushButton("套到播放器滤镜")
        self._btn_grade_to_player.setObjectName("GhostBtn")
        self._btn_grade_to_player.setToolTip("把当前预设同步到首页播放器 OpenCV 滤镜（需重新编译含 warm/cool/vintage）")
        self._btn_grade_to_player.clicked.connect(self._on_grade_to_player)
        actions.addWidget(self._btn_run_grade)
        actions.addWidget(self._btn_open_grade)
        actions.addWidget(self._btn_folder_grade)
        actions.addWidget(self._btn_grade_to_player)
        actions.addStretch()
        layout.addLayout(actions)

        self._grade_src_path = ""
        self._grade_is_image = False

        scroll = QScrollArea()
        _paint_scroll_dark(scroll, body)
        outer.addWidget(scroll)
        return page

    def _refresh_ai_hint(self):
        fn = getattr(self._vm, "ai_runtime_hint", None)
        set_ai_hint_text(getattr(self, "_ai_hint", None), fn() if callable(fn) else "")

    def _refresh_license_gates(self):
        """试用：灰显 AI 4×；正式版全开。"""
        self._refresh_ai_hint()
        licensed = bool(getattr(self._vm, "is_licensed", False))
        tip = "" if licensed else "正式版可用 · 请到「个人中心」兑换卡密"
        for prefix in ("img", "vid"):
            s4 = getattr(self, f"_{prefix}_scale_4", None)
            ai = getattr(self, f"_{prefix}_mode_ai", None)
            if s4 is None:
                continue
            # 仅当选 AI 时限制 4×；快速 OpenCV 的 4× 仍可用
            need_gate = (not licensed) and (ai is None or ai.isChecked())
            s4.setEnabled(not need_gate)
            s4.setToolTip(tip if need_gate else "AI 超分 4×")
            if need_gate and s4.isChecked():
                s2 = getattr(self, f"_{prefix}_scale_2", None)
                if s2:
                    s2.setChecked(True)

    def _current_scale(self, prefix: str) -> int:
        return 4 if getattr(self, f"_{prefix}_scale_4").isChecked() else 2

    def _current_tile(self, prefix: str) -> int:
        combo = getattr(self, f"_{prefix}_tile", None)
        if combo is None:
            return 0
        return int(combo.currentData() or 0)

    def _apply_tile(self, prefix: str) -> None:
        try:
            self._vm.get_app_state().enhance_params.tile = self._current_tile(prefix)
        except Exception:
            pass

    def _current_backend(self, prefix: str) -> str:
        return "opencv" if getattr(self, f"_{prefix}_mode_fast").isChecked() else "realesrgan"

    def _current_strength(self, prefix: str) -> int:
        return int(getattr(self, f"_{prefix}_strength").value())

    def _set_busy(self, busy: bool):
        self._busy = busy
        for btn in (
            getattr(self, "_btn_run_img", None),
            getattr(self, "_btn_run_vid", None),
            getattr(self, "_btn_run_interp", None),
            getattr(self, "_btn_run_grade", None),
        ):
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

    def _set_interp_range_preset(self, seconds: int):
        """补帧专用区间；默认全程，与超分「试 2 秒」独立。"""
        video = self._vm.get_app_state().current_video
        if not video or not getattr(self, "_interp_start_slider", None):
            return
        max_ms = max(1, int(video.duration_sec * 1000))
        self._interp_start_slider.setValue(0)
        self._interp_end_slider.setValue(
            max_ms if seconds <= 0 else min(max_ms, seconds * 1000)
        )

    @Slot()
    def _on_interp_range_changed(self):
        video = self._vm.get_app_state().current_video
        if not video or not getattr(self, "_interp_start_slider", None):
            return
        start = self._interp_start_slider.value() / 1000.0
        end = self._interp_end_slider.value() / 1000.0
        if end <= start:
            end = min(video.duration_sec, start + 0.1)
            self._interp_end_slider.blockSignals(True)
            self._interp_end_slider.setValue(int(end * 1000))
            self._interp_end_slider.blockSignals(False)
        self._interp_start_label.setText(f"{start:.1f}s")
        self._interp_end_label.setText(f"{end:.1f}s")
        dur = max(0.0, end - start)
        full = abs(dur - float(video.duration_sec or 0.0)) < 0.15 and start < 0.05
        self._interp_range_hint.setText(
            "将处理：全程" if full else f"将处理：{dur:.1f} 秒（{start:.1f}s → {end:.1f}s）"
        )

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
            QMessageBox.warning(self, "画质增强", "图片文件不存在")
            return False
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
        return True

    def focus_video_tab(self) -> None:
        self._tabs.setCurrentIndex(1)

    @Slot()
    def _on_import_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频", "",
            "视频 (*.mp4 *.mov *.mkv *.avi *.webm);;所有文件 (*.*)",
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
    def _on_send_to_watermark(self):
        if not self._handoff:
            return
        path = self._result_path
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "提示", "请先完成视频超分，再送去去水印。")
            return
        if path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
            QMessageBox.information(self, "提示", "当前结果是图片；请对视频结果使用「送去去水印」。")
            return
        self._handoff(path, TAB_WATERMARK)

    @Slot(object)
    def _on_video_loaded(self, video):
        if not video:
            return
        self._vid_path_label.setText(video.file_path)
        self._vid_info.setText(
            f"原片  {video.width}×{video.height}  ·  {video.duration_sec:.1f}s  ·  "
            f"{video.fps:.1f} fps  ·  {self._file_size_mb(video.file_path)}"
        )
        if getattr(self, "_interp_path_label", None):
            self._interp_path_label.setText(video.file_path)
        fps = float(video.fps or 25.0)
        if getattr(self, "_interp_info", None):
            self._interp_info.setText(
                f"{video.width}×{video.height}  ·  源 {fps:.1f} fps  ·  "
                f"2×→{fps * 2:.0f} / 4×→{fps * 4:.0f}  ·  {self._file_size_mb(video.file_path)}"
            )
        max_ms = max(1, int(video.duration_sec * 1000))
        for s in (self._preview_slider, self._start_slider, self._end_slider):
            s.blockSignals(True)
            s.setMaximum(max_ms)
            s.blockSignals(False)
        self._start_slider.setValue(0)
        self._end_slider.setValue(min(max_ms, 2000))  # 超分默认试 2 秒
        self._on_range_changed()
        # 补帧默认试 15 秒（与超分区间独立；全程可选手动点「全程」）
        if getattr(self, "_interp_start_slider", None):
            for s in (self._interp_start_slider, self._interp_end_slider):
                s.blockSignals(True)
                s.setMaximum(max_ms)
                s.blockSignals(False)
            self._interp_start_slider.setValue(0)
            self._interp_end_slider.setValue(min(max_ms, 15000))
            self._on_interp_range_changed()
        if getattr(self, "_grade_start", None):
            self._grade_src_path = video.file_path
            self._grade_is_image = False
            self._grade_path_label.setText(video.file_path)
            for s in (self._grade_start, self._grade_end):
                s.blockSignals(True)
                s.setMaximum(max_ms)
                s.blockSignals(False)
            self._grade_start.setValue(0)
            self._grade_end.setValue(min(max_ms, 15000))
            self._on_grade_range_changed()
            self._grade_info.setText(
                f"视频  {video.width}×{video.height}  ·  {video.duration_sec:.1f}s"
            )
        self._refresh_video_preview()
        self._vid_compare.clear_result("超分完成后显示结果首帧")
        self._btn_open_vid.setEnabled(False)
        self._btn_folder_vid.setEnabled(False)
        if getattr(self, "_btn_send_wm", None):
            self._btn_send_wm.setEnabled(False)
        if getattr(self, "_btn_open_interp", None):
            self._btn_open_interp.setEnabled(False)
            self._btn_folder_interp.setEnabled(False)

    @Slot()
    def _on_preview_slider(self):
        self._preview_time_label.setText(f"{self._preview_slider.value() / 1000.0:.1f}s")
        # 拖动只改时间标签；松手/停顿后再抽帧，避免卡主线程
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
        self._end_label.setText(
            "全程" if end >= video.duration_sec - 0.05 else f"{end:.1f}s"
        )
        self._vm.update_enhance_range(start, end)

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
            fd, out_png = tempfile.mkstemp(suffix=".png", prefix="sr_prev_")
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
            th.finished.connect(self._clear_preview_thread)
            self._preview_thread = th
            self._preview_worker = worker
            th.start()
        except Exception as e:
            self._show_error(f"预览失败: {e}")

    @Slot(str, float)
    def _on_preview_frame_ready(self, png: str, t: float):
        if png and os.path.isfile(png):
            if self._vid_compare.set_original(png):
                self._status.setText(f"左侧预览 @ {t:.1f}s")

    @Slot(str)
    def _on_preview_frame_failed(self, msg: str):
        self._show_error(f"预览失败: {msg}")

    @Slot()
    def _clear_preview_thread(self):
        self._preview_thread = None
        self._preview_worker = None

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
        self._apply_tile("img")
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
        self._apply_tile("vid")
        self._vm.start_enhance_video(
            out, start, end, scale=scale, backend=backend,
            strength=self._current_strength("vid"),
        )

    def _grade_preset_key(self) -> str:
        return str(self._grade_preset.currentData() or "warm")

    def _set_grade_range_preset(self, seconds: int):
        video = self._vm.get_app_state().current_video
        if not video or not getattr(self, "_grade_start", None):
            return
        max_ms = max(1, int(video.duration_sec * 1000))
        self._grade_start.setValue(0)
        self._grade_end.setValue(max_ms if seconds <= 0 else min(max_ms, seconds * 1000))

    @Slot()
    def _on_grade_range_changed(self):
        if not getattr(self, "_grade_start", None):
            return
        start = self._grade_start.value() / 1000.0
        end = self._grade_end.value() / 1000.0
        if end <= start:
            end = start + 0.1
            self._grade_end.blockSignals(True)
            self._grade_end.setValue(int(end * 1000))
            self._grade_end.blockSignals(False)
        self._grade_start_lbl.setText(f"{start:.1f}s")
        self._grade_end_lbl.setText(f"{end:.1f}s")

    @Slot()
    def _on_grade_import_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)",
        )
        if not path:
            return
        self._grade_src_path = path
        self._grade_is_image = True
        self._grade_path_label.setText(path)
        self._grade_compare.set_original(path)
        self._grade_compare.clear_result("预览或导出后显示")
        w, h = probe_size(path)
        self._grade_info.setText(
            f"图片  {w}×{h}" if w > 0 else f"图片  {self._file_size_mb(path)}"
        )
        self._status.setText(f"调色素材: {os.path.basename(path)}")

    @Slot()
    def _on_grade_import_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频", "",
            "视频 (*.mp4 *.mov *.mkv *.avi *.webm);;所有文件 (*.*)",
        )
        if path:
            self._vm.import_video(path)
            self._tabs.setCurrentIndex(3)

    @Slot()
    def _on_grade_use_current(self):
        video = self._vm.get_app_state().current_video
        if not video or not video.file_path:
            QMessageBox.information(self, "提示", "尚未导入视频。")
            return
        self._tabs.setCurrentIndex(3)
        self._on_video_loaded(video)

    @Slot()
    def _on_grade_preview(self):
        """本地 OpenCV 预览（图片或缩略帧；缩边 + JPEG 临时文件加快刷新）。"""
        src = self._grade_src_path
        if not src or not os.path.isfile(src):
            QMessageBox.information(self, "提示", "请先导入图片或视频。")
            return
        preset = self._grade_preset_key()
        try:
            from core.color_grade import apply_grade_opencv_bgr, PRESETS
            import cv2
            import numpy as np
            import tempfile

            if self._grade_is_image:
                data = np.fromfile(src, dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_COLOR)
                self._grade_compare.set_original(src)
            else:
                t = self._grade_start.value() / 1000.0
                thumb = self._vm.bridge.extract_thumbnail(
                    src, t, max_width=720, use_cache=True,
                )
                # PPM / 中文路径
                data = np.fromfile(thumb, dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_COLOR)
                if img is None:
                    img = cv2.imread(thumb, cv2.IMREAD_COLOR)
                self._grade_compare.set_original(thumb)
            if img is None:
                raise RuntimeError("解码失败")
            out = apply_grade_opencv_bgr(img, preset, max_side=960)
            tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            tmp.close()
            ok, buf = cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            if not ok:
                raise RuntimeError("编码预览失败")
            buf.tofile(tmp.name)
            self._grade_compare.set_result(tmp.name)
            self._status.setText(f"预览: {PRESETS.get(preset, preset)}")
        except Exception as e:
            try:
                self._grade_preview_ffmpeg(src, preset)
            except Exception as e2:
                QMessageBox.warning(self, "预览失败", f"{e}\n{e2}")

    def _grade_preview_ffmpeg(self, src: str, preset: str):
        from core.color_grade import grade_with_ffmpeg, PRESETS
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        t0 = self._grade_start.value() / 1000.0 if not self._grade_is_image else 0.0
        grade_with_ffmpeg(src, tmp.name, preset, start_sec=t0, end_sec=t0 + 0.08)
        if not self._grade_is_image:
            try:
                thumb = self._vm.bridge.extract_thumbnail(
                    src, t0, max_width=960, use_cache=False,
                )
                self._grade_compare.set_original(thumb)
            except Exception:
                pass
        else:
            self._grade_compare.set_original(src)
        self._grade_compare.set_result(tmp.name)
        self._status.setText(f"预览: {PRESETS.get(preset, preset)}")

    @Slot()
    def _on_run_grade(self):
        src = self._grade_src_path
        if not src or not os.path.isfile(src):
            QMessageBox.warning(self, "提示", "请先导入图片或视频")
            return
        preset = self._grade_preset_key()
        stem = Path(src).stem
        if self._grade_is_image:
            default = str(Path(src).with_name(f"{stem}_{preset}.png"))
            filt = "PNG (*.png);;JPEG (*.jpg);;所有文件 (*.*)"
        else:
            default = str(Path(src).with_name(f"{stem}_{preset}.mp4"))
            filt = "MP4 (*.mp4);;所有文件 (*.*)"
        out, _ = QFileDialog.getSaveFileName(self, "保存调色结果", default, filt)
        if not out:
            return
        start = self._grade_start.value() / 1000.0
        end = self._grade_end.value() / 1000.0
        self._result_path = out
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._set_busy(True)
        self._grade_compare.clear_result("调色导出中…")
        self._status.setText(f"调色导出（{preset}）…")
        self._vm.start_color_grade(
            src, out, preset,
            start_sec=0.0 if self._grade_is_image else start,
            end_sec=0.0 if self._grade_is_image else end,
        )

    @Slot(int, str)
    def _on_grade_finished(self, _task_id: int, output_path: str):
        self._set_busy(False)
        self._progress.setValue(100)
        self._result_path = output_path
        self._tabs.setCurrentIndex(3)
        self._btn_open_grade.setEnabled(True)
        self._btn_folder_grade.setEnabled(True)
        if output_path.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
            if self._grade_src_path:
                self._grade_compare.set_original(self._grade_src_path)
            self._grade_compare.set_result(output_path)
        self._status.setText(f"调色完成 · {os.path.basename(output_path)}")
        QMessageBox.information(self, "调色完成", f"已保存：\n{output_path}")

    @Slot()
    def _on_grade_to_player(self):
        preset = self._grade_preset_key()
        # 通过 MainWindow 的手递：emit 不够，直接找顶层
        win = self.window()
        home = getattr(win, "_home_page", None)
        if home and hasattr(home, "apply_opencv_filter"):
            if home.apply_opencv_filter(preset):
                self._status.setText(f"已套到播放器滤镜: {preset}")
                return
        QMessageBox.information(
            self, "播放器滤镜",
            f"请切换到首页，在滤镜下拉选择对应项（{preset}）。\n"
            "若没有暖调/冷调/复古，请重新编译 media_player（build_x64.bat）。",
        )

    @Slot()
    def _on_use_current_for_interp(self):
        video = self._vm.get_app_state().current_video
        if not video or not video.file_path:
            QMessageBox.information(self, "提示", "尚未导入视频，请先导入。")
            return
        self._tabs.setCurrentIndex(2)
        self._on_video_loaded(video)
        self._status.setText(f"补帧使用: {os.path.basename(video.file_path)}")

    @Slot()
    def _on_run_interp(self):
        video = self._vm.get_app_state().current_video
        if not video:
            QMessageBox.warning(self, "提示", "请先导入视频")
            return
        factor = 4 if self._interp_x4.isChecked() else 2
        quality = "quality" if self._interp_q_fine.isChecked() else "fast"
        start = self._interp_start_slider.value() / 1000.0
        end = self._interp_end_slider.value() / 1000.0
        if end <= start:
            QMessageBox.warning(self, "提示", "请设置有效的处理时间段（终点大于起点）")
            return
        dur = end - start
        full = abs(dur - float(video.duration_sec or 0.0)) < 0.15 and start < 0.05
        stem = Path(video.file_path).stem
        out, _ = QFileDialog.getSaveFileName(
            self, "保存补帧视频",
            str(Path(video.file_path).with_name(f"{stem}_interp_x{factor}.mp4")),
            "MP4 (*.mp4);;所有文件 (*.*)",
        )
        if not out:
            return
        if quality == "quality" and (full or dur > 20):
            ans = QMessageBox.question(
                self, "精细模式较慢",
                "「精细」用运动补偿，可能比「快速」慢很多。\n"
                "建议先用「快速」或缩短到「试 5 秒」。是否仍用精细？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        elif full and (video.duration_sec or 0) > 120:
            ans = QMessageBox.question(
                self, "全程补帧",
                f"将处理全程约 {video.duration_sec:.0f} 秒。是否继续？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        self._result_path = out
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._set_busy(True)
        range_txt = "全程" if full else f"{dur:.1f}s"
        mode_txt = "精细" if quality == "quality" else "快速"
        be = "rife" if getattr(self, "_interp_be_rife", None) and self._interp_be_rife.isChecked() else "ffmpeg"
        eng = "RIFE" if be == "rife" else mode_txt
        self._status.setText(f"补帧处理中（{eng} {factor}x · {range_txt}）…")
        self._vm.start_interpolate_video(
            out, factor=factor, start_sec=start, end_sec=end, quality=quality, backend=be,
        )

    @Slot(int, str)
    def _on_interp_finished(self, _task_id: int, output_path: str):
        self._set_busy(False)
        self._progress.setValue(100)
        self._result_path = output_path
        self._tabs.setCurrentIndex(2)
        self._btn_open_interp.setEnabled(True)
        self._btn_folder_interp.setEnabled(True)
        self._status.setText(f"补帧完成 · {os.path.basename(output_path)}")
        QMessageBox.information(
            self, "补帧完成",
            f"已保存：\n{output_path}\n\n可用首页播放器打开查看流畅度。",
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
        if getattr(self, "_btn_send_wm", None):
            self._btn_send_wm.setEnabled(True)
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
        tab = ask_video_handoff(
            self,
            "超分完成",
            f"视频已保存：\n{output_path}\n\n可继续送去去水印（无需重新导入）。",
            [("送去去水印", TAB_WATERMARK)],
        )
        if tab is not None and self._handoff:
            self._handoff(output_path, tab)

    @Slot(str)
    def _show_error(self, msg: str):
        if not self._busy:
            return
        self._set_busy(False)
        self._progress.setVisible(False)
        self._status.setText(f"失败: {msg}")
        QMessageBox.critical(self, "超分错误", msg)
