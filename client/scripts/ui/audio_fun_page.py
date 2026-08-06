"""音频趣味页：变调 / 变速 / 倒放 / 8D / 混响（FFmpeg）。"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QProgressBar, QPushButton, QSlider, QVBoxLayout, QWidget,
)

from core.audio_fx import PRESETS, AudioFxParams, describe_params
from ui.elided_label import ElidedPathLabel
from viewmodels.main_vm import MainViewModel


class AudioFunPage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._src_path = ""
        self._result_path = ""
        self._busy = False

        root = QVBoxLayout(self)
        tip = QLabel(
            "MusicEditing 本业：变调(asetrate)、变速(atempo)、倒放(areverse)、"
            "伪 8D(apulsator)、简单混响(aecho)。可作用于音频或视频音轨（视频画面 copy）。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("MutedText")
        root.addWidget(tip)

        src_box = QGroupBox("输入")
        src_lay = QVBoxLayout(src_box)
        row = QHBoxLayout()
        self._path_label = ElidedPathLabel("未选择文件", object_name="InfoText")
        btn_open = QPushButton("打开…")
        btn_open.clicked.connect(self._on_open)
        btn_use = QPushButton("使用当前导入")
        btn_use.clicked.connect(self._on_use_current)
        row.addWidget(self._path_label, 1)
        row.addWidget(btn_use)
        row.addWidget(btn_open)
        src_lay.addLayout(row)
        root.addWidget(src_box)

        preset_box = QGroupBox("一键预设")
        preset_lay = QHBoxLayout(preset_box)
        for name, params in PRESETS:
            btn = QPushButton(name)
            btn.clicked.connect(lambda _=False, p=params: self._apply_preset(p))
            preset_lay.addWidget(btn)
        preset_lay.addStretch()
        root.addWidget(preset_box)

        fx_box = QGroupBox("参数")
        fx = QVBoxLayout(fx_box)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("变速"))
        self._speed_slider = QSlider(Qt.Horizontal)
        self._speed_slider.setRange(25, 400)  # ×0.01
        self._speed_slider.setValue(100)
        self._speed_spin = QDoubleSpinBox()
        self._speed_spin.setRange(0.25, 4.0)
        self._speed_spin.setSingleStep(0.05)
        self._speed_spin.setValue(1.0)
        self._speed_slider.valueChanged.connect(
            lambda v: self._speed_spin.setValue(v / 100.0)
        )
        self._speed_spin.valueChanged.connect(
            lambda v: self._speed_slider.setValue(int(round(v * 100)))
        )
        speed_row.addWidget(self._speed_slider, 1)
        speed_row.addWidget(self._speed_spin)
        fx.addLayout(speed_row)

        pitch_row = QHBoxLayout()
        pitch_row.addWidget(QLabel("变调"))
        self._pitch_slider = QSlider(Qt.Horizontal)
        self._pitch_slider.setRange(50, 200)
        self._pitch_slider.setValue(100)
        self._pitch_spin = QDoubleSpinBox()
        self._pitch_spin.setRange(0.5, 2.0)
        self._pitch_spin.setSingleStep(0.05)
        self._pitch_spin.setValue(1.0)
        self._pitch_slider.valueChanged.connect(
            lambda v: self._pitch_spin.setValue(v / 100.0)
        )
        self._pitch_spin.valueChanged.connect(
            lambda v: self._pitch_slider.setValue(int(round(v * 100)))
        )
        pitch_row.addWidget(self._pitch_slider, 1)
        pitch_row.addWidget(self._pitch_spin)
        fx.addLayout(pitch_row)

        flags = QHBoxLayout()
        self._chk_reverse = QCheckBox("倒放")
        self._chk_8d = QCheckBox("8D 环绕")
        self._chk_reverb = QCheckBox("简单混响")
        flags.addWidget(self._chk_reverse)
        flags.addWidget(self._chk_8d)
        flags.addWidget(self._chk_reverb)
        flags.addStretch()
        fx.addLayout(flags)

        self._summary = QLabel("效果：直通")
        self._summary.setObjectName("InfoText")
        fx.addWidget(self._summary)
        for w in (
            self._speed_spin, self._pitch_spin,
            self._chk_reverse, self._chk_8d, self._chk_reverb,
        ):
            if isinstance(w, QCheckBox):
                w.stateChanged.connect(self._refresh_summary)
            else:
                w.valueChanged.connect(self._refresh_summary)
        root.addWidget(fx_box)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setObjectName("MutedText")
        root.addWidget(self._status)

        btn_row = QHBoxLayout()
        self._btn_run = QPushButton("导出效果")
        self._btn_run.setObjectName("primaryButton")
        self._btn_run.clicked.connect(self._on_run)
        self._btn_open = QPushButton("打开结果")
        self._btn_open.setEnabled(False)
        self._btn_open.clicked.connect(self._on_open_result)
        self._btn_folder = QPushButton("打开目录")
        self._btn_folder.setEnabled(False)
        self._btn_folder.clicked.connect(self._on_open_folder)
        self._btn_reset = QPushButton("重置参数")
        self._btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(self._btn_run)
        btn_row.addWidget(self._btn_open)
        btn_row.addWidget(self._btn_folder)
        btn_row.addWidget(self._btn_reset)
        btn_row.addStretch()
        root.addLayout(btn_row)
        root.addStretch()

        vm.audioFxProgress.connect(self._on_progress)
        vm.audioFxFinished.connect(self._on_finished)
        vm.errorOccurred.connect(self._on_error)
        vm.videoLoaded.connect(self._on_video_loaded)

    def set_media(self, path: str):
        if path and os.path.isfile(path):
            self._src_path = path
            self._path_label.setText(path)

    @Slot(object)
    def _on_video_loaded(self, video):
        if video and getattr(video, "file_path", "") and not self._src_path:
            self.set_media(video.file_path)

    def _params(self) -> AudioFxParams:
        return AudioFxParams(
            speed=float(self._speed_spin.value()),
            pitch=float(self._pitch_spin.value()),
            reverse=self._chk_reverse.isChecked(),
            spatial_8d=self._chk_8d.isChecked(),
            reverb=self._chk_reverb.isChecked(),
        )

    def _refresh_summary(self, *_args):
        self._summary.setText(f"效果：{describe_params(self._params())}")

    def _apply_preset(self, params: AudioFxParams):
        self._speed_spin.setValue(params.speed)
        self._pitch_spin.setValue(params.pitch)
        self._chk_reverse.setChecked(params.reverse)
        self._chk_8d.setChecked(params.spatial_8d)
        self._chk_reverb.setChecked(params.reverb)
        self._refresh_summary()

    @Slot()
    def _on_reset(self):
        self._apply_preset(AudioFxParams())

    @Slot()
    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择音频或视频",
            "",
            "媒体 (*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.mp4 *.mkv *.mov *.webm);;所有文件 (*.*)",
        )
        if path:
            self.set_media(path)

    @Slot()
    def _on_use_current(self):
        video = getattr(self._vm._state, "current_video", None)  # noqa: SLF001
        path = getattr(video, "file_path", "") if video else ""
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "提示", "当前没有已导入的媒体")
            return
        self.set_media(path)

    @Slot()
    def _on_run(self):
        if self._busy:
            return
        src = self._src_path
        if not src or not os.path.isfile(src):
            QMessageBox.warning(self, "提示", "请先选择文件")
            return
        params = self._params()
        if describe_params(params) == "直通":
            QMessageBox.information(self, "提示", "请先调整参数或选一个预设")
            return
        stem = Path(src).stem
        ext = Path(src).suffix.lower()
        is_video = ext in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v"}
        if is_video:
            default = str(Path(src).with_name(f"{stem}_fx.mp4"))
            filt = "MP4 (*.mp4);;所有文件 (*.*)"
        else:
            default = str(Path(src).with_name(f"{stem}_fx.mp3"))
            filt = "MP3 (*.mp3);;WAV (*.wav);;M4A (*.m4a);;所有文件 (*.*)"
        out, _ = QFileDialog.getSaveFileName(self, "保存效果文件", default, filt)
        if not out:
            return
        self._busy = True
        self._btn_run.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._status.setText(f"处理中… {describe_params(params)}")
        self._vm.start_audio_fx(src, out, params)

    @Slot(int, float, str)
    def _on_progress(self, _tid: int, p: float, msg: str):
        self._progress.setValue(int(max(0, min(100, p))))
        if msg:
            self._status.setText(msg)

    @Slot(int, str)
    def _on_finished(self, _tid: int, path: str):
        self._busy = False
        self._btn_run.setEnabled(True)
        self._progress.setValue(100)
        self._result_path = path
        self._btn_open.setEnabled(True)
        self._btn_folder.setEnabled(True)
        self._status.setText(f"完成 · {os.path.basename(path)}")
        QMessageBox.information(self, "音频效果完成", f"已保存：\n{path}")

    @Slot(str)
    def _on_error(self, msg: str):
        if not self._busy:
            return
        self._busy = False
        self._btn_run.setEnabled(True)
        self._status.setText(f"失败: {msg}")
        QMessageBox.warning(self, "音频效果失败", msg)

    @Slot()
    def _on_open_result(self):
        if self._result_path and os.path.isfile(self._result_path):
            os.startfile(self._result_path)  # noqa: S606

    @Slot()
    def _on_open_folder(self):
        if self._result_path:
            os.startfile(str(Path(self._result_path).parent))  # noqa: S606
