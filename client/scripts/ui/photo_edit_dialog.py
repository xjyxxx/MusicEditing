"""非破坏照片编辑器：OpenGL 实时预览，失败时自动切 NumPy 软件渲染。"""

from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QSlider,
    QStackedLayout, QStackedWidget, QVBoxLayout, QWidget,
)

from core.image_loader import load_preview
from core.photo_edit_math import resolve_master_adjustments
from core.photo_numpy_renderer import render_rgba
from core.photo_sidecar import EditRecipe, load_sidecar, remove_sidecar, save_sidecar
from ui.gl_video_widget import GlVideoWidget


class PhotoEditDialog(QDialog):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path
        self._saved = False
        sidecar = load_sidecar(path)
        self._recipe = sidecar.recipe if sidecar else EditRecipe()
        self._source_image = QImage()
        self._software_image = QImage()
        self._gpu_attempted = False
        self._gpu_rendered = False
        self._zoom = 1.0
        self.setWindowTitle(f"编辑 · {os.path.basename(path)}")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.setMinimumSize(760, 520)
        self.resize(1120, 760)
        self._software_timer = QTimer(self)
        self._software_timer.setSingleShot(True)
        self._software_timer.setInterval(45)
        self._software_timer.timeout.connect(self._render_software)
        self._build_ui()

    @property
    def saved(self) -> bool:
        return self._saved

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        self._preview_stack = QStackedWidget()
        self._software = QLabel("正在加载照片…")
        self._software.setAlignment(Qt.AlignCenter)
        self._software.setMinimumSize(360, 260)
        self._software.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._software.setStyleSheet("background:#080A0E; color:#A1A1A6; border-radius:10px;")
        self._software.installEventFilter(self)
        self._viewer = GlVideoWidget()
        self._viewer.setMinimumSize(360, 260)
        self._viewer.installEventFilter(self)
        self._viewer.setCursor(Qt.ArrowCursor)
        self._viewer.set_placeholder("正在初始化 GPU 预览…")
        self._viewer.renderReady.connect(self._on_gpu_ready)
        self._viewer.renderFailed.connect(self._on_gpu_failed)
        self._preview_stack.addWidget(self._software)
        self._preview_stack.addWidget(self._viewer)
        # 两层同时保持可见：软件画面在上层立即显示，底层 GL 可并行创建上下文。
        # renderReady 到达后再把 GPU 层提升，避免初始化期间出现黑屏。
        self._preview_stack.layout().setStackingMode(QStackedLayout.StackAll)
        self._preview_stack.setCurrentWidget(self._software)

        preview_panel = QWidget()
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        preview_layout.addWidget(self._preview_stack, 1)
        zoom_row = QHBoxLayout()
        zoom_row.addStretch()
        self._zoom_out_button = QPushButton("−")
        self._zoom_out_button.setFixedWidth(34)
        self._zoom_out_button.setToolTip("缩小照片（也可在画面上滚轮向下）")
        self._zoom_out_button.clicked.connect(lambda: self._set_zoom(self._zoom / 1.2))
        zoom_row.addWidget(self._zoom_out_button)
        self._zoom_label = QLabel("100%")
        self._zoom_label.setAlignment(Qt.AlignCenter)
        self._zoom_label.setMinimumWidth(52)
        zoom_row.addWidget(self._zoom_label)
        self._zoom_in_button = QPushButton("+")
        self._zoom_in_button.setFixedWidth(34)
        self._zoom_in_button.setToolTip("放大照片（也可在画面上滚轮向上）")
        self._zoom_in_button.clicked.connect(lambda: self._set_zoom(self._zoom * 1.2))
        zoom_row.addWidget(self._zoom_in_button)
        fit_button = QPushButton("适合窗口")
        fit_button.clicked.connect(lambda: self._set_zoom(1.0))
        zoom_row.addWidget(fit_button)
        zoom_row.addStretch()
        preview_layout.addLayout(zoom_row)
        root.addWidget(preview_panel, 1)

        tools = QWidget()
        tools.setMinimumWidth(250)
        lay = QVBoxLayout(tools)
        heading = QLabel("非破坏编辑")
        heading.setObjectName("HomeTitle")
        lay.addWidget(heading)
        self._render_status = QLabel("正在准备预览…")
        self._render_status.setObjectName("MutedText")
        self._render_status.setWordWrap(True)
        lay.addWidget(self._render_status)
        self._sliders: dict[str, QSlider] = {}
        controls = (
            ("master_light", "光效大师", -100, 100, self._recipe.master_light, 100),
            ("master_color", "色彩大师", -100, 100, self._recipe.master_color, 100),
            ("exposure", "曝光", -30, 30, self._recipe.exposure, 10),
            ("contrast", "对比度", -100, 100, self._recipe.contrast, 100),
            ("saturation", "饱和度", -100, 100, self._recipe.saturation, 100),
            ("temperature", "色温", -100, 100, self._recipe.temperature, 100),
            ("perspective_horizontal", "水平透视", -100, 100, self._recipe.perspective_horizontal, 100),
            ("perspective_vertical", "垂直透视", -100, 100, self._recipe.perspective_vertical, 100),
            ("rotation", "旋转", -450, 450, self._recipe.rotation, 10),
        )
        for key, title, minimum, maximum, value, scale in controls:
            self._add_slider(lay, key, title, minimum, maximum, round(value * scale))
        lay.addStretch()
        hint = QLabel("大师滑块采用 Gaussian 权重分配；透视裁剪在投影空间验证，自动避开黑边。")
        hint.setWordWrap(True)
        hint.setObjectName("MutedText")
        lay.addWidget(hint)

        reset = QPushButton("重置配方")
        reset.clicked.connect(self._reset)
        lay.addWidget(reset)
        discard = QPushButton("移除旁路编辑")
        discard.clicked.connect(self._discard)
        lay.addWidget(discard)
        save = QPushButton("保存非破坏编辑")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save)
        lay.addWidget(save)

        tool_scroll = QScrollArea()
        tool_scroll.setObjectName("PhotoEditTools")
        tool_scroll.setFrameShape(QFrame.NoFrame)
        tool_scroll.setWidgetResizable(True)
        tool_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tool_scroll.setMinimumWidth(270)
        tool_scroll.setMaximumWidth(360)
        tool_scroll.setWidget(tools)
        root.addWidget(tool_scroll)

        preview = load_preview(self._path, max_side=1800)
        if preview.ok:
            self._source_image = preview.pixmap.toImage().convertToFormat(QImage.Format_RGBA8888).copy()
            self._render_software()
            self._viewer.set_qimage(self._source_image)
        else:
            self._software.setText("无法解码该照片")
            self._render_status.setText("图片解码失败；请检查文件格式或编解码插件。")
        self._apply()

    def _add_slider(self, layout, key: str, title: str, minimum: int, maximum: int, value: int) -> None:
        layout.addWidget(QLabel(title))
        row = QHBoxLayout()
        slider = QSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        value_label = QLabel()
        value_label.setMinimumWidth(48)
        slider.valueChanged.connect(lambda _value, name=key: self._on_adjusted(name))
        self._sliders[key] = slider
        setattr(self, f"_{key}_label", value_label)
        row.addWidget(slider, 1)
        row.addWidget(value_label)
        layout.addLayout(row)

    def eventFilter(self, watched, event) -> bool:
        if watched in (self._software, self._viewer) and event.type() == QEvent.Wheel:
            delta = event.angleDelta().y()
            if delta:
                self._set_zoom(self._zoom * (1.15 if delta > 0 else 1.0 / 1.15))
                event.accept()
                return True
        return super().eventFilter(watched, event)

    def _set_zoom(self, zoom: float) -> None:
        self._zoom = max(0.25, min(4.0, float(zoom)))
        self._zoom_label.setText(f"{round(self._zoom * 100):d}%")
        self._viewer.set_view_zoom(self._zoom)
        self._update_software_pixmap()
        self._zoom_out_button.setEnabled(self._zoom > 0.2501)
        self._zoom_in_button.setEnabled(self._zoom < 3.9999)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._gpu_attempted or self._source_image.isNull():
            return
        self._gpu_attempted = True
        # StackAll 让隐藏在软件画面下方的 QOpenGLWidget 也能初始化；成功前不暴露空白层。
        self._viewer.update()
        QTimer.singleShot(900, self._gpu_watchdog)

    def _gpu_watchdog(self) -> None:
        if not self._gpu_rendered:
            reason = self._viewer.gl_error or "OpenGL 首帧未在 900ms 内就绪"
            self._on_gpu_failed(reason)

    def _on_gpu_ready(self) -> None:
        self._gpu_rendered = True
        if self._has_geometry_adjustment():
            self._preview_stack.setCurrentWidget(self._software)
            self._render_status.setText("透视/旋转预览 · NumPy/OpenCV 安全裁剪")
        else:
            self._preview_stack.setCurrentWidget(self._viewer)
            self._render_status.setText("GPU 实时预览 · OpenGL 3.3")

    def _on_gpu_failed(self, reason: str) -> None:
        self._preview_stack.setCurrentWidget(self._software)
        compact = " ".join(str(reason or "OpenGL 不可用").split())
        if "setUniformValue" in compact:
            compact = "OpenGL 参数绑定失败"
        elif len(compact) > 140:
            compact = compact[:137] + "…"
        self._render_status.setText(f"GPU 不可用，已切换软件预览：{compact}")
        self._software_timer.start()

    def _current_recipe(self) -> EditRecipe:
        value = lambda key, scale: self._sliders[key].value() / float(scale)
        return EditRecipe(
            master_light=value("master_light", 100), master_color=value("master_color", 100),
            exposure=value("exposure", 10), contrast=value("contrast", 100),
            saturation=value("saturation", 100), temperature=value("temperature", 100),
            perspective_horizontal=value("perspective_horizontal", 100),
            perspective_vertical=value("perspective_vertical", 100), rotation=value("rotation", 10),
        ).normalized()

    def _has_geometry_adjustment(self) -> bool:
        recipe = self._current_recipe()
        return any(abs(value) > 1e-6 for value in (
            recipe.perspective_horizontal, recipe.perspective_vertical, recipe.rotation,
        ))

    def _on_adjusted(self, _name: str) -> None:
        self._apply()

    def _apply(self) -> None:
        recipe = self._current_recipe()
        tone = resolve_master_adjustments(
            light=recipe.master_light, color=recipe.master_color, exposure=recipe.exposure,
            contrast=recipe.contrast, saturation=recipe.saturation, temperature=recipe.temperature,
        )
        self._viewer.set_photo_adjustments(
            tone.exposure, tone.contrast, tone.saturation, tone.temperature,
        )
        for key, scale, decimals in (
            ("master_light", 100, 2), ("master_color", 100, 2), ("exposure", 10, 1),
            ("contrast", 100, 2), ("saturation", 100, 2), ("temperature", 100, 2),
            ("perspective_horizontal", 100, 2), ("perspective_vertical", 100, 2),
            ("rotation", 10, 1),
        ):
            number = self._sliders[key].value() / float(scale)
            getattr(self, f"_{key}_label").setText(f"{number:+.{decimals}f}")
        if self._has_geometry_adjustment():
            self._preview_stack.setCurrentWidget(self._software)
            self._render_status.setText("透视/旋转预览 · NumPy/OpenCV 安全裁剪")
        elif self._viewer.gl_ready:
            self._preview_stack.setCurrentWidget(self._viewer)
            self._render_status.setText("GPU 实时预览 · OpenGL 3.3")
        self._software_timer.start()

    def _render_software(self) -> None:
        if self._source_image.isNull():
            return
        image = self._source_image.convertToFormat(QImage.Format_RGBA8888)
        width, height, stride = image.width(), image.height(), image.bytesPerLine()
        raw = np.frombuffer(image.bits(), dtype=np.uint8, count=height * stride)
        rgba = raw.reshape(height, stride)[:, :width * 4].reshape(height, width, 4).copy()
        rendered = np.ascontiguousarray(render_rgba(rgba, self._current_recipe()))
        result = QImage(rendered.data, width, height, int(rendered.strides[0]), QImage.Format_RGBA8888)
        self._software_image = result.copy()
        self._update_software_pixmap()

    def _update_software_pixmap(self) -> None:
        if self._software_image.isNull():
            return
        size = self._software.size()
        available_width = max(1, size.width() - 12)
        available_height = max(1, size.height() - 12)
        pixmap = QPixmap.fromImage(self._software_image).scaled(
            max(1, round(available_width * self._zoom)),
            max(1, round(available_height * self._zoom)),
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
        self._software.setPixmap(pixmap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_software_pixmap()

    def _reset(self) -> None:
        for slider in self._sliders.values():
            slider.setValue(0)

    def _discard(self) -> None:
        remove_sidecar(self._path)
        self._saved = True
        self.accept()

    def _save(self) -> None:
        save_sidecar(self._path, self._current_recipe())
        self._saved = True
        self.accept()

    def done(self, result: int) -> None:
        self._software_timer.stop()
        self._viewer.cleanup_gl()
        super().done(result)
