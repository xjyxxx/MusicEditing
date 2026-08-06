"""BGM 混音 / 人声分离：下载页拿歌后在此混到成片；Demucs 可选。"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QProgressBar, QPushButton, QTabWidget, QVBoxLayout,
    QWidget,
)

from core.bgm_mix import MIX_MODES
from core.demucs_sep import probe_demucs
from ui.elided_label import ElidedPathLabel
from ui.theme import style_spinbox
from viewmodels.main_vm import MainViewModel


class BgmPage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._busy = False
        self._video = ""
        self._bgm = ""
        self._sep_src = ""
        self._last_out = ""

        root = QVBoxLayout(self)
        tip = QLabel(
            "基础混音只用项目 FFmpeg，可直接打包给其它电脑。"
            "人声分离需可选安装 Demucs（third_party/demucs 源码很小；"
            "PyTorch + 权重较大，运行 scripts\\setup_demucs.bat）。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("MutedText")
        root.addWidget(tip)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_mix_tab(), "BGM 混音")
        self._tabs.addTab(self._build_sep_tab(), "人声分离")
        root.addWidget(self._tabs, 1)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)
        self._status = QLabel("")
        self._status.setObjectName("MutedText")
        root.addWidget(self._status)

        vm.bgmMixProgress.connect(self._on_progress)
        vm.bgmMixFinished.connect(self._on_mix_finished)
        vm.demucsProgress.connect(self._on_progress)
        vm.demucsFinished.connect(self._on_sep_finished)
        vm.errorOccurred.connect(self._on_error)
        self._refresh_demucs_status()

    def _build_mix_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        vbox = QGroupBox("成片视频")
        vl = QVBoxLayout(vbox)
        row = QHBoxLayout()
        self._video_label = ElidedPathLabel("未选择", object_name="InfoText")
        b1 = QPushButton("选择视频…")
        b1.clicked.connect(self._pick_video)
        b2 = QPushButton("用当前导入")
        b2.clicked.connect(self._use_current_video)
        row.addWidget(self._video_label, 1)
        row.addWidget(b2)
        row.addWidget(b1)
        vl.addLayout(row)
        lay.addWidget(vbox)

        bbox = QGroupBox("背景音乐（可从「链接下载」下好的 mp3）")
        bl = QVBoxLayout(bbox)
        row2 = QHBoxLayout()
        self._bgm_label = ElidedPathLabel("未选择", object_name="InfoText")
        b3 = QPushButton("选择音频…")
        b3.clicked.connect(self._pick_bgm)
        row2.addWidget(self._bgm_label, 1)
        row2.addWidget(b3)
        bl.addLayout(row2)
        lay.addWidget(bbox)

        opt = QGroupBox("混音参数")
        ol = QVBoxLayout(opt)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("模式"))
        self._mode = QComboBox()
        for k, name in MIX_MODES.items():
            self._mode.addItem(name, k)
        mode_row.addWidget(self._mode, 1)
        ol.addLayout(mode_row)

        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("BGM 音量"))
        self._bgm_vol = QDoubleSpinBox()
        self._bgm_vol.setRange(0.05, 1.5)
        self._bgm_vol.setSingleStep(0.05)
        self._bgm_vol.setValue(0.35)
        style_spinbox(self._bgm_vol)
        vol_row.addWidget(self._bgm_vol)
        vol_row.addWidget(QLabel("原声音量"))
        self._voice_vol = QDoubleSpinBox()
        self._voice_vol.setRange(0.0, 1.5)
        self._voice_vol.setSingleStep(0.05)
        self._voice_vol.setValue(1.0)
        style_spinbox(self._voice_vol)
        vol_row.addWidget(self._voice_vol)
        self._loop = QCheckBox("BGM 循环铺满")
        self._loop.setChecked(True)
        vol_row.addWidget(self._loop)
        vol_row.addStretch()
        ol.addLayout(vol_row)
        lay.addWidget(opt)

        btn_row = QHBoxLayout()
        self._btn_mix = QPushButton("导出混音成片")
        self._btn_mix.setObjectName("primaryButton")
        self._btn_mix.clicked.connect(self._on_mix)
        self._btn_open = QPushButton("打开结果")
        self._btn_open.setEnabled(False)
        self._btn_open.clicked.connect(self._open_last)
        btn_row.addWidget(self._btn_mix)
        btn_row.addWidget(self._btn_open)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        lay.addStretch()
        return w

    def _build_sep_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self._demucs_status = QLabel("")
        self._demucs_status.setWordWrap(True)
        self._demucs_status.setObjectName("InfoText")
        lay.addWidget(self._demucs_status)

        src = QGroupBox("待分离音频 / 含音轨视频")
        sl = QVBoxLayout(src)
        row = QHBoxLayout()
        self._sep_label = ElidedPathLabel("未选择", object_name="InfoText")
        b1 = QPushButton("选择…")
        b1.clicked.connect(self._pick_sep)
        b2 = QPushButton("用当前导入")
        b2.clicked.connect(self._use_current_sep)
        b3 = QPushButton("刷新 Demucs 状态")
        b3.clicked.connect(self._refresh_demucs_status)
        row.addWidget(self._sep_label, 1)
        row.addWidget(b2)
        row.addWidget(b1)
        row.addWidget(b3)
        sl.addLayout(row)
        lay.addWidget(src)

        hint = QLabel(
            "输出：vocals（人声）、no_vocals（伴奏）以及 drums/bass/other。"
            "伴奏可再拿去「BGM 混音」叠到成片。"
        )
        hint.setWordWrap(True)
        hint.setObjectName("MutedText")
        lay.addWidget(hint)

        btn_row = QHBoxLayout()
        self._btn_sep = QPushButton("开始人声分离")
        self._btn_sep.setObjectName("primaryButton")
        self._btn_sep.clicked.connect(self._on_sep)
        self._btn_sep_open = QPushButton("打开输出目录")
        self._btn_sep_open.setEnabled(False)
        self._btn_sep_open.clicked.connect(self._open_last)
        btn_row.addWidget(self._btn_sep)
        btn_row.addWidget(self._btn_sep_open)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        lay.addStretch()
        return w

    def _refresh_demucs_status(self):
        st = probe_demucs()
        if st.available:
            gpu = "CUDA" if st.cuda else "CPU"
            self._demucs_status.setText(
                f"Demucs {st.demucs_version} · torch {st.torch_version} · {gpu} · {st.detail}"
            )
            self._btn_sep.setEnabled(True)
        else:
            self._demucs_status.setText(st.detail)
            self._btn_sep.setEnabled(False)

    def _current_path(self) -> str:
        video = getattr(self._vm._state, "current_video", None)  # noqa: SLF001
        return getattr(video, "file_path", "") if video else ""

    @Slot()
    def _pick_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择成片视频", "",
            "视频 (*.mp4 *.mkv *.mov *.webm);;所有文件 (*.*)",
        )
        if path:
            self._video = path
            self._video_label.setText(path)

    @Slot()
    def _use_current_video(self):
        path = self._current_path()
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "提示", "当前没有已导入视频")
            return
        self._video = path
        self._video_label.setText(path)

    @Slot()
    def _pick_bgm(self):
        default = os.path.join(os.path.expanduser("~"), "MusicEditingDownloads")
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 BGM",
            default if os.path.isdir(default) else "",
            "音频 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg);;所有文件 (*.*)",
        )
        if path:
            self._bgm = path
            self._bgm_label.setText(path)

    @Slot()
    def _pick_sep(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择要分离的媒体", "",
            "媒体 (*.mp3 *.wav *.m4a *.flac *.mp4 *.mkv *.mov);;所有文件 (*.*)",
        )
        if path:
            self._sep_src = path
            self._sep_label.setText(path)

    @Slot()
    def _use_current_sep(self):
        path = self._current_path()
        if not path:
            QMessageBox.information(self, "提示", "当前没有已导入媒体")
            return
        self._sep_src = path
        self._sep_label.setText(path)

    @Slot()
    def _on_mix(self):
        if self._busy:
            return
        if not self._video or not os.path.isfile(self._video):
            QMessageBox.warning(self, "提示", "请先选择成片视频")
            return
        if not self._bgm or not os.path.isfile(self._bgm):
            QMessageBox.warning(self, "提示", "请先选择背景音乐")
            return
        stem = Path(self._video).stem
        default = str(Path(self._video).with_name(f"{stem}_bgm.mp4"))
        out, _ = QFileDialog.getSaveFileName(
            self, "保存混音成片", default, "MP4 (*.mp4);;所有文件 (*.*)",
        )
        if not out:
            return
        self._set_busy(True)
        self._status.setText("正在混音…")
        self._vm.start_bgm_mix(
            self._video,
            self._bgm,
            out,
            mode=str(self._mode.currentData() or "overlay"),
            bgm_volume=float(self._bgm_vol.value()),
            voice_volume=float(self._voice_vol.value()),
            loop_bgm=self._loop.isChecked(),
        )

    @Slot()
    def _on_sep(self):
        if self._busy:
            return
        if not self._sep_src or not os.path.isfile(self._sep_src):
            QMessageBox.warning(self, "提示", "请先选择音频或视频")
            return
        default_dir = str(Path(self._sep_src).with_name(Path(self._sep_src).stem + "_stems"))
        out_dir = QFileDialog.getExistingDirectory(self, "选择分轨输出目录", default_dir)
        if not out_dir:
            out_dir = default_dir
        self._set_busy(True)
        self._status.setText("人声分离中（首次可能下载模型）…")
        self._vm.start_demucs_separate(self._sep_src, out_dir)

    def _set_busy(self, busy: bool):
        self._busy = busy
        self._btn_mix.setEnabled(not busy)
        self._progress.setVisible(busy or self._progress.value() > 0)
        if busy:
            self._progress.setValue(0)

    @Slot(int, float, str)
    def _on_progress(self, _tid: int, p: float, msg: str):
        self._progress.setVisible(True)
        self._progress.setValue(int(max(0, min(100, p))))
        if msg:
            self._status.setText(msg)

    @Slot(int, str)
    def _on_mix_finished(self, _tid: int, path: str):
        self._set_busy(False)
        self._last_out = path
        self._btn_open.setEnabled(True)
        self._status.setText(f"混音完成 · {os.path.basename(path)}")
        QMessageBox.information(self, "混音完成", f"已保存：\n{path}")

    @Slot(int, str)
    def _on_sep_finished(self, _tid: int, out_dir: str):
        self._set_busy(False)
        self._last_out = out_dir
        self._btn_sep_open.setEnabled(True)
        self._status.setText(f"分轨完成 · {out_dir}")
        QMessageBox.information(self, "人声分离完成", f"输出目录：\n{out_dir}")

    @Slot(str)
    def _on_error(self, msg: str):
        if not self._busy:
            return
        self._set_busy(False)
        self._status.setText(f"失败: {msg}")
        QMessageBox.warning(self, "失败", msg)

    @Slot()
    def _open_last(self):
        if not self._last_out:
            return
        path = self._last_out
        if os.path.isfile(path):
            os.startfile(str(Path(path).parent))  # noqa: S606
        elif os.path.isdir(path):
            os.startfile(path)  # noqa: S606
