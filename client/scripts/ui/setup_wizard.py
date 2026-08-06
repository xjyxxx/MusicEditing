"""首次启动依赖向导。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.app_logic import update_app_config_value
from core.setup_status import DepItem, SetupStatus, collect_setup_status


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


class SetupWizardDialog(QDialog):
    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self._vm = vm
        self.setWindowTitle("开箱设置 · MusicEditing")
        self.setMinimumSize(560, 480)
        self.resize(620, 520)

        root = QVBoxLayout(self)
        title = QLabel("欢迎使用 MusicEditing")
        title.setObjectName("HomeTitle")
        root.addWidget(title)
        tip = QLabel(
            "本地离线主链路不强制联网。下列依赖按需准备："
            "超分/去水印模型、链接下载、Cookie、GPU。"
            "可稍后在「个人中心」再次打开本向导。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("MutedText")
        root.addWidget(tip)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setSpacing(8)
        scroll.setWidget(self._body)
        root.addWidget(scroll, 1)

        self._rows: dict[str, QLabel] = {}
        self._refresh()

        btns = QHBoxLayout()
        btn_refresh = QPushButton("重新检测")
        btn_refresh.clicked.connect(self._refresh)
        btns.addWidget(btn_refresh)
        btns.addStretch()
        box = QDialogButtonBox(QDialogButtonBox.Ok)
        box.button(QDialogButtonBox.Ok).setText("完成并进入")
        box.accepted.connect(self._on_done)
        btns.addWidget(box)
        root.addLayout(btns)

    def _clear_body(self):
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows.clear()

    @Slot()
    def _refresh(self):
        self._clear_body()
        app = getattr(self._vm, "_app", None) or getattr(self._vm, "app", None)
        st = collect_setup_status(app)
        for item in st.items:
            self._body_lay.addWidget(self._make_row(item))
        self._body_lay.addStretch()

    def _make_row(self, item: DepItem) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 6, 8, 6)
        mark = "✓" if item.ok else "!"
        title = QLabel(f"{mark}  {item.title}")
        title.setObjectName("InfoText" if item.ok else "WarnText")
        title.setMinimumWidth(160)
        detail = QLabel(item.detail)
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)
        self._rows[item.key] = detail
        lay.addWidget(title)
        lay.addWidget(detail, 1)
        if not item.ok or item.action.startswith("special:"):
            btn = QPushButton(self._action_label(item))
            btn.setObjectName("GhostBtn")
            btn.clicked.connect(lambda _=False, it=item: self._on_action(it))
            lay.addWidget(btn)
        return row

    def _action_label(self, item: DepItem) -> str:
        if item.action == "special:cookie":
            return "去配置 Cookie"
        if item.action == "special:gpu":
            return "个人中心"
        if item.action.endswith(".bat"):
            return "一键下载"
        return "处理"

    @Slot()
    def _on_action(self, item: DepItem):
        if item.action == "special:cookie":
            QMessageBox.information(
                self, "Cookie",
                "请到「链接下载」页点击「Cookie…」，选择扩展导出的 Netscape cookies.txt。\n"
                "抖音需先登录 douyin.com 再导出。",
            )
            parent = self.parent()
            if parent and hasattr(parent, "navigate_to"):
                parent.navigate_to("download")
            self.accept()
            return
        if item.action == "special:gpu":
            parent = self.parent()
            if parent and hasattr(parent, "navigate_to"):
                parent.navigate_to("profile")
            self.accept()
            return
        if item.action.endswith(".bat"):
            bat = _project_root() / item.action.replace("/", os.sep)
            if not bat.is_file():
                QMessageBox.warning(self, "脚本缺失", f"未找到：\n{bat}")
                return
            try:
                subprocess.Popen(
                    ["cmd", "/c", str(bat)],
                    cwd=str(_project_root()),
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
                QMessageBox.information(
                    self, "已启动",
                    f"已在新窗口运行：\n{bat.name}\n完成后点「重新检测」。",
                )
            except OSError as e:
                QMessageBox.warning(self, "启动失败", str(e))

    @Slot()
    def _on_done(self):
        update_app_config_value("setup_wizard_done", "true")
        self.accept()
