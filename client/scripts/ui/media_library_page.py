"""本地素材库页面。"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QWidget,
)

from core.media_library import default_library_roots, iter_media_files
from ui.studio_kit import (
    make_studio_card,
    make_studio_hero,
    studio_btn,
    studio_page_stylesheet,
    wrap_studio_scroll,
)
from ui.workflow_link import TAB_HOME, TAB_PIPELINE, TAB_SLICE


class MediaLibraryPage(QWidget):
    def __init__(self, vm, handoff=None, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._handoff = handoff
        self._root = ""
        self.setObjectName("MediaLibraryPage")
        self.setStyleSheet(studio_page_stylesheet("MediaLibraryPage"))
        _, _, root = wrap_studio_scroll(self)

        root.addWidget(make_studio_hero(
            "本地素材库",
            "索引默认输出目录与自选根目录（不上传云端）。可送首页预览、智能切片或全流程队列。",
            "工作流",
        ))

        root_card, root_lay = make_studio_card("根目录", "选择要浏览的本地文件夹")
        row = QHBoxLayout()
        self._root_label = QLabel("未选择目录")
        self._root_label.setObjectName("StudioCardHint")
        btn_pick = studio_btn("选择目录…")
        btn_pick.clicked.connect(self._on_pick)
        btn_refresh = studio_btn("刷新")
        btn_refresh.clicked.connect(self.refresh)
        row.addWidget(self._root_label, 1)
        row.addWidget(btn_pick)
        row.addWidget(btn_refresh)
        root_lay.addLayout(row)
        root.addWidget(root_card)

        list_card, list_lay = make_studio_card("文件", "点选后用下方按钮送到其它功能页")
        self._list = QListWidget()
        list_lay.addWidget(self._list)
        actions = QHBoxLayout()
        self._btn_home = studio_btn("送首页", primary=True)
        self._btn_slice = studio_btn("送切片")
        self._btn_pipe = studio_btn("送队列")
        for b in (self._btn_home, self._btn_slice, self._btn_pipe):
            actions.addWidget(b)
        actions.addStretch()
        list_lay.addLayout(actions)
        root.addWidget(list_card, 1)

        self._btn_home.clicked.connect(lambda: self._send(TAB_HOME))
        self._btn_slice.clicked.connect(lambda: self._send(TAB_SLICE))
        self._btn_pipe.clicked.connect(lambda: self._send(TAB_PIPELINE))

        self._bootstrap()

    def _bootstrap(self):
        out = getattr(self._vm, "output_dir", "") or ""
        roots = default_library_roots(out)
        if roots:
            self._root = roots[0]
            self.refresh()
        else:
            self._root_label.setText("请选择素材根目录")

    @Slot()
    def _on_pick(self):
        start = self._root or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择素材库根目录", start)
        if not path:
            return
        self._root = path
        self.refresh()

    @Slot()
    def refresh(self):
        self._list.clear()
        if not self._root:
            return
        self._root_label.setText(self._root)
        items = iter_media_files(self._root, recursive=True, limit=400)
        for m in items:
            mb = m.size_bytes / (1024 * 1024)
            text = f"[{m.kind}] {m.name}  ·  {mb:.1f} MB"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, m.path)
            self._list.addItem(it)
        if not items:
            self._list.addItem(QListWidgetItem("（目录内暂无视频/图片）"))

    def _current_path(self) -> str:
        it = self._list.currentItem()
        if not it:
            return ""
        path = it.data(Qt.ItemDataRole.UserRole) or ""
        return str(path) if path else ""

    def _send(self, tab: int):
        path = self._current_path()
        if not path or not os.path.isfile(path):
            QMessageBox.information(self, "素材库", "请先选择一个媒体文件")
            return
        win = self.window()
        if tab == TAB_PIPELINE and hasattr(win, "_pipeline_page"):
            if hasattr(win, "navigate_to"):
                win.navigate_to("pipeline")
            win._pipeline_page.enqueue_paths([path])  # noqa: SLF001
            return
        if tab == TAB_HOME and hasattr(win, "_on_preview_play"):
            win._on_preview_play(path)  # noqa: SLF001
            return
        if self._handoff:
            self._handoff(path, tab)
        else:
            self._vm.import_video(path)
