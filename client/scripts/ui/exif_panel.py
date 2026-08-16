"""图片 ExifTool 元数据：悬浮摘要 + 弹窗查看全部。"""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget,
)

from ui.theme import ACCENT, BORDER, ELEVATED, SIGNAL, SURFACE_2, TEXT, TEXT_MUTED


def _split_exif_sections(text: str) -> tuple[str, str]:
    """从 read_image_exif(full=True) 文本拆出常用 / 全部。"""
    raw = (text or "").strip()
    if not raw:
        return "", ""
    if "=== 常用信息 ===" in raw or "=== 全部标签 ===" in raw:
        highlight = ""
        full = ""
        if "=== 常用信息 ===" in raw:
            after = raw.split("=== 常用信息 ===", 1)[1]
            if "=== 全部标签 ===" in after:
                highlight, rest = after.split("=== 全部标签 ===", 1)
                full = rest.strip()
            else:
                highlight = after
            highlight = highlight.strip()
        elif "=== 全部标签 ===" in raw:
            full = raw.split("=== 全部标签 ===", 1)[1].strip()
        return highlight, full or raw
    return raw, raw


def _summary_lines(highlight: str, limit: int = 5) -> list[str]:
    lines: list[str] = []
    for line in (highlight or "").splitlines():
        s = line.strip()
        if not s or s.startswith("==="):
            continue
        if ":" in s:
            tag, val = s.split(":", 1)
            tag = tag.strip().split("]")[-1].strip()
            val = val.strip()
            if tag and val:
                lines.append(f"{tag}  {val}")
        else:
            lines.append(s)
        if len(lines) >= limit:
            break
    return lines


class ExifFullDialog(QDialog):
    """查看全部 EXIF 标签。"""

    def __init__(self, path: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("EXIF / 元数据")
        self.resize(640, 520)
        self.setModal(True)

        lay = QVBoxLayout(self)
        path_lbl = QLabel(path or "")
        path_lbl.setWordWrap(True)
        path_lbl.setStyleSheet(f"color: {TEXT_MUTED}; font-size: 12px;")
        lay.addWidget(path_lbl)

        body = QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(text or "（无元数据）")
        body.setStyleSheet(
            f"QTextEdit {{ background: {SURFACE_2}; color: {TEXT}; "
            f"font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px; "
            f"border: 1px solid {BORDER}; border-radius: 8px; padding: 8px; }}"
        )
        lay.addWidget(body, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_btn = buttons.button(QDialogButtonBox.Close)
        if close_btn:
            close_btn.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class ExifPanel(QFrame):
    """悬浮在图片右上角的 EXIF 摘要；点「全部」弹出完整数据。"""

    _ready = Signal(str, str)  # path, text

    def __init__(self, get_bridge, parent=None):
        super().__init__(parent)
        self._get_bridge = get_bridge
        self._req_path = ""
        self._path = ""
        self._full_text = ""
        self._highlight = ""

        self.setObjectName("ExifOverlay")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(228)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        self.setStyleSheet(
            f"""
            QFrame#ExifOverlay {{
                background: rgba(14, 17, 22, 210);
                border: 1px solid {BORDER};
                border-radius: 10px;
            }}
            QLabel#ExifTitle {{
                color: {SIGNAL};
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#ExifLine {{
                color: {TEXT};
                font-size: 11px;
            }}
            QLabel#ExifEmpty {{
                color: {TEXT_MUTED};
                font-size: 11px;
            }}
            QPushButton#ExifAllBtn {{
                background: {ELEVATED};
                color: {TEXT};
                border: 1px solid {BORDER};
                border-radius: 6px;
                padding: 4px 8px;
                font-size: 11px;
            }}
            QPushButton#ExifAllBtn:hover {{
                border-color: {ACCENT};
                color: {ACCENT};
            }}
            """
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(4)

        head = QHBoxLayout()
        title = QLabel("EXIF")
        title.setObjectName("ExifTitle")
        head.addWidget(title)
        head.addStretch()
        self._btn_all = QPushButton("全部")
        self._btn_all.setObjectName("ExifAllBtn")
        self._btn_all.setCursor(Qt.PointingHandCursor)
        self._btn_all.setToolTip("查看全部元数据")
        self._btn_all.clicked.connect(self._open_full)
        self._btn_all.setEnabled(False)
        head.addWidget(self._btn_all)
        lay.addLayout(head)

        self._body = QLabel("导入图片后显示")
        self._body.setObjectName("ExifEmpty")
        self._body.setWordWrap(True)
        self._body.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        lay.addWidget(self._body)

        self.setVisible(False)
        self._ready.connect(self._on_ready)

    def clear(self):
        self._req_path = ""
        self._path = ""
        self._full_text = ""
        self._highlight = ""
        self._set_body("导入图片后显示", empty=True)
        self._btn_all.setEnabled(False)
        self.setVisible(False)

    def load_path(self, path: str):
        path = (path or "").strip()
        if not path:
            self.clear()
            return
        self._req_path = path
        self._path = path
        self.setVisible(True)
        self._set_body("读取中…", empty=True)
        self._btn_all.setEnabled(False)
        self._full_text = ""
        self._highlight = ""

        bridge = self._get_bridge()
        if not bridge:
            self._set_body("媒体引擎未加载", empty=True)
            return
        if not getattr(bridge, "exiftool_available", False):
            self._set_body("未找到 ExifTool\n请运行 download_exiftool.bat", empty=True)
            return

        def run():
            try:
                text = bridge.read_image_exif(path, full=True)
            except Exception as e:
                text = f"读取失败: {e}"
            self._ready.emit(path, text)

        threading.Thread(target=run, daemon=True).start()

    def _set_body(self, text: str, *, empty: bool):
        self._body.setObjectName("ExifEmpty" if empty else "ExifLine")
        self._body.setText(text)
        self._body.style().unpolish(self._body)
        self._body.style().polish(self._body)
        self.adjustSize()

    @Slot(str, str)
    def _on_ready(self, path: str, text: str):
        if path != self._req_path:
            return
        if text.startswith(("读取失败", "未找到", "媒体引擎")):
            self._full_text = text
            self._highlight = ""
            self._set_body(text[:160], empty=True)
            self._btn_all.setEnabled(True)
            return

        highlight, full = _split_exif_sections(text)
        self._highlight = highlight
        self._full_text = text
        lines = _summary_lines(highlight or full, limit=5)
        if not lines:
            self._set_body("无常用 EXIF 字段", empty=True)
        else:
            self._set_body("\n".join(lines), empty=False)
        self._btn_all.setEnabled(True)

    @Slot()
    def _open_full(self):
        dlg = ExifFullDialog(
            self._path,
            self._full_text or self._highlight or "（无元数据）",
            parent=self.window(),
        )
        dlg.exec()

    def mouseDoubleClickEvent(self, event):
        if self._btn_all.isEnabled():
            self._open_full()
        super().mouseDoubleClickEvent(event)


def attach_exif_corner(host: QWidget, overlay: ExifPanel) -> QWidget:
    """EXIF 叠在右上角，不占纵向空间（用于左右对比预览）。"""
    wrap = QWidget()
    wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    grid = QGridLayout(wrap)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(0)
    host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    grid.addWidget(host, 0, 0)

    corner = QWidget()
    corner.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
    corner_lay = QVBoxLayout(corner)
    corner_lay.setContentsMargins(0, 10, 10, 0)
    corner_lay.setSpacing(0)
    corner_lay.addWidget(overlay)
    grid.addWidget(corner, 0, 0, Qt.AlignTop | Qt.AlignRight)
    return wrap


def attach_exif_overlay(host: QWidget, overlay: ExifPanel) -> QWidget:
    """host 与 EXIF 上下排列（去水印框选区不挡鼠标）。"""
    wrap = QWidget()
    wrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    lay = QVBoxLayout(wrap)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    lay.addWidget(host, 1)
    # 避免 Fixed 宽把整列挤成窄条
    overlay.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    overlay.setMaximumHeight(120)
    lay.addWidget(overlay, 0)
    return wrap
