"""本地媒体信息对话框（VideoEye 精简：封装 / 码流只读表）。"""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.media_probe import MediaProbeResult


class MediaInfoDialog(QDialog):
    def __init__(self, result: MediaProbeResult, parent=None):
        super().__init__(parent)
        self._result = result
        name = result.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] if result.path else "媒体"
        self.setWindowTitle(f"媒体信息 — {name}")
        self.setMinimumSize(480, 420)

        root = QVBoxLayout(self)
        tip = QLabel("本地 ffprobe 探测（封装层 / 编码层摘要）。")
        tip.setObjectName("MutedText")
        tip.setWordWrap(True)
        root.addWidget(tip)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["项", "值"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setWordWrap(True)
        rows = result.rows()
        table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(k))
            table.setItem(i, 1, QTableWidgetItem(v))
        table.resizeColumnsToContents()
        table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(table, 1)

        btn_row = QHBoxLayout()
        copy_btn = QPushButton("复制摘要")
        copy_btn.clicked.connect(self._copy)
        btn_row.addWidget(copy_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close = buttons.button(QDialogButtonBox.Close)
        if close:
            close.clicked.connect(self.accept)
        root.addWidget(buttons)

    def _copy(self):
        text = self._result.summary_text()
        QGuiApplication.clipboard().setText(text)
        QMessageBox.information(self, "已复制", "媒体信息摘要已复制到剪贴板。")
