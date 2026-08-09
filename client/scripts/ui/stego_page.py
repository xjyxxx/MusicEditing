"""溯源水印：频域封面 / 回声音频 / LSB / EXIF（与去水印分离）。"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from core.blind_watermark_dct import embed_text_dct, extract_text_dct
from core.echo_watermark import (
    embed_echo_watermark, extract_echo_watermark, min_duration_hint,
)
from core.exif_stamp import ExifStamp, stamp_exif
from core.stego_lsb import capacity_hint, embed_text, extract_text
from ui.elided_label import ElidedPathLabel
from ui.studio_kit import wrap_tab_scroll


class StegoPage(QWidget):
    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._img_path = ""
        self._media_path = ""

        root = QVBoxLayout(self)
        tip = QLabel(
            "主动藏信息用于溯源，与「去水印」无关。"
            "频域封面偏 blind-watermark 思路；回声水印偏 HideInfo；均为自研、无额外 pip 包。"
            "LSB 仅适合 PNG；频域对轻度 JPEG 更稳；回声需音轨足够长（见页内提示）。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("MutedText")
        tip.setMaximumHeight(tip.fontMetrics().lineSpacing() * 3 + 4)
        tip.setToolTip(tip.text())
        root.addWidget(tip)

        tabs = QTabWidget()
        tabs.addTab(wrap_tab_scroll(self._build_dct_tab()), "频域封面")
        tabs.addTab(wrap_tab_scroll(self._build_echo_tab()), "回声水印")
        tabs.addTab(wrap_tab_scroll(self._build_lsb_tab()), "LSB（PNG）")
        tabs.addTab(wrap_tab_scroll(self._build_exif_tab()), "EXIF 署名")
        root.addWidget(tabs, 1)
        self._status = ElidedPathLabel("", object_name="MutedText")
        root.addWidget(self._status)

    def set_image(self, path: str):
        if path and os.path.isfile(path):
            self._img_path = path
            self._dct_path.setText(path)
            self._lsb_path.setText(path)
            self._exif_path.setText(path)

    def set_media(self, path: str):
        if path and os.path.isfile(path):
            self._media_path = path
            self._echo_path.setText(path)

    # ── 频域 ──
    def _build_dct_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("在封面/图片 Y 通道 DCT 中频嵌入文字（建议 ≥256×256）。"))
        row = QHBoxLayout()
        self._dct_path = ElidedPathLabel("未选择图片", object_name="InfoText")
        b = QPushButton("打开图片…")
        b.setObjectName("GhostBtn")
        b.clicked.connect(lambda: self._pick_image("_dct"))
        row.addWidget(self._dct_path, 1)
        row.addWidget(b)
        lay.addLayout(row)
        self._dct_text = QTextEdit()
        self._dct_text.setPlaceholderText("要嵌入的文字（≤96 字）")
        self._dct_text.setMaximumHeight(72)
        lay.addWidget(self._dct_text)
        btns = QHBoxLayout()
        be = QPushButton("嵌入频域水印…")
        be.setObjectName("PrimaryBtn")
        be.clicked.connect(self._on_dct_embed)
        bx = QPushButton("提取…")
        bx.setObjectName("GhostBtn")
        bx.clicked.connect(self._on_dct_extract)
        btns.addWidget(be)
        btns.addWidget(bx)
        btns.addStretch()
        lay.addLayout(btns)
        self._dct_out = QLabel("")
        self._dct_out.setObjectName("InfoText")
        self._dct_out.setWordWrap(True)
        lay.addWidget(self._dct_out)
        lay.addStretch()
        return page

    # ── 回声 ──
    def _build_echo_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel(
            f"嵌到成片音轨或 WAV。{min_duration_hint()}。"
            "文字 ≤32 字；过程会重编码音频（视频画面 copy）。"
        ))
        row = QHBoxLayout()
        self._echo_path = ElidedPathLabel("未选择音频/视频", object_name="InfoText")
        b = QPushButton("打开…")
        b.setObjectName("GhostBtn")
        b.clicked.connect(self._pick_media)
        bu = QPushButton("用当前导入")
        bu.setObjectName("GhostBtn")
        bu.clicked.connect(self._echo_use_current)
        row.addWidget(self._echo_path, 1)
        row.addWidget(bu)
        row.addWidget(b)
        lay.addLayout(row)
        self._echo_text = QTextEdit()
        self._echo_text.setPlaceholderText("要嵌入的文字（≤32 字）")
        self._echo_text.setMaximumHeight(72)
        lay.addWidget(self._echo_text)
        btns = QHBoxLayout()
        be = QPushButton("嵌入回声水印…")
        be.setObjectName("PrimaryBtn")
        be.clicked.connect(self._on_echo_embed)
        bx = QPushButton("提取…")
        bx.setObjectName("GhostBtn")
        bx.clicked.connect(self._on_echo_extract)
        btns.addWidget(be)
        btns.addWidget(bx)
        btns.addStretch()
        lay.addLayout(btns)
        self._echo_out = QLabel("")
        self._echo_out.setObjectName("InfoText")
        self._echo_out.setWordWrap(True)
        lay.addWidget(self._echo_out)
        lay.addStretch()
        return page

    # ── LSB ──
    def _build_lsb_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("最低有效位嵌入；请另存 PNG。再压 JPEG 易丢。"))
        row = QHBoxLayout()
        self._lsb_path = ElidedPathLabel("未选择图片", object_name="InfoText")
        b = QPushButton("打开…")
        b.setObjectName("GhostBtn")
        b.clicked.connect(lambda: self._pick_image("_lsb"))
        bc = QPushButton("容量")
        bc.setObjectName("GhostBtn")
        bc.clicked.connect(self._on_lsb_cap)
        row.addWidget(self._lsb_path, 1)
        row.addWidget(bc)
        row.addWidget(b)
        lay.addLayout(row)
        self._lsb_text = QTextEdit()
        self._lsb_text.setMaximumHeight(72)
        lay.addWidget(self._lsb_text)
        btns = QHBoxLayout()
        be = QPushButton("嵌入 LSB…")
        be.setObjectName("PrimaryBtn")
        be.clicked.connect(self._on_lsb_embed)
        bx = QPushButton("提取…")
        bx.setObjectName("GhostBtn")
        bx.clicked.connect(self._on_lsb_extract)
        btns.addWidget(be)
        btns.addWidget(bx)
        btns.addStretch()
        lay.addLayout(btns)
        self._lsb_out = QLabel("")
        self._lsb_out.setWordWrap(True)
        lay.addWidget(self._lsb_out)
        lay.addStretch()
        return page

    # ── EXIF ──
    def _build_exif_tab(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.addWidget(QLabel("写入 Artist / Comment / Copyright（需 ExifTool）。封面工厂导出也可勾选自动署名。"))
        row = QHBoxLayout()
        self._exif_path = ElidedPathLabel("未选择图片", object_name="InfoText")
        b = QPushButton("打开…")
        b.setObjectName("GhostBtn")
        b.clicked.connect(lambda: self._pick_image("_exif"))
        row.addWidget(self._exif_path, 1)
        row.addWidget(b)
        lay.addLayout(row)
        form = QGroupBox("字段")
        fl = QVBoxLayout(form)
        self._artist = QLineEdit()
        self._artist.setPlaceholderText("作者 Artist")
        self._title = QLineEdit()
        self._title.setPlaceholderText("作品名")
        self._comment = QLineEdit()
        self._comment.setPlaceholderText("备注")
        self._copyright = QLineEdit()
        self._copyright.setPlaceholderText("版权")
        for w in (self._artist, self._title, self._comment, self._copyright):
            fl.addWidget(w)
        self._exif_copy = QCheckBox("写入副本（不改原图）")
        self._exif_copy.setChecked(True)
        fl.addWidget(self._exif_copy)
        lay.addWidget(form)
        be = QPushButton("写入 EXIF…")
        be.setObjectName("PrimaryBtn")
        be.clicked.connect(self._on_exif)
        lay.addWidget(be)
        lay.addStretch()
        return page

    def _pick_image(self, which: str):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*.*)",
        )
        if not path:
            return
        self._img_path = path
        if which == "_dct":
            self._dct_path.setText(path)
        elif which == "_lsb":
            self._lsb_path.setText(path)
        else:
            self._exif_path.setText(path)

    def _pick_media(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择音频或视频", "",
            "媒体 (*.mp4 *.mov *.mkv *.wav *.m4a);;所有文件 (*.*)",
        )
        if path:
            self.set_media(path)

    @Slot()
    def _echo_use_current(self):
        video = getattr(self._vm._state, "current_video", None)  # noqa: SLF001
        path = getattr(video, "file_path", "") if video else ""
        if not path:
            QMessageBox.information(self, "提示", "当前没有导入视频")
            return
        self.set_media(path)

    @Slot()
    def _on_dct_embed(self):
        path = self._dct_path.text()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "提示", "请先打开图片")
            return
        text = self._dct_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请填写文字")
            return
        default = str(Path(path).with_name(Path(path).stem + "_dct.png"))
        out, _ = QFileDialog.getSaveFileName(self, "保存", default, "PNG (*.png);;JPEG (*.jpg)")
        if not out:
            return
        try:
            p, n = embed_text_dct(path, out, text)
            self._status.setText(f"频域嵌入 {n} 字节 → {p}")
            self._dct_out.setText(f"已保存：{p}")
            QMessageBox.information(self, "完成", p)
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    @Slot()
    def _on_dct_extract(self):
        path = self._dct_path.text()
        if not path or not os.path.isfile(path):
            path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "图片 (*.png *.jpg *.jpeg)")
        if not path:
            return
        try:
            t = extract_text_dct(path)
            self._dct_out.setText(f"提取：{t}")
            self._dct_text.setPlainText(t)
        except Exception as e:
            QMessageBox.warning(self, "提取失败", str(e))

    @Slot()
    def _on_echo_embed(self):
        path = self._media_path or self._echo_path.text()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "提示", "请先打开媒体")
            return
        text = self._echo_text.toPlainText().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请填写文字")
            return
        stem = Path(path).stem
        ext = Path(path).suffix.lower()
        default = str(Path(path).with_name(f"{stem}_echo" + (ext if ext else ".mp4")))
        out, _ = QFileDialog.getSaveFileName(self, "保存", default, "媒体 (*.mp4 *.wav);;所有文件 (*.*)")
        if not out:
            return
        try:
            p = embed_echo_watermark(path, out, text)
            self._echo_out.setText(f"已保存：{p}")
            self._status.setText(p)
            QMessageBox.information(self, "完成", p)
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    @Slot()
    def _on_echo_extract(self):
        path = self._media_path or self._echo_path.text()
        if not path or not os.path.isfile(path):
            path, _ = QFileDialog.getOpenFileName(self, "选择媒体", "", "媒体 (*.mp4 *.wav *.mkv)")
        if not path:
            return
        try:
            t = extract_echo_watermark(path)
            self._echo_out.setText(f"提取：{t}")
            self._echo_text.setPlainText(t)
        except Exception as e:
            QMessageBox.warning(self, "提取失败", str(e))

    @Slot()
    def _on_lsb_cap(self):
        path = self._lsb_path.text()
        if not path or not os.path.isfile(path):
            return
        try:
            QMessageBox.information(self, "容量", capacity_hint(path))
        except Exception as e:
            QMessageBox.warning(self, "容量", str(e))

    @Slot()
    def _on_lsb_embed(self):
        path = self._lsb_path.text()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "提示", "请先打开图片")
            return
        text = self._lsb_text.toPlainText().strip()
        if not text:
            return
        default = str(Path(path).with_name(Path(path).stem + "_lsb.png"))
        out, _ = QFileDialog.getSaveFileName(self, "保存 PNG", default, "PNG (*.png)")
        if not out:
            return
        try:
            p, n = embed_text(path, out, text)
            self._lsb_out.setText(f"已嵌入 {n} 字节 → {p}")
            QMessageBox.information(self, "完成", p)
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    @Slot()
    def _on_lsb_extract(self):
        path = self._lsb_path.text()
        if not path or not os.path.isfile(path):
            path, _ = QFileDialog.getOpenFileName(self, "选择图片", "", "图片 (*.png)")
        if not path:
            return
        try:
            t = extract_text(path)
            self._lsb_out.setText(f"提取：{t}")
            self._lsb_text.setPlainText(t)
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))

    @Slot()
    def _on_exif(self):
        path = self._exif_path.text()
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, "提示", "请先打开图片")
            return
        stamp = ExifStamp(
            artist=self._artist.text(),
            title=self._title.text(),
            comment=self._comment.text(),
            copyright=self._copyright.text(),
        )
        out = None
        if self._exif_copy.isChecked():
            stem = Path(path).stem
            ext = Path(path).suffix or ".jpg"
            default = str(Path(path).with_name(f"{stem}_signed{ext}"))
            out, _ = QFileDialog.getSaveFileName(self, "保存副本", default, "图片 (*.png *.jpg)")
            if not out:
                return
        try:
            p = stamp_exif(path, stamp, output_path=out)
            self._status.setText(f"EXIF → {p}")
            QMessageBox.information(self, "完成", p)
        except Exception as e:
            QMessageBox.warning(self, "失败", str(e))
