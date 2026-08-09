"""导出参数：发布预设 + 一键竖屏成片模板。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
    QVBoxLayout,
)

from core.film_templates import get_film_template, list_film_templates


@dataclass
class ExportOptions:
    """导出选项。max_height=0 表示保持原画高度。"""

    max_height: int = 0
    quality: str = "high"
    container: str = "mp4"
    preset: str = "custom"
    make_cover: bool = False
    make_topic_draft: bool = False
    use_naming_scheme: bool = True
    film_template: str = ""
    cover_title: str = ""
    max_total_sec: float = 0.0

    @property
    def vertical_size(self) -> tuple[int, int]:
        if self.max_height == 720:
            return 720, 1280
        if self.max_height == 1080:
            return 1080, 1920
        return 1080, 1920

    @property
    def topic_tags(self) -> list[str]:
        tpl = get_film_template(self.film_template)
        if tpl is not None:
            return list(tpl.topics)
        return {
            "douyin_vertical": ["#抖音", "#竖屏", "#高光"],
            "bilibili_vertical": ["#必剪", "#竖屏", "#高光成片"],
            "kuaishou_vertical": ["#快手", "#竖屏", "#高光"],
        }.get(self.preset, ["#口播", "#干货", "#MusicEditing"])


class ExportOptionsDialog(QDialog):
    def __init__(self, parent=None, *, title: str = "导出参数"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(440)
        root = QVBoxLayout(self)
        tip = QLabel(
            "成片模板会带时长上限、封面文案与话题；"
            "发布预设只填平台分辨率/质量。勾选规范命名方便批量归档。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("MutedText")
        root.addWidget(tip)

        form = QFormLayout()
        self._film = QComboBox()
        self._film.addItem("不使用成片模板", "")
        for t in list_film_templates():
            self._film.addItem(t.label, t.key)
        self._film.currentIndexChanged.connect(self._on_film)
        form.addRow("成片模板", self._film)

        self._film_hint = QLabel("")
        self._film_hint.setObjectName("MutedText")
        self._film_hint.setWordWrap(True)
        form.addRow("", self._film_hint)

        self._preset = QComboBox()
        self._preset.addItem("自定义", "custom")
        self._preset.addItem("抖音竖屏（1080×1920）", "douyin_vertical")
        self._preset.addItem("B站竖屏（1080×1920）", "bilibili_vertical")
        self._preset.addItem("快手竖屏（1080×1920）", "kuaishou_vertical")
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
        self._naming = QCheckBox("规范命名（源名_类型_平台_时间戳）")
        self._naming.setChecked(True)
        root.addWidget(self._cover)
        root.addWidget(self._draft)
        root.addWidget(self._naming)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._on_film()

    def _apply_vertical_pack(self):
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
        self._naming.setChecked(True)

    def _on_preset(self, _idx: int = 0):
        key = str(self._preset.currentData() or "custom")
        if key in ("douyin_vertical", "bilibili_vertical", "kuaishou_vertical"):
            self._apply_vertical_pack()

    def _on_film(self, _idx: int = 0):
        tpl = get_film_template(str(self._film.currentData() or ""))
        if tpl is None:
            self._film_hint.setText("")
            return
        self._film_hint.setText(
            f"{tpl.hint} · 封面「{tpl.cover_title}」· ≤{tpl.max_total_sec:.0f}s"
        )
        for i in range(self._preset.count()):
            if self._preset.itemData(i) == tpl.platform:
                self._preset.setCurrentIndex(i)
                break
        self._apply_vertical_pack()

    def options(self) -> ExportOptions:
        tpl = get_film_template(str(self._film.currentData() or ""))
        return ExportOptions(
            max_height=int(self._res.currentData() or 0),
            quality=str(self._quality.currentData() or "high"),
            container=str(self._fmt.currentData() or "mp4"),
            preset=str(self._preset.currentData() or "custom"),
            make_cover=bool(self._cover.isChecked()),
            make_topic_draft=bool(self._draft.isChecked()),
            use_naming_scheme=bool(self._naming.isChecked()),
            film_template=tpl.key if tpl else "",
            cover_title=tpl.cover_title if tpl else "",
            max_total_sec=float(tpl.max_total_sec) if tpl else 0.0,
        )
