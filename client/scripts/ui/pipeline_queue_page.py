"""批量全流程队列页：切片成片 → 超分 → 去水印（无人值守）。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from models.pipeline_model import PipelineJob, PipelineJobState, PipelineSettings
from ui.theme import (
    ACCENT,
    ACCENT_PRESSED,
    BG,
    BORDER,
    BORDER_STRONG,
    DANGER,
    ELEVATED,
    FONT_UI,
    OK,
    SIGNAL,
    SURFACE,
    SURFACE_2,
    TEXT,
    TEXT_DIM,
    TEXT_MUTED,
)
from viewmodels.main_vm import MainViewModel

_VIDEO_FILTER = "视频 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.ts);;所有文件 (*.*)"

_STATE_COLORS = {
    PipelineJobState.WAITING: TEXT_MUTED,
    PipelineJobState.RUNNING: ACCENT,
    PipelineJobState.DONE: OK,
    PipelineJobState.FAILED: DANGER,
    PipelineJobState.SKIPPED: TEXT_DIM,
    PipelineJobState.CANCELLED: TEXT_DIM,
}


def _page_stylesheet() -> str:
    return f"""
QWidget#PipelineQueuePage {{
    background: {BG};
}}
QFrame#PipelineHero {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {SURFACE}, stop:0.55 {SURFACE_2}, stop:1 #1A222E);
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#PipelineTitle {{
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 18px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QLabel#PipelineSubtitle {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#PipelineFlow {{
    color: {SIGNAL};
    font-family: {FONT_UI};
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.5px;
}}
QFrame#PipelinePanel {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#PanelTitle {{
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 13px;
    font-weight: 600;
}}
QLabel#PanelMeta {{
    color: {TEXT_DIM};
    font-size: 12px;
}}
QLabel#FieldLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#OutPathLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 10px;
}}
QPushButton#StepChip {{
    background: {SURFACE_2};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 14px;
    font-family: {FONT_UI};
    font-size: 13px;
    font-weight: 600;
    text-align: left;
}}
QPushButton#StepChip:checked {{
    background: #2A3A36;
    color: #B8EDE4;
    border: 1px solid {SIGNAL};
}}
QPushButton#StepChip:hover {{
    border-color: {BORDER_STRONG};
    color: {TEXT};
}}
QPushButton#GhostBtn {{
    background: transparent;
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 7px 12px;
}}
QPushButton#GhostBtn:hover {{
    background: {ELEVATED};
    color: {TEXT};
    border-color: {BORDER_STRONG};
}}
QPushButton#DangerBtn {{
    background: transparent;
    color: {DANGER};
    border: 1px solid #5A3030;
    border-radius: 8px;
    padding: 7px 14px;
}}
QPushButton#DangerBtn:hover {{
    background: #3A2222;
    border-color: {DANGER};
}}
QPushButton#DangerBtn:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
    background: transparent;
}}
QPushButton#primaryButton {{
    min-width: 108px;
    padding: 9px 20px;
}}
QListWidget#PipelineList {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
    outline: 0;
}}
QListWidget#PipelineList::item {{
    padding: 11px 12px;
    margin: 2px 0;
    border-radius: 8px;
    color: {TEXT};
}}
QListWidget#PipelineList::item:selected {{
    background: #2C3444;
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
}}
QListWidget#PipelineList::item:hover {{
    background: {ELEVATED};
}}
QProgressBar#PipelineProgress {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    text-align: center;
    color: {TEXT};
    min-height: 18px;
    font-size: 11px;
}}
QProgressBar#PipelineProgress::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT_PRESSED}, stop:1 {ACCENT});
    border-radius: 7px;
}}
QFrame#PipelineFooter {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#PipelineStatus {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QComboBox, QDoubleSpinBox {{
    min-height: 28px;
}}
"""


class PipelineQueuePage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._paths: list[str] = []
        self._out_dir = ""

        self.setObjectName("PipelineQueuePage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_page_stylesheet())

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(12)

        root.addWidget(self._build_hero())

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_queue_panel())
        split.addWidget(self._build_settings_panel())
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setSizes([560, 420])
        root.addWidget(split, 1)

        root.addWidget(self._build_footer())

        vm.pipelineItemUpdated.connect(self._on_item_updated)
        vm.pipelineFinished.connect(self._on_finished)
        vm.pipelineStatusChanged.connect(self._on_status)
        vm.errorOccurred.connect(self._on_error)
        self._sync_step_enabled()

    # ── 结构 ──────────────────────────────────────────────

    def _build_hero(self) -> QWidget:
        hero = QFrame()
        hero.setObjectName("PipelineHero")
        lay = QHBoxLayout(hero)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(12)

        left = QVBoxLayout()
        left.setSpacing(4)
        title = QLabel("全流程队列")
        title.setObjectName("PipelineTitle")
        sub = QLabel("批量无人值守：切片成片 → 超分 → 去水印，输出按文件名分子目录")
        sub.setObjectName("PipelineSubtitle")
        sub.setWordWrap(True)
        left.addWidget(title)
        left.addWidget(sub)
        lay.addLayout(left, 1)

        flow = QLabel("SLICE  →  ENHANCE  →  WATERMARK")
        flow.setObjectName("PipelineFlow")
        flow.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(flow)
        return hero

    def _build_queue_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("PipelinePanel")
        col = QVBoxLayout(panel)
        col.setContentsMargins(14, 14, 14, 14)
        col.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("任务队列")
        title.setObjectName("PanelTitle")
        self._count_label = QLabel("0 项")
        self._count_label.setObjectName("PanelMeta")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(self._count_label)
        col.addLayout(head)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self._btn_add = QPushButton("添加视频")
        self._btn_add.setObjectName("primaryButton")
        self._btn_add.clicked.connect(self._add_files)
        self._btn_folder = QPushButton("添加文件夹")
        self._btn_folder.setObjectName("GhostBtn")
        self._btn_folder.clicked.connect(self._add_folder)
        self._btn_remove = QPushButton("移除")
        self._btn_remove.setObjectName("GhostBtn")
        self._btn_remove.clicked.connect(self._remove_selected)
        self._btn_clear = QPushButton("清空")
        self._btn_clear.setObjectName("GhostBtn")
        self._btn_clear.clicked.connect(self._clear_list)
        tools.addWidget(self._btn_add)
        tools.addWidget(self._btn_folder)
        tools.addStretch()
        tools.addWidget(self._btn_remove)
        tools.addWidget(self._btn_clear)
        col.addLayout(tools)

        self._list = QListWidget()
        self._list.setObjectName("PipelineList")
        self._list.setMinimumHeight(240)
        self._list.setAlternatingRowColors(False)
        self._list.setSpacing(1)
        col.addWidget(self._list, 1)
        self._refresh_list_labels()
        return panel

    def _build_settings_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("PipelinePanel")
        col = QVBoxLayout(panel)
        col.setContentsMargins(14, 14, 14, 14)
        col.setSpacing(12)

        head = QLabel("流程与参数")
        head.setObjectName("PanelTitle")
        col.addWidget(head)

        # 步骤芯片
        step_row = QHBoxLayout()
        step_row.setSpacing(8)
        self._chip_slice = self._make_step_chip("① 切片成片", True)
        self._chip_enhance = self._make_step_chip("② 超分", True)
        self._chip_wm = self._make_step_chip("③ 去水印", False)
        for chip in (self._chip_slice, self._chip_enhance, self._chip_wm):
            chip.toggled.connect(self._sync_step_enabled)
            step_row.addWidget(chip, 1)
        col.addLayout(step_row)

        tip = QLabel("点按步骤开启/关闭 · 去水印使用角标预设，无需逐个框选")
        tip.setObjectName("PanelMeta")
        tip.setWordWrap(True)
        col.addWidget(tip)

        # 切片
        self._slice_box = self._section("切片")
        g = QGridLayout(self._slice_box)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        g.addWidget(self._field_label("场景"), 0, 0)
        self._scene = QComboBox()
        self._scene.addItems(["游戏高光", "演讲金句", "日常精彩片段", "响度高潮", "自定义识别"])
        g.addWidget(self._scene, 0, 1, 1, 3)
        g.addWidget(self._field_label("最短秒"), 1, 0)
        self._min_dur = QDoubleSpinBox()
        self._min_dur.setRange(1.0, 120.0)
        self._min_dur.setValue(3.0)
        g.addWidget(self._min_dur, 1, 1)
        g.addWidget(self._field_label("最长秒"), 1, 2)
        self._max_dur = QDoubleSpinBox()
        self._max_dur.setRange(3.0, 300.0)
        self._max_dur.setValue(60.0)
        g.addWidget(self._max_dur, 1, 3)
        col.addWidget(self._wrap_section(self._slice_box))

        # 超分
        self._enh_box = self._section("超分")
        eg = QGridLayout(self._enh_box)
        eg.setHorizontalSpacing(10)
        eg.setVerticalSpacing(8)
        eg.addWidget(self._field_label("后端"), 0, 0)
        self._enh_backend = QComboBox()
        self._enh_backend.addItem("快速 · OpenCV", "opencv")
        self._enh_backend.addItem("AI · Real-ESRGAN", "realesrgan")
        eg.addWidget(self._enh_backend, 0, 1)
        eg.addWidget(self._field_label("倍率"), 0, 2)
        self._enh_scale = QComboBox()
        self._enh_scale.addItem("2×", 2)
        self._enh_scale.addItem("4×", 4)
        eg.addWidget(self._enh_scale, 0, 3)
        eg.addWidget(self._field_label("试跑秒数"), 1, 0)
        self._enh_max_sec = QDoubleSpinBox()
        self._enh_max_sec.setRange(0.0, 600.0)
        self._enh_max_sec.setValue(0.0)
        self._enh_max_sec.setSpecialValueText("全程")
        self._enh_max_sec.setToolTip("0 = 全程；大于 0 仅超分前 N 秒，适合试跑")
        eg.addWidget(self._enh_max_sec, 1, 1, 1, 3)
        col.addWidget(self._wrap_section(self._enh_box))

        # 去水印
        self._wm_box = self._section("去水印")
        wg = QGridLayout(self._wm_box)
        wg.setHorizontalSpacing(10)
        wg.setVerticalSpacing(8)
        wg.addWidget(self._field_label("角标"), 0, 0)
        self._wm_corner = QComboBox()
        for label, data in (
            ("右上", "top_right"),
            ("左上", "top_left"),
            ("右下", "bottom_right"),
            ("左下", "bottom_left"),
        ):
            self._wm_corner.addItem(label, data)
        wg.addWidget(self._wm_corner, 0, 1)
        wg.addWidget(self._field_label("后端"), 0, 2)
        self._wm_backend = QComboBox()
        self._wm_backend.addItem("快速 · OpenCV", "opencv")
        self._wm_backend.addItem("精修 · LaMa", "lama")
        wg.addWidget(self._wm_backend, 0, 3)
        col.addWidget(self._wrap_section(self._wm_box))

        # 输出
        out_wrap = self._section("输出目录")
        out_col = QVBoxLayout(out_wrap)
        out_col.setSpacing(8)
        self._out_label = QLabel("默认：各视频同目录 / pipeline_out")
        self._out_label.setObjectName("OutPathLabel")
        self._out_label.setWordWrap(True)
        btn_out = QPushButton("选择目录…")
        btn_out.setObjectName("GhostBtn")
        btn_out.clicked.connect(self._pick_output)
        out_row = QHBoxLayout()
        out_row.addWidget(self._out_label, 1)
        out_row.addWidget(btn_out)
        out_col.addLayout(out_row)
        col.addWidget(self._wrap_section(out_wrap))

        col.addStretch(1)
        return panel

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("PipelineFooter")
        col = QVBoxLayout(footer)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(10)

        self._progress = QProgressBar()
        self._progress.setObjectName("PipelineProgress")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%p%")
        col.addWidget(self._progress)

        self._status = QLabel("就绪 · 勾选步骤并添加视频后即可开始")
        self._status.setObjectName("PipelineStatus")
        self._status.setWordWrap(True)
        col.addWidget(self._status)

        run_row = QHBoxLayout()
        run_row.setSpacing(8)
        self._btn_start = QPushButton("开始队列")
        self._btn_start.setObjectName("primaryButton")
        self._btn_start.setCursor(Qt.PointingHandCursor)
        self._btn_start.clicked.connect(self._on_start)
        self._btn_pause = QPushButton("暂停")
        self._btn_pause.setObjectName("GhostBtn")
        self._btn_pause.setEnabled(False)
        self._btn_pause.clicked.connect(self._on_pause)
        self._btn_skip = QPushButton("跳过当前")
        self._btn_skip.setObjectName("GhostBtn")
        self._btn_skip.setEnabled(False)
        self._btn_skip.clicked.connect(self._on_skip)
        self._btn_cancel = QPushButton("取消")
        self._btn_cancel.setObjectName("DangerBtn")
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self._on_cancel)
        self._btn_open = QPushButton("打开结果")
        self._btn_open.setObjectName("GhostBtn")
        self._btn_open.setEnabled(False)
        self._btn_open.clicked.connect(self._open_result)

        run_row.addWidget(self._btn_start)
        run_row.addWidget(self._btn_pause)
        run_row.addWidget(self._btn_skip)
        run_row.addWidget(self._btn_cancel)
        run_row.addStretch()
        run_row.addWidget(self._btn_open)
        col.addLayout(run_row)
        return footer

    # ── 小部件工具 ────────────────────────────────────────

    def _make_step_chip(self, text: str, checked: bool) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("StepChip")
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return btn

    def _field_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("FieldLabel")
        return lab

    def _section(self, _title: str) -> QWidget:
        w = QWidget()
        return w

    def _wrap_section(self, inner: QWidget) -> QWidget:
        # 用轻量卡片框住参数区（标题已在芯片/外层面板表达）
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background: {SURFACE_2}; border: 1px solid {BORDER};"
            f" border-radius: 10px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(inner)
        return frame

    def _sync_step_enabled(self):
        for box, on in (
            (self._slice_box, self._chip_slice.isChecked()),
            (self._enh_box, self._chip_enhance.isChecked()),
            (self._wm_box, self._chip_wm.isChecked()),
        ):
            wrap = box.parentWidget()
            if wrap:
                wrap.setEnabled(on)
                wrap.setStyleSheet(
                    f"QFrame {{ background: {SURFACE_2 if on else BG};"
                    f" border: 1px solid {BORDER if on else '#1E2530'};"
                    f" border-radius: 10px; }}"
                )

    # ── 业务逻辑（与原先一致） ────────────────────────────

    def _pick_output(self):
        d = QFileDialog.getExistingDirectory(self, "选择输出根目录", self._out_dir or "")
        if d:
            self._out_dir = d
            self._out_label.setText(d)

    def _add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "添加视频", "", _VIDEO_FILTER)
        self._append_paths(files)

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "添加文件夹中的视频")
        if not d:
            return
        exts = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts", ".mpeg", ".mpg"}
        found = []
        for name in sorted(os.listdir(d)):
            p = os.path.join(d, name)
            if os.path.isfile(p) and os.path.splitext(name)[1].lower() in exts:
                found.append(p)
        self._append_paths(found)
        if not found:
            QMessageBox.information(self, "提示", "该文件夹下没有常见视频文件。")

    def _append_paths(self, paths: list[str]):
        existing = {os.path.normcase(os.path.abspath(p)) for p in self._paths}
        for p in paths:
            if not p or not os.path.isfile(p):
                continue
            key = os.path.normcase(os.path.abspath(p))
            if key in existing:
                continue
            existing.add(key)
            self._paths.append(os.path.abspath(p))
        self._refresh_list_labels()

    def _remove_selected(self):
        rows = sorted({i.row() for i in self._list.selectedIndexes()}, reverse=True)
        for r in rows:
            if 0 <= r < len(self._paths):
                self._paths.pop(r)
        self._refresh_list_labels()

    def _clear_list(self):
        if self._vm.pipeline_running:
            QMessageBox.warning(self, "提示", "队列运行中，无法清空。")
            return
        self._paths.clear()
        self._refresh_list_labels()
        self._progress.setValue(0)

    def _refresh_list_labels(self, jobs: list[PipelineJob] | None = None):
        self._list.clear()
        if jobs:
            for job in jobs:
                item = QListWidgetItem(self._format_job(job))
                item.setData(Qt.UserRole, job.result_path or job.path)
                item.setToolTip(job.path + (f"\n{job.result_path}" if job.result_path else ""))
                color = _STATE_COLORS.get(job.state, TEXT)
                item.setForeground(QColor(color))
                self._list.addItem(item)
            self._count_label.setText(f"{len(jobs)} 项")
            return

        if not self._paths:
            item = QListWidgetItem("还没有任务 — 点「添加视频」或「添加文件夹」开始")
            item.setFlags(Qt.NoItemFlags)
            item.setForeground(QColor(TEXT_DIM))
            self._list.addItem(item)
            self._count_label.setText("0 项")
            return

        for p in self._paths:
            item = QListWidgetItem(f"等待 · {os.path.basename(p)}")
            item.setData(Qt.UserRole, p)
            item.setToolTip(p)
            item.setForeground(QColor(TEXT_MUTED))
            self._list.addItem(item)
        self._count_label.setText(f"{len(self._paths)} 项")

    @staticmethod
    def _format_job(job: PipelineJob) -> str:
        name = os.path.basename(job.path)
        phase = f" · {job.phase.value}" if job.phase and job.phase.value else ""
        msg = f"\n{job.message}" if job.message else ""
        return f"{job.state.value}{phase}  ·  {name}{msg}"

    def _collect_settings(self) -> PipelineSettings | None:
        if not (
            self._chip_slice.isChecked()
            or self._chip_enhance.isChecked()
            or self._chip_wm.isChecked()
        ):
            QMessageBox.warning(self, "提示", "请至少开启一个处理步骤。")
            return None
        if self._chip_wm.isChecked() and not self._wm_corner.currentData():
            QMessageBox.warning(self, "提示", "去水印已开启，请选择角标位置。")
            return None
        return PipelineSettings(
            do_slice=self._chip_slice.isChecked(),
            do_enhance=self._chip_enhance.isChecked(),
            do_watermark=self._chip_wm.isChecked(),
            scene=self._scene.currentText(),
            min_duration=float(self._min_dur.value()),
            max_duration=float(self._max_dur.value()),
            enhance_backend=str(self._enh_backend.currentData()),
            enhance_scale=int(self._enh_scale.currentData()),
            enhance_max_sec=float(self._enh_max_sec.value()),
            watermark_backend=str(self._wm_backend.currentData()),
            watermark_corner=str(self._wm_corner.currentData() or "top_right"),
            output_root=self._out_dir,
        )

    def _on_start(self):
        if self._vm.pipeline_running:
            return
        if not self._paths:
            QMessageBox.warning(self, "提示", "请先添加视频。")
            return
        settings = self._collect_settings()
        if settings is None:
            return
        self._set_running_ui(True)
        self._progress.setValue(0)
        self._status.setText("队列启动…")
        self._vm.start_pipeline_queue(list(self._paths), settings)

    def _on_pause(self):
        if not self._vm.pipeline_running:
            return
        if self._vm.pipeline_paused:
            self._vm.resume_pipeline_queue()
            self._btn_pause.setText("暂停")
            self._status.setText("已继续")
        else:
            self._vm.pause_pipeline_queue()
            self._btn_pause.setText("继续")
            self._status.setText("已暂停 · 可点「继续」恢复")

    def _on_skip(self):
        self._vm.skip_pipeline_current()

    def _on_cancel(self):
        self._vm.cancel_pipeline_queue()
        self._status.setText("正在取消…")

    def _open_result(self):
        item = self._list.currentItem()
        if not item:
            QMessageBox.information(self, "提示", "请先在列表中选中一项。")
            return
        path = item.data(Qt.UserRole) or ""
        if path and os.path.isfile(path):
            os.startfile(os.path.dirname(path))  # noqa: S606
        elif path and os.path.isdir(path):
            os.startfile(path)  # noqa: S606
        else:
            QMessageBox.information(self, "提示", "尚无结果文件可打开。")

    def _set_running_ui(self, running: bool):
        self._btn_start.setEnabled(not running)
        self._btn_pause.setEnabled(running)
        self._btn_skip.setEnabled(running)
        self._btn_cancel.setEnabled(running)
        self._btn_add.setEnabled(not running)
        self._btn_folder.setEnabled(not running)
        self._btn_remove.setEnabled(not running)
        self._btn_clear.setEnabled(not running)
        if not running:
            self._btn_pause.setText("暂停")

    @Slot(int, object)
    def _on_item_updated(self, index: int, job: object):
        if not isinstance(job, PipelineJob):
            return
        jobs = self._vm.pipeline_jobs
        if jobs:
            self._refresh_list_labels(jobs)
            if 0 <= index < len(jobs):
                self._list.setCurrentRow(index)
            total = max(len(jobs), 1)
            if job.state == PipelineJobState.RUNNING:
                overall = (index + job.progress / 100.0) / total * 100.0
            else:
                done = sum(
                    1
                    for j in jobs
                    if j.state
                    in (
                        PipelineJobState.DONE,
                        PipelineJobState.FAILED,
                        PipelineJobState.SKIPPED,
                        PipelineJobState.CANCELLED,
                    )
                )
                overall = done / total * 100.0
            self._progress.setValue(int(max(0, min(100, overall))))
            self._status.setText(
                f"[{index + 1}/{total}] {job.state.value}"
                f"{(' · ' + job.phase.value) if job.phase.value else ''}"
                f" · {job.message}"
            )
            if job.result_path:
                self._btn_open.setEnabled(True)

    @Slot()
    def _on_finished(self):
        self._set_running_ui(False)
        jobs = self._vm.pipeline_jobs
        ok = sum(1 for j in jobs if j.state == PipelineJobState.DONE)
        fail = sum(1 for j in jobs if j.state == PipelineJobState.FAILED)
        self._status.setText(f"队列结束 · 成功 {ok} · 失败 {fail}")
        if fail == 0 and ok > 0:
            self._progress.setValue(100)
        if ok:
            self._btn_open.setEnabled(True)

    @Slot(str)
    def _on_status(self, text: str):
        if text:
            self._status.setText(text)

    @Slot(str)
    def _on_error(self, msg: str):
        if self.isVisible() and msg.startswith("全流程队列"):
            QMessageBox.warning(self, "队列", msg)
