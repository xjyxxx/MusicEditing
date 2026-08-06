"""导出参数：含抖音竖屏发布预设。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QVBoxLayout,
)


@dataclass
class ExportOptions:
    """导出选项。max_height=0 表示保持原画高度。"""

    max_height: int = 0  # 0 | 1080 | 720
    quality: str = "high"  # high | standard | small
    container: str = "mp4"  # mp4 | mov
    preset: str = "custom"  # custom | douyin_vertical
    make_cover: bool = False
    make_topic_draft: bool = False

    @property
    def vertical_size(self) -> tuple[int, int]:
        """竖屏默认 9:16。"""
        if self.max_height == 720:
            return 720, 1280
        if self.max_height == 1080:
            return 1080, 1920
        return 1080, 1920


class ExportOptionsDialog(QDialog):
    def __init__(self, parent=None, *, title: str = "导出参数"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        root = QVBoxLayout(self)
        tip = QLabel("不改则与当前默认导出一致（偏高质量）。可选抖音竖屏一键预设。")
        tip.setWordWrap(True)
        tip.setObjectName("MutedText")
        root.addWidget(tip)

        form = QFormLayout()
        self._preset = QComboBox()
        self._preset.addItem("自定义", "custom")
        self._preset.addItem("抖音竖屏（1080×1920）", "douyin_vertical")
        self._preset.currentIndexChanged.connect(self._on_preset)
        form.addRow("发布预设", self._preset)

        self._res = QComboBox()
        self._res.addItem("原画 / 默认", 0)
        self._res.addItem("1080p", 1080)
        self._res.addItem("720p", 720)
        form.addRow("分辨率", self._res)

        self._quality = QComboBox()
        self._quality.addItem("高（推荐）", "high")
        self._quality.addItem("标准", "standard")
        self._quality.addItem("小文件", "small")
        form.addRow("质量", self._quality)

        self._fmt = QComboBox()
        self._fmt.addItem("MP4", "mp4")
        self._fmt.addItem("MOV", "mov")
        form.addRow("格式", self._fmt)
        root.addLayout(form)

        self._cover = QCheckBox("导出后生成封面 PNG（同目录）")
        self._draft = QCheckBox("导出后生成话题/标题草稿 .txt")
        root.addWidget(self._cover)
        root.addWidget(self._draft)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _on_preset(self, _idx: int = 0):
        key = str(self._preset.currentData() or "custom")
        if key == "douyin_vertical":
            # 1080p + 高码率 + mp4 + 封面/草稿
            for i in range(self._res.count()):
                if self._res.itemData(i) == 1080:
                    self._res.setCurrentIndex(i)
                    break
            for i in range(self._quality.count()):
                if self._quality.itemData(i) == "high":
                    self._quality.setCurrentIndex(i)
                    break
            for i in range(self._fmt.count()):
                if self._fmt.itemData(i) == "mp4":
                    self._fmt.setCurrentIndex(i)
                    break
            self._cover.setChecked(True)
            self._draft.setChecked(True)

    def options(self) -> ExportOptions:
        return ExportOptions(
            max_height=int(self._res.currentData() or 0),
            quality=str(self._quality.currentData() or "high"),
            container=str(self._fmt.currentData() or "mp4"),
            preset=str(self._preset.currentData() or "custom"),
            make_cover=bool(self._cover.isChecked()),
            make_topic_draft=bool(self._draft.isChecked()),
        )
