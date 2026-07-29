"""图片 ExifTool 元数据面板（异步读取，不阻塞 UI）。"""

from __future__ import annotations

import threading

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout,
)


class ExifPanel(QGroupBox):
    """显示 ExifTool 输出；load_path() 在后台线程调用 bridge.read_image_exif。"""

    _ready = Signal(str, str)  # path, text

    def __init__(self, get_bridge, parent=None):
        super().__init__("EXIF / 元数据（ExifTool）", parent)
        self._get_bridge = get_bridge
        self._req_path = ""
        self._path = ""

        lay = QVBoxLayout(self)
        tip_row = QHBoxLayout()
        self._hint = QLabel("导入图片后显示拍摄参数、时间、GPS 等")
        self._hint.setStyleSheet("color:#9a9ab0; font-size:12px;")
        self._hint.setWordWrap(True)
        tip_row.addWidget(self._hint, 1)
        self._btn_refresh = QPushButton("刷新")
        self._btn_refresh.setFixedWidth(64)
        self._btn_refresh.clicked.connect(self._on_refresh)
        tip_row.addWidget(self._btn_refresh)
        lay.addLayout(tip_row)

        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlaceholderText("尚无元数据…")
        self._text.setMinimumHeight(120)
        self._text.setMaximumHeight(220)
        self._text.setStyleSheet(
            "QTextEdit { background:#1e1e28; color:#d8d8e8; font-family: Consolas, 'Cascadia Mono', monospace; font-size:12px; }"
        )
        lay.addWidget(self._text)

        self._ready.connect(self._on_ready)

    def clear(self):
        self._req_path = ""
        self._path = ""
        self._text.clear()
        self._hint.setText("导入图片后显示拍摄参数、时间、GPS 等")

    def load_path(self, path: str):
        path = (path or "").strip()
        if not path:
            self.clear()
            return
        self._req_path = path
        self._path = path
        self._hint.setText(f"正在读取：{path}")
        self._text.setPlainText("正在用 ExifTool 读取…")

        bridge = self._get_bridge()
        if not bridge:
            self._text.setPlainText("媒体引擎未加载")
            return
        if not getattr(bridge, "exiftool_available", False):
            self._text.setPlainText(
                "未找到 ExifTool。\n请运行 scripts\\download_exiftool.bat\n"
                "安装到 third_party\\exiftool\\（需保留 exiftool_files）。"
            )
            self._hint.setText("ExifTool 不可用")
            return

        def run():
            try:
                text = bridge.read_image_exif(path, full=True)
            except Exception as e:
                text = f"读取失败: {e}"
            self._ready.emit(path, text)

        threading.Thread(target=run, daemon=True).start()

    @Slot()
    def _on_refresh(self):
        if self._path:
            self.load_path(self._path)

    @Slot(str, str)
    def _on_ready(self, path: str, text: str):
        if path != self._req_path:
            return
        self._text.setPlainText(text)
        self._hint.setText(path)
