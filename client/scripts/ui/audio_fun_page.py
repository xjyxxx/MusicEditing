"""音频趣味页：整轨效果 + 梗音叠加。"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QSlider, QTabWidget, QVBoxLayout, QWidget,
)

from core.audio_fx import PRESETS, AudioFxParams, describe_params
from core.sfx_overlay import SfxOverlayParams, list_sfx_library, sfx_dirs
from ui.elided_label import ElidedPathLabel
from ui.studio_kit import (
    make_studio_hero,
    studio_page_stylesheet,
    wrap_tab_scroll,
)
from ui.theme import style_spinbox
from viewmodels.main_vm import MainViewModel


class AudioFunPage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._src_path = ""
        self._result_path = ""
        self._busy = False
        self._sfx_path = ""
        self._sfx_busy = False
        self.setObjectName("AudioFunPage")
        self.setStyleSheet(studio_page_stylesheet("AudioFunPage"))

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)
        root.addWidget(make_studio_hero(
            "音频趣味",
            "整轨变调/变速/倒放/伪8D/混响，或叠加梗音。作用于视频时会尽量保持音画同步。",
            "趣味",
        ))
        tabs = QTabWidget()
        tabs.addTab(wrap_tab_scroll(self._build_track_tab()), "整轨趣味")
        tabs.addTab(wrap_tab_scroll(self._build_sfx_tab()), "梗音叠加")
        root.addWidget(tabs)

        vm.audioFxProgress.connect(self._on_progress)
        vm.audioFxFinished.connect(self._on_finished)
        vm.sfxOverlayProgress.connect(self._on_sfx_progress)
        vm.sfxOverlayFinished.connect(self._on_sfx_finished)
        vm.errorOccurred.connect(self._on_error)
        vm.videoLoaded.connect(self._on_video_loaded)

    def _build_track_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        tip = QLabel(
            "变调(asetrate)、变速(atempo+视频 setpts)、倒放(areverse+视频 reverse)、"
            "伪 8D(apulsator)、简单混响(aecho)。"
            "作用于视频时：变速/倒放会同步改画面时间轴，避免音画不同步；"
            "仅变调/8D/混响仍可 copy 视频轨。"
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
        self._speed_slider.setRange(25, 400)
        self._speed_slider.setValue(100)
        self._speed_spin = QDoubleSpinBox()
        self._speed_spin.setRange(0.25, 4.0)
        self._speed_spin.setSingleStep(0.05)
        self._speed_spin.setValue(1.0)
        style_spinbox(self._speed_spin)
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
        style_spinbox(self._pitch_spin)
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
        return page

    def _build_sfx_tab(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        tip = QLabel(
            "把短音效叠到视频指定时刻，支持搞笑倍数（如 1.5× / 2×）。"
            "热梗原声（如「我还记得你」）请自行放入 assets/sfx/user/，本软件不内置版权音。"
            "列表会自动带几段免费演示音（叮/鼓点）。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("MutedText")
        root.addWidget(tip)

        vid_box = QGroupBox("成片视频")
        vid_lay = QHBoxLayout(vid_box)
        self._sfx_video_label = ElidedPathLabel("未选择视频", object_name="InfoText")
        btn_v = QPushButton("打开…")
        btn_v.clicked.connect(self._on_sfx_open_video)
        btn_vu = QPushButton("用当前导入")
        btn_vu.clicked.connect(self._on_sfx_use_current)
        vid_lay.addWidget(self._sfx_video_label, 1)
        vid_lay.addWidget(btn_vu)
        vid_lay.addWidget(btn_v)
        root.addWidget(vid_box)

        lib_box = QGroupBox("音效库")
        lib_lay = QVBoxLayout(lib_box)
        self._sfx_list = QListWidget()
        self._sfx_list.currentItemChanged.connect(self._on_sfx_selected)
        lib_lay.addWidget(self._sfx_list)
        lib_btns = QHBoxLayout()
        btn_refresh = QPushButton("刷新")
        btn_refresh.setObjectName("GhostBtn")
        btn_refresh.clicked.connect(self._refresh_sfx_list)
        btn_import = QPushButton("导入到 user…")
        btn_import.setObjectName("GhostBtn")
        btn_import.clicked.connect(self._on_sfx_import)
        btn_folder = QPushButton("打开 user 目录")
        btn_folder.setObjectName("GhostBtn")
        btn_folder.clicked.connect(self._on_open_user_sfx)
        btn_preview = QPushButton("试听")
        btn_preview.setObjectName("GhostBtn")
        btn_preview.clicked.connect(self._on_sfx_preview)
        lib_btns.addWidget(btn_refresh)
        lib_btns.addWidget(btn_import)
        lib_btns.addWidget(btn_folder)
        lib_btns.addWidget(btn_preview)
        lib_btns.addStretch()
        lib_lay.addLayout(lib_btns)
        root.addWidget(lib_box, 1)

        param = QGroupBox("插入参数")
        pl = QVBoxLayout(param)
        t_row = QHBoxLayout()
        t_row.addWidget(QLabel("时刻(秒)"))
        self._sfx_start = QDoubleSpinBox()
        self._sfx_start.setRange(0.0, 36000.0)
        self._sfx_start.setDecimals(2)
        self._sfx_start.setSingleStep(0.1)
        style_spinbox(self._sfx_start)
        t_row.addWidget(self._sfx_start)
        t_row.addStretch()
        pl.addLayout(t_row)

        sp_row = QHBoxLayout()
        sp_row.addWidget(QLabel("倍数"))
        self._sfx_speed = QDoubleSpinBox()
        self._sfx_speed.setRange(0.5, 4.0)
        self._sfx_speed.setSingleStep(0.25)
        self._sfx_speed.setValue(1.0)
        style_spinbox(self._sfx_speed)
        sp_row.addWidget(self._sfx_speed)
        for label, val in (("0.75×慢", 0.75), ("1×", 1.0), ("1.5×", 1.5), ("2×搞笑", 2.0)):
            b = QPushButton(label)
            b.setObjectName("PresetBtn")
            b.clicked.connect(lambda _=False, v=val: self._sfx_speed.setValue(v))
            sp_row.addWidget(b)
        sp_row.addStretch()
        pl.addLayout(sp_row)

        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("音效音量"))
        self._sfx_vol = QSlider(Qt.Horizontal)
        self._sfx_vol.setRange(20, 250)
        self._sfx_vol.setValue(120)
        self._sfx_vol_lbl = QLabel("1.20")
        self._sfx_vol.valueChanged.connect(
            lambda v: self._sfx_vol_lbl.setText(f"{v / 100:.2f}")
        )
        vol_row.addWidget(self._sfx_vol, 1)
        vol_row.addWidget(self._sfx_vol_lbl)
        pl.addLayout(vol_row)

        self._sfx_duck = QCheckBox("叠加时略压原声（更突出梗音）")
        pl.addWidget(self._sfx_duck)
        root.addWidget(param)

        self._sfx_progress = QProgressBar()
        self._sfx_progress.setVisible(False)
        root.addWidget(self._sfx_progress)
        self._sfx_status = QLabel("")
        self._sfx_status.setObjectName("MutedText")
        root.addWidget(self._sfx_status)

        run_row = QHBoxLayout()
        self._btn_sfx_run = QPushButton("导出叠加成片")
        self._btn_sfx_run.setObjectName("primaryButton")
        self._btn_sfx_run.clicked.connect(self._on_sfx_run)
        run_row.addWidget(self._btn_sfx_run)
        run_row.addStretch()
        root.addLayout(run_row)

        self._refresh_sfx_list()
        return page

    def set_media(self, path: str):
        if path and os.path.isfile(path):
            self._src_path = path
            self._path_label.setText(path)
            ext = Path(path).suffix.lower()
            if ext in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}:
                self._sfx_video_label.setText(path)

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

    @Slot()
    def _refresh_sfx_list(self):
        self._sfx_list.clear()
        for item in list_sfx_library():
            tag = "自备" if item.source == "user" else "演示"
            it = QListWidgetItem(f"[{tag}] {item.name}")
            it.setData(Qt.UserRole, item.path)
            self._sfx_list.addItem(it)
        if self._sfx_list.count() == 0:
            self._sfx_list.addItem(QListWidgetItem("（库空：请导入音效到 user/）"))

    def _on_sfx_selected(self, cur: QListWidgetItem, _prev):
        if not cur:
            self._sfx_path = ""
            return
        path = cur.data(Qt.UserRole) or ""
        self._sfx_path = str(path) if path else ""

    @Slot()
    def _on_sfx_open_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频",
            "",
            "视频 (*.mp4 *.mov *.mkv *.avi *.webm);;所有文件 (*.*)",
        )
        if path:
            self._sfx_video_label.setText(path)
            self._src_path = path

    @Slot()
    def _on_sfx_use_current(self):
        self._on_use_current()
        if self._src_path:
            self._sfx_video_label.setText(self._src_path)

    @Slot()
    def _on_sfx_import(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "导入音效到 user",
            "",
            "音频 (*.mp3 *.wav *.m4a *.aac *.ogg *.flac);;所有文件 (*.*)",
        )
        if not files:
            return
        dest = sfx_dirs()[0]
        dest.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in files:
            try:
                target = dest / Path(f).name
                if not target.exists():
                    import shutil
                    shutil.copy2(f, target)
                    n += 1
                else:
                    # 覆盖同名
                    import shutil
                    shutil.copy2(f, target)
                    n += 1
            except OSError:
                pass
        self._refresh_sfx_list()
        QMessageBox.information(self, "导入", f"已放入 user/：{n} 个文件")

    @Slot()
    def _on_open_user_sfx(self):
        d = sfx_dirs()[0]
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))  # noqa: S606

    @Slot()
    def _on_sfx_preview(self):
        if not self._sfx_path or not os.path.isfile(self._sfx_path):
            QMessageBox.information(self, "试听", "请先选中一条音效")
            return
        try:
            os.startfile(self._sfx_path)  # noqa: S606
        except OSError as e:
            QMessageBox.warning(self, "试听", str(e))

    @Slot()
    def _on_sfx_run(self):
        if self._sfx_busy:
            return
        video = self._sfx_video_label.text().strip()
        if not video or not os.path.isfile(video) or video.startswith("未选择"):
            QMessageBox.warning(self, "提示", "请先选择成片视频")
            return
        if not self._sfx_path or not os.path.isfile(self._sfx_path):
            QMessageBox.warning(self, "提示", "请先选择音效（可导入到 user/）")
            return
        stem = Path(video).stem
        default = str(Path(video).with_name(f"{stem}_sfx.mp4"))
        out, _ = QFileDialog.getSaveFileName(
            self, "保存叠加成片", default, "MP4 (*.mp4);;所有文件 (*.*)",
        )
        if not out:
            return
        params = SfxOverlayParams(
            start_sec=float(self._sfx_start.value()),
            speed=float(self._sfx_speed.value()),
            sfx_volume=self._sfx_vol.value() / 100.0,
            voice_volume=1.0,
            duck_voice=self._sfx_duck.isChecked(),
        )
        self._sfx_busy = True
        self._btn_sfx_run.setEnabled(False)
        self._sfx_progress.setVisible(True)
        self._sfx_progress.setValue(0)
        self._sfx_status.setText(
            f"叠加中… {os.path.basename(self._sfx_path)} @ {params.start_sec:.2f}s · {params.speed:.2f}×"
        )
        self._vm.start_sfx_overlay(video, self._sfx_path, out, params)

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

    @Slot(int, float, str)
    def _on_sfx_progress(self, _tid: int, p: float, msg: str):
        self._sfx_progress.setValue(int(max(0, min(100, p))))
        if msg:
            self._sfx_status.setText(msg)

    @Slot(int, str)
    def _on_sfx_finished(self, _tid: int, path: str):
        self._sfx_busy = False
        self._btn_sfx_run.setEnabled(True)
        self._sfx_progress.setValue(100)
        self._result_path = path
        self._sfx_status.setText(f"完成 · {os.path.basename(path)}")
        QMessageBox.information(self, "梗音叠加完成", f"已保存：\n{path}")

    @Slot(str)
    def _on_error(self, msg: str):
        if self._busy:
            self._busy = False
            self._btn_run.setEnabled(True)
            self._status.setText(f"失败: {msg}")
            QMessageBox.warning(self, "音频效果失败", msg)
            return
        if self._sfx_busy:
            self._sfx_busy = False
            self._btn_sfx_run.setEnabled(True)
            self._sfx_status.setText(f"失败: {msg}")
            QMessageBox.warning(self, "梗音叠加失败", msg)

    @Slot()
    def _on_open_result(self):
        if self._result_path and os.path.isfile(self._result_path):
            os.startfile(self._result_path)  # noqa: S606

    @Slot()
    def _on_open_folder(self):
        if self._result_path:
            os.startfile(str(Path(self._result_path).parent))  # noqa: S606
