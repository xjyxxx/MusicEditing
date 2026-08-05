"""功能页索引、菜单分组与页面间接力弹窗。

页面以 QStackedWidget 承载，索引常量保持稳定，供菜单与 open_with_video 共用。
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtWidgets import QMessageBox, QWidget

# 与 MainWindow 堆叠页顺序一致（勿随意改号，接力 / 菜单依赖）
TAB_HOME = 0
TAB_SLICE = 1
TAB_ENHANCE = 2
TAB_WATERMARK = 3
TAB_DOWNLOAD = 4
TAB_HOT_COMMENTS = 4  # 与下载同页（内嵌「热评弹幕」子 Tab）
TAB_PIPELINE = 5
TAB_COVER = 6
TAB_AUDIO_FUN = 7
TAB_BGM = 8
TAB_PROFILE = 9

PAGE_TITLES: dict[int, str] = {
    TAB_HOME: "首页",
    TAB_SLICE: "智能切片",
    TAB_ENHANCE: "画质增强",
    TAB_WATERMARK: "去水印",
    TAB_DOWNLOAD: "下载与热评",
    TAB_PIPELINE: "全流程队列",
    TAB_COVER: "封面工厂",
    TAB_AUDIO_FUN: "音频趣味",
    TAB_BGM: "BGM 混音",
    TAB_PROFILE: "个人中心",
}

# 菜单：(菜单标题, [(动作文案, page_index), ...])
# 趣味「热评弹幕」与工作流「下载与热评」同页；MainWindow 对前者会 focus_hot_tab。
MENU_GROUPS: Sequence[Tuple[str, Sequence[Tuple[str, int]]]] = (
    (
        "核心",
        (
            ("首页预览", TAB_HOME),
            ("智能切片", TAB_SLICE),
            ("画质增强", TAB_ENHANCE),
            ("去水印", TAB_WATERMARK),
        ),
    ),
    (
        "工作流",
        (
            ("全流程队列", TAB_PIPELINE),
            ("下载与热评", TAB_DOWNLOAD),
            ("BGM 混音", TAB_BGM),
        ),
    ),
    (
        "趣味",
        (
            ("热评弹幕", TAB_HOT_COMMENTS),
            ("封面工厂", TAB_COVER),
            ("音频趣味", TAB_AUDIO_FUN),
        ),
    ),
    (
        "帮助",
        (
            ("个人中心", TAB_PROFILE),
        ),
    ),
)


def ask_video_handoff(
    parent: QWidget,
    title: str,
    message: str,
    choices: List[Tuple[str, int]],
) -> Optional[int]:
    """
    完成后询问是否送去其它功能。
    choices: (按钮文案, page_index)；另自动加「关闭」。
    返回选中的 page_index，关闭则 None。
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
