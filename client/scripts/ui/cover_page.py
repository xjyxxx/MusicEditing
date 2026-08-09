"""封面工厂：选最清晰帧 + 大字标题 PNG（短视频封面）。"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSpinBox, QTextEdit,
    QVBoxLayout, QWidget,
)

from core.blind_watermark_dct import embed_text_dct
from core.cover_factory import COVER_SIZES
from core.exif_stamp import ExifStamp, stamp_exif
from ui.elided_label import ElidedPathLabel
from ui.studio_kit import wrap_studio_scroll
from ui.theme import style_spinbox
from viewmodels.main_vm import MainViewModel


class CoverPage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._src_path = ""
        self._result_path = ""
        self._busy = False

        # 外层：可滚动正文 + 底栏按钮（避免预览框被窗口裁成半截）
        outer, _body, root = wrap_studio_scroll(self)
        root.setSpacing(12)

        tip = QLabel(
            "在已有缩略图抽取之上，均匀抽样多帧，用 Laplacian 锐度选最清晰画面，"
            "再叠加大字标题导出 PNG（默认竖屏 9:16 短视频封面）。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("MutedText")
        tip.setMaximumHeight(tip.fontMetrics().lineSpacing() * 3 + 4)
        tip.setToolTip(tip.text())
        root.addWidget(tip)

        src_box = QGroupBox("视频")
        src_lay = QVBoxLayout(src_box)
        src_lay.setContentsMargins(10, 8, 10, 10)
        src_lay.setSpacing(8)
        row = QHBoxLayout()
        self._path_label = ElidedPathLabel("未选择文件", object_name="InfoText")
        btn_open = QPushButton("打开视频…")
        btn_open.setObjectName("GhostBtn")
        btn_open.clicked.connect(self._on_open)
        btn_use = QPushButton("使用当前导入")
        btn_use.setObjectName("GhostBtn")
        btn_use.clicked.connect(self._on_use_current)
        row.addWidget(self._path_label, 1)
        row.addWidget(btn_use)
        row.addWidget(btn_open)
        src_lay.addLayout(row)
        root.addWidget(src_box)

        opt_box = QGroupBox("封面参数")
        opt = QVBoxLayout(opt_box)
        opt.setContentsMargins(10, 8, 10, 10)
        opt.setSpacing(8)
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("大标题"))
        self._title = QLineEdit()
        self._title.setPlaceholderText("例如：今日高光")
        title_row.addWidget(self._title, 1)
        opt.addLayout(title_row)

        sub_row = QHBoxLayout()
        sub_row.addWidget(QLabel("副标题"))
        self._subtitle = QLineEdit()
        self._subtitle.setPlaceholderText("可选")
        sub_row.addWidget(self._subtitle, 1)
        opt.addLayout(sub_row)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("尺寸"))
        self._size = QComboBox()
        for name in COVER_SIZES:
            self._size.addItem(name)
        size_row.addWidget(self._size)
        size_row.addWidget(QLabel("抽样帧数"))
        self._count = QSpinBox()
        self._count.setRange(4, 36)
        self._count.setValue(12)
        style_spinbox(self._count)
        size_row.addWidget(self._count)
        size_row.addStretch()
        opt.addLayout(size_row)
        root.addWidget(opt_box)

        stamp_box = QGroupBox("导出后溯源（可选）")
        stamp_lay = QVBoxLayout(stamp_box)
        stamp_lay.setContentsMargins(10, 8, 10, 10)
        stamp_lay.setSpacing(6)
        self._chk_exif = QCheckBox("写入 EXIF 署名（作者=大标题，备注含 MusicEditing）")
        self._chk_dct = QCheckBox("嵌入频域隐形水印（文字=大标题）")
        self._chk_exif.setChecked(False)
        self._chk_dct.setChecked(False)
        stamp_lay.addWidget(self._chk_exif)
        stamp_lay.addWidget(self._chk_dct)
        tip_s = QLabel("频域水印会就地改写导出的 PNG；需 ExifTool 才写 EXIF。")
        tip_s.setObjectName("MutedText")
        tip_s.setWordWrap(True)
        stamp_lay.addWidget(tip_s)
        root.addWidget(stamp_box)

        preview_box = QGroupBox("预览")
        preview_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        prev = QHBoxLayout(preview_box)
        prev.setContentsMargins(10, 8, 10, 10)
        prev.setSpacing(10)
        self._preview = QLabel("生成后显示封面")
        self._preview.setAlignment(Qt.AlignCenter)
        # 完整预览高度；窗口矮时靠外层滚动，不再被裁成半截
        self._preview.setMinimumHeight(360)
        self._preview.setMinimumWidth(200)
        self._preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._preview.setStyleSheet(
            "background: #080A0E; border: 1px solid #2A3140; border-radius: 8px; color: #8B95A8;"
        )
        self._preview.setScaledContents(False)
        prev.addWidget(self._preview, 1)
        self._meta = QTextEdit()
        self._meta.setReadOnly(True)
        self._meta.setMaximumWidth(280)
        self._meta.setMinimumHeight(360)
        self._meta.setPlaceholderText("锐度 / 时间点 / 尺寸…")
        prev.addWidget(self._meta)
        root.addWidget(preview_box, 0)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setObjectName("MutedText")
        root.addWidget(self._status)
        root.addStretch(1)

        # 底栏固定在滚动区外，始终可见
        footer = QWidget()
        btn_row = QHBoxLayout(footer)
        btn_row.setContentsMargins(12, 8, 12, 10)
        btn_row.setSpacing(10)
        self._btn_run = QPushButton("生成封面")
        self._btn_run.setObjectName("primaryButton")
        self._btn_run.clicked.connect(self._on_run)
        self._btn_open_out = QPushButton("打开结果")
        self._btn_open_out.setEnabled(False)
        self._btn_open_out.clicked.connect(self._on_open_result)
        self._btn_folder = QPushButton("打开目录")
        self._btn_folder.setEnabled(False)
        self._btn_folder.clicked.connect(self._on_open_folder)
        btn_row.addWidget(self._btn_run)
        btn_row.addWidget(self._btn_open_out)
        btn_row.addWidget(self._btn_folder)
        btn_row.addStretch()
        outer.addWidget(footer, 0)

        vm.coverProgress.connect(self._on_progress)
        vm.coverFinished.connect(self._on_finished)
        vm.errorOccurred.connect(self._on_error)
        vm.videoLoaded.connect(self._on_video_loaded)

    def set_video(self, path: str):
        if path and os.path.isfile(path):
            self._src_path = path
            self._path_label.setText(path)
            if not self._title.text().strip():
                self._title.setText(Path(path).stem[:24])

    @Slot(object)
    def _on_video_loaded(self, video):
        if video and getattr(video, "file_path", ""):
            # 不强制覆盖用户已选手动文件
            if not self._src_path:
                self.set_video(video.file_path)

    @Slot()
    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频",
            "",
            "视频 (*.mp4 *.mkv *.mov *.avi *.webm *.flv);;所有文件 (*.*)",
        )
        if path:
            self.set_video(path)

    @Slot()
    def _on_use_current(self):
        video = getattr(self._vm, "current_video", None)
        if video is None:
            video = getattr(self._vm._state, "current_video", None)  # noqa: SLF001
        path = getattr(video, "file_path", "") if video else ""
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "提示", "当前没有已导入的视频")
            return
        self.set_video(path)

    def _duration(self) -> float:
        video = getattr(self._vm._state, "current_video", None)  # noqa: SLF001
        if video and getattr(video, "file_path", "") == self._src_path:
            d = float(getattr(video, "duration_sec", 0) or 0)
            if d > 0:
                return d
        bridge = self._vm.bridge
        if bridge and self._src_path:
            try:
                return float(bridge.probe_duration(self._src_path) or 0)
            except Exception:
                pass
        return 0.0

    @Slot()
    def _on_run(self):
        if self._busy:
            return
        src = self._src_path
        if not src or not os.path.isfile(src):
            QMessageBox.warning(self, "提示", "请先选择视频")
            return
        title = self._title.text().strip() or Path(src).stem
        size_name = self._size.currentText()
        w, h = COVER_SIZES.get(size_name, (1080, 1920))
        stem = Path(src).stem
        default = str(Path(src).with_name(f"{stem}_cover.png"))
        out, _ = QFileDialog.getSaveFileName(
            self, "保存封面 PNG", default, "PNG (*.png);;所有文件 (*.*)",
        )
        if not out:
            return
        if not out.lower().endswith(".png"):
            out += ".png"
        dur = self._duration()
        self._busy = True
        self._btn_run.setEnabled(False)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._status.setText("正在选最清晰帧并绘制封面…")
        self._vm.start_cover_factory(
            src,
            out,
            title,
            subtitle=self._subtitle.text().strip(),
            duration_sec=dur,
            count=self._count.value(),
            width=w,
            height=h,
        )

    @Slot(int, float, str)
    def _on_progress(self, _tid: int, p: float, msg: str):
        self._progress.setValue(int(max(0, min(100, p))))
        if msg:
            self._status.setText(msg)

    @Slot(int, str, object)
    def _on_finished(self, _tid: int, path: str, meta):
        self._busy = False
        self._btn_run.setEnabled(True)
        self._progress.setValue(100)
        self._result_path = path
        self._btn_open_out.setEnabled(True)
        self._btn_folder.setEnabled(True)
        self._status.setText(f"封面完成 · {os.path.basename(path)}")
        pix = QPixmap(path)
        if not pix.isNull():
            self._preview.setPixmap(
                pix.scaled(
                    self._preview.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
            )
        lines = [f"文件: {path}"]
        if meta:
            lines.append(f"时间点: {getattr(meta, 'time_sec', 0):.2f}s")
            lines.append(f"锐度: {getattr(meta, 'sharpness', 0):.1f}")
            size = getattr(meta, "size", None)
            if size:
                lines.append(f"尺寸: {size[0]}×{size[1]}")
        extra = []
        title = self._title.text().strip() or Path(path).stem
        if path and os.path.isfile(path) and self._chk_dct.isChecked():
            try:
                embed_text_dct(path, path, title[:96])
                extra.append("已嵌频域水印")
            except Exception as e:
                extra.append(f"频域水印失败: {e}")
        if path and os.path.isfile(path) and self._chk_exif.isChecked():
            try:
                stamp_exif(
                    path,
                    ExifStamp(
                        artist=title[:64],
                        title=title[:128],
                        comment=f"MusicEditing cover · {self._subtitle.text().strip()}",
                        copyright="MusicEditing",
                    ),
                    output_path=None,
                )
                extra.append("已写 EXIF")
            except Exception as e:
                extra.append(f"EXIF 失败: {e}")
        if extra:
            lines.append(" · ".join(extra))
            self._status.setText(self._status.text() + " · " + " · ".join(extra))
        self._meta.setPlainText("\n".join(lines))
        tip = f"已保存：\n{path}"
        if extra:
            tip += "\n" + "\n".join(extra)
        QMessageBox.information(self, "封面完成", tip)

    @Slot(str)
    def _on_error(self, msg: str):
        if not self._busy:
            return
        self._busy = False
        self._btn_run.setEnabled(True)
        self._status.setText(f"失败: {msg}")
        QMessageBox.warning(self, "封面失败", msg)

    @Slot()
    def _on_open_result(self):
        if self._result_path and os.path.isfile(self._result_path):
            os.startfile(self._result_path)  # noqa: S606

    @Slot()
    def _on_open_folder(self):
        if self._result_path:
            folder = str(Path(self._result_path).parent)
            os.startfile(folder)  # noqa: S606

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._result_path and os.path.isfile(self._result_path):
            pix = QPixmap(self._result_path)
            if not pix.isNull():
                self._preview.setPixmap(
                    pix.scaled(
                        self._preview.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation,
                    )
                )
