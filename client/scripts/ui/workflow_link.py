"""三大核心功能（切片 / 超分 / 去水印）之间的 Tab 索引与接力弹窗。"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtWidgets import QMessageBox, QWidget

# 与 MainWindow 标签页顺序一致
TAB_HOME = 0
TAB_SLICE = 1
TAB_ENHANCE = 2
TAB_WATERMARK = 3
TAB_HOT_COMMENTS = 4
TAB_DOWNLOAD = 5
TAB_PIPELINE = 6
TAB_PROFILE = 7


def ask_video_handoff(
    parent: QWidget,
    title: str,
    message: str,
    choices: List[Tuple[str, int]],
) -> Optional[int]:
    """
    完成后询问是否送去其它功能。
    choices: (按钮文案, tab_index)；另自动加「关闭」。
    返回选中的 tab_index，关闭则 None。
    """
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(title)
    box.setText(message)
    mapping = {}
    for label, tab in choices:
        btn = box.addButton(label, QMessageBox.AcceptRole)
        mapping[btn] = tab
    close_btn = box.addButton("关闭", QMessageBox.RejectRole)
    box.setDefaultButton(close_btn)
    box.exec()
    clicked = box.clickedButton()
    return mapping.get(clicked)
