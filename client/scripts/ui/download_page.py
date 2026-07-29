"""链接下载：嵌套 Tab — 下载 / 仅获取信息（列表可播放、可删除）。"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QProgressBar, QPushButton,
    QRadioButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from viewmodels.main_vm import MainViewModel

_ROLE_ITEM = Qt.UserRole


class DownloadPage(QWidget):
    """预览播放请求：由 MainWindow 打开首页播放器。"""
    previewPlayRequested = Signal(str)

    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._busy = False
        self._probe_for_info_tab = False
        self._awaiting_preview = False
        self._page_url = ""
        self._out_dir = os.path.join(
            os.path.expanduser("~"), "MusicEditingDownloads"
        )

        root = QVBoxLayout(self)
        tip = QLabel(
            "引擎：third_party/yt-dlp + 项目 FFmpeg。"
            "「仅获取信息」可点列表播放/删除；播放会短暂拉取到临时文件。"
            "请仅处理自有或已获授权内容。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#9a9ab0; padding:6px;")
        root.addWidget(tip)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_download_tab(), "下载")
        self._tabs.addTab(self._build_info_tab(), "仅获取信息")
        root.addWidget(self._tabs, 1)

        yt_ok = bool(vm.bridge and getattr(vm.bridge, "yt_dlp_available", False))
        if not yt_ok:
            self._dl_status.setText(
                "未找到 yt-dlp.exe。请运行 scripts\\download_yt_dlp.bat"
            )
            self._btn_dl.setEnabled(False)
            self._btn_probe.setEnabled(False)
            self._btn_info_fetch.setEnabled(False)

        vm.downloadProgress.connect(self._on_progress)
        vm.downloadFinished.connect(self._on_finished)
        vm.downloadProbeReady.connect(self._on_probe_ready)
        vm.errorOccurred.connect(self._on_error)

    def _build_download_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        url_box = QGroupBox("链接")
        url_lay = QVBoxLayout(url_box)
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("https://…")
        url_lay.addWidget(self._url_edit)
        row = QHBoxLayout()
        self._btn_paste = QPushButton("粘贴")
        self._btn_paste.clicked.connect(self._on_paste_dl)
        self._btn_probe = QPushButton("探测信息")
        self._btn_probe.clicked.connect(self._on_probe_dl)
        row.addWidget(self._btn_paste)
        row.addWidget(self._btn_probe)
        row.addStretch()
        url_lay.addLayout(row)
        lay.addWidget(url_box)

        mode_box = QGroupBox("下载类型")
        mode_lay = QHBoxLayout(mode_box)
        self._mode_video = QRadioButton("视频（MP4）")
        self._mode_audio = QRadioButton("仅音频（MP3）")
        self._mode_video.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self._mode_video)
        grp.addButton(self._mode_audio)
        mode_lay.addWidget(self._mode_video)
        mode_lay.addWidget(self._mode_audio)
        mode_lay.addStretch()
        lay.addWidget(mode_box)

        out_row = QHBoxLayout()
        self._out_label = QLabel(self._out_dir)
        self._out_label.setStyleSheet("color:#8cf;")
        btn_out = QPushButton("保存目录…")
        btn_out.clicked.connect(self._on_pick_dir)
        out_row.addWidget(QLabel("保存到:"))
        out_row.addWidget(self._out_label, 1)
        out_row.addWidget(btn_out)
        lay.addLayout(out_row)

        self._info = QTextEdit()
        self._info.setReadOnly(True)
        self._info.setMaximumHeight(100)
        self._info.setPlaceholderText("探测摘要…")
        lay.addWidget(self._info)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        lay.addWidget(self._progress)

        self._dl_status = QLabel("")
        self._dl_status.setStyleSheet("color:#aaa;")
        lay.addWidget(self._dl_status)

        btn_row = QHBoxLayout()
        self._btn_dl = QPushButton("开始下载")
        self._btn_dl.setStyleSheet(
            "background:#5b5bd6; color:white; padding:10px 22px; font-weight:600;"
        )
        self._btn_dl.clicked.connect(self._on_download)
        btn_row.addWidget(self._btn_dl)
        btn_row.addStretch()
        lay.addLayout(btn_row)
        lay.addStretch()
        return w

    def _build_info_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        hint = QLabel(
            "获取名称与列表（不保存到下载目录）。"
            "双击或点「播放」可试听；「删除」只从本列表移除。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9a9ab0;")
        lay.addWidget(hint)

        url_row = QHBoxLayout()
        self._info_url = QLineEdit()
        self._info_url.setPlaceholderText("粘贴歌曲 / 视频 / 歌单链接…")
        btn_paste = QPushButton("粘贴")
        btn_paste.clicked.connect(self._on_paste_info)
        self._btn_info_fetch = QPushButton("获取信息")
        self._btn_info_fetch.setStyleSheet(
            "background:#5b5bd6; color:white; padding:8px 16px; font-weight:600;"
        )
        self._btn_info_fetch.clicked.connect(self._on_fetch_info)
        url_row.addWidget(self._info_url, 1)
        url_row.addWidget(btn_paste)
        url_row.addWidget(self._btn_info_fetch)
        lay.addLayout(url_row)

        self._name_label = QLabel("名称：—")
        self._name_label.setStyleSheet(
            "font-size:16px; font-weight:700; color:#e0e0ff; padding:8px 0;"
        )
        self._name_label.setWordWrap(True)
        lay.addWidget(self._name_label)

        self._meta_label = QLabel("")
        self._meta_label.setStyleSheet("color:#8cf;")
        self._meta_label.setWordWrap(True)
        lay.addWidget(self._meta_label)

        self._hint_label = QLabel("")
        self._hint_label.setStyleSheet("color:#e8a87c;")
        self._hint_label.setWordWrap(True)
        lay.addWidget(self._hint_label)

        lay.addWidget(QLabel("列表（双击播放）："))
        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background:#2d2d3a; border:1px solid #555; }"
            "QListWidget::item:selected { background:#5b5bd6; }"
        )
        self._list.itemDoubleClicked.connect(self._on_item_play)
        lay.addWidget(self._list, 1)

        act_row = QHBoxLayout()
        self._btn_play = QPushButton("播放选中")
        self._btn_play.clicked.connect(self._on_play_selected)
        self._btn_del = QPushButton("删除选中")
        self._btn_del.clicked.connect(self._on_delete_selected)
        self._btn_clear = QPushButton("清空列表")
        self._btn_clear.clicked.connect(self._on_clear_list)
        act_row.addWidget(self._btn_play)
        act_row.addWidget(self._btn_del)
        act_row.addWidget(self._btn_clear)
        act_row.addStretch()
        lay.addLayout(act_row)

        self._info_status = QLabel("")
        self._info_status.setStyleSheet("color:#aaa;")
        lay.addWidget(self._info_status)

        use_row = QHBoxLayout()
        btn_to_dl = QPushButton("用此链接去下载")
        btn_to_dl.clicked.connect(self._send_url_to_download_tab)
        use_row.addWidget(btn_to_dl)
        use_row.addStretch()
        lay.addLayout(use_row)
        return w

    @Slot()
    def _on_paste_dl(self):
        from PySide6.QtWidgets import QApplication
        text = QApplication.clipboard().text().strip()
        if text:
            self._url_edit.setText(text)

    @Slot()
    def _on_paste_info(self):
        from PySide6.QtWidgets import QApplication
        text = QApplication.clipboard().text().strip()
        if text:
            self._info_url.setText(text)

    @Slot()
    def _on_pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存目录", self._out_dir)
        if d:
            self._out_dir = d
            self._out_label.setText(d)

    @Slot()
    def _on_probe_dl(self):
        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请先粘贴链接")
            return
        self._probe_for_info_tab = False
        self._set_busy(True)
        self._dl_status.setText("正在探测…")
        self._vm.probe_download_url(url, False)

    @Slot()
    def _on_fetch_info(self):
        url = self._info_url.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请先粘贴链接")
            return
        self._probe_for_info_tab = True
        self._set_busy(True)
        self._info_status.setText("正在获取（不落盘到下载目录）…")
        self._list.clear()
        self._vm.probe_download_url(url, True)

    @Slot()
    def _on_download(self):
        url = self._url_edit.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请先粘贴链接")
            return
        self._awaiting_preview = False
        self._set_busy(True)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._vm.start_url_download(
            url,
            self._out_dir,
            audio_only=self._mode_audio.isChecked(),
        )

    @Slot()
    def _send_url_to_download_tab(self):
        url = self._info_url.text().strip()
        if not url:
            QMessageBox.warning(self, "提示", "请先获取或填写链接")
            return
        self._url_edit.setText(url)
        self._tabs.setCurrentIndex(0)

    def _selected_item_data(self):
        row = self._list.currentRow()
        if row < 0:
            return None
        it = self._list.item(row)
        if not it:
            return None
        return it.data(_ROLE_ITEM)

    @Slot(QListWidgetItem)
    def _on_item_play(self, _item: QListWidgetItem):
        self._on_play_selected()

    @Slot()
    def _on_play_selected(self):
        data = self._selected_item_data()
        if data is None:
            QMessageBox.warning(self, "提示", "请先选中列表中的一项")
            return
        self._awaiting_preview = True
        self._set_busy(True)
        self._info_status.setText("正在准备播放…")
        self._vm.preview_list_item(data)

    @Slot()
    def _on_delete_selected(self):
        rows = sorted({i.row() for i in self._list.selectedIndexes()}, reverse=True)
        if not rows:
            cur = self._list.currentRow()
            if cur < 0:
                QMessageBox.warning(self, "提示", "请先选中要删除的项")
                return
            rows = [cur]
        for r in rows:
            self._list.takeItem(r)
        self._info_status.setText(f"列表剩余 {self._list.count()} 条")

    @Slot()
    def _on_clear_list(self):
        self._list.clear()
        self._info_status.setText("列表已清空")

    def _set_busy(self, busy: bool):
        self._busy = busy
        self._btn_dl.setEnabled(not busy)
        self._btn_probe.setEnabled(not busy)
        self._btn_info_fetch.setEnabled(not busy)
        self._btn_play.setEnabled(not busy)

    @Slot(int, float, str)
    def _on_progress(self, _task_id: int, progress: float, msg: str):
        if self._awaiting_preview:
            self._info_status.setText(msg)
            return
        self._progress.setVisible(True)
        self._progress.setValue(int(progress))
        self._dl_status.setText(msg)

    @Slot(object)
    def _on_probe_ready(self, info):
        self._set_busy(False)
        if not info:
            return

        if self._probe_for_info_tab:
            self._fill_info_tab(info)
            return

        lines = [
            f"标题: {getattr(info, 'title', '')}",
            f"时长: {getattr(info, 'duration_sec', 0):.1f}s",
            f"上传者: {getattr(info, 'uploader', '') or '—'}",
            f"页面: {getattr(info, 'webpage_url', '')}",
        ]
        hint = getattr(info, "preview_hint", "") or ""
        if hint:
            lines.append(hint)
        self._info.setPlainText("\n".join(lines))
        self._dl_status.setText("探测完成，可开始下载")

    def _fill_info_tab(self, info):
        self._page_url = getattr(info, "webpage_url", "") or getattr(info, "url", "") or ""
        pl = getattr(info, "playlist_title", "") or ""
        title = getattr(info, "title", "") or "—"
        if pl and pl != title:
            self._name_label.setText(f"名称：{pl}  /  {title}")
        else:
            self._name_label.setText(f"名称：{title}")

        meta_parts = [
            f"时长 {getattr(info, 'duration_sec', 0):.1f}s",
            f"上传者 {getattr(info, 'uploader', '') or '—'}",
        ]
        items = getattr(info, "items", None) or []
        kinds = {getattr(it, "kind", "") for it in items}
        if "entry" in kinds:
            meta_parts.append(f"条目 {len(items)} 个")
        elif "format" in kinds:
            meta_parts.append(f"格式 {len(items)} 种")
        self._meta_label.setText(" · ".join(meta_parts))

        hint = getattr(info, "preview_hint", "") or ""
        self._hint_label.setText(hint)

        self._list.clear()
        if not items:
            empty = QListWidgetItem("（无列表项，站点可能限制了格式信息）")
            empty.setFlags(Qt.NoItemFlags)
            self._list.addItem(empty)
        else:
            for it in items:
                # 补 page_url
                if not getattr(it, "page_url", ""):
                    it.page_url = self._page_url
                name = getattr(it, "name", "")
                detail = getattr(it, "detail", "")
                kind = getattr(it, "kind", "")
                prefix = "♪ " if kind == "entry" else "▸ "
                text = f"{prefix}{name}"
                if detail and detail not in name:
                    text += f"    ({detail})"
                row = QListWidgetItem(text)
                row.setData(_ROLE_ITEM, it)
                self._list.addItem(row)

        self._info_status.setText(
            f"已获取 · {self._list.count()} 条 · 双击或点「播放选中」试听"
        )

    @Slot(str)
    def _on_finished(self, path: str):
        was_preview = self._awaiting_preview
        self._awaiting_preview = False
        self._set_busy(False)
        if was_preview:
            self._info_status.setText(f"正在播放预览…")
            self.previewPlayRequested.emit(path)
            return
        self._progress.setValue(100)
        self._dl_status.setText(f"已保存: {path}")
        QMessageBox.information(
            self, "下载完成",
            f"文件已保存：\n{path}\n\n可在首页播放器中打开。",
        )

    @Slot(str)
    def _on_error(self, msg: str):
        if not self._busy and not self._awaiting_preview:
            return
        self._awaiting_preview = False
        self._set_busy(False)
        self._progress.setVisible(False)
        self._info_status.setText("")
        QMessageBox.warning(self, "错误", msg)
