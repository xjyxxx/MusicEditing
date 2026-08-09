"""Studio 页共用：Hero + Card + 全宽滚动壳（对齐个人中心节奏）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme import (
    ACCENT,
    ACCENT_HOVER,
    ACCENT_ON,
    BG,
    BORDER,
    BORDER_STRONG,
    ELEVATED,
    FONT_UI,
    SIGNAL,
    SURFACE,
    SURFACE_2,
    TEXT,
    TEXT_MUTED,
)


def studio_page_stylesheet(page_object: str = "StudioPage") -> str:
    """页面级 QSS：背景 + Hero/Card/按钮。"""
    return f"""
QWidget#{page_object} {{
    background: {BG};
}}
QScrollArea#StudioScroll {{
    background: {BG};
    border: none;
}}
QWidget#StudioBody {{
    background: {BG};
}}
QFrame#StudioHero {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {SURFACE}, stop:0.55 {SURFACE_2}, stop:1 #1A2420);
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#StudioTitle {{
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 18px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QLabel#StudioSubtitle {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#StudioPill {{
    background: {ELEVATED};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 12px;
}}
QFrame#StudioCard {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#StudioCardTitle {{
    color: {SIGNAL};
    font-family: {FONT_UI};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#StudioCardHint {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QPushButton#StudioPrimary {{
    background: {ACCENT};
    color: {ACCENT_ON};
    border: 1px solid {ACCENT};
    border-radius: 10px;
    padding: 9px 14px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#StudioPrimary:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton#StudioPrimary:disabled {{
    background: #4A3F32;
    color: #9A8A78;
    border-color: #4A3F32;
}}
QPushButton#StudioGhost {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 10px;
    padding: 8px 12px;
    font-size: 13px;
}}
QPushButton#StudioGhost:hover {{
    background: #2C3444;
    border-color: #4A5870;
}}
"""


def wrap_studio_scroll(page: QWidget) -> tuple[QVBoxLayout, QWidget, QVBoxLayout]:
    """
    把 page 变成：外层铺满 → Scroll → Body。
    返回 (outer_layout, body, body_layout)。
    """
    page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)

    scroll = QScrollArea()
    scroll.setObjectName("StudioScroll")
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    outer.addWidget(scroll)

    body = QWidget()
    body.setObjectName("StudioBody")
    body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
    scroll.setWidget(body)

    root = QVBoxLayout(body)
    root.setContentsMargins(12, 10, 12, 12)
    root.setSpacing(10)
    return outer, body, root


def make_studio_hero(title: str, subtitle: str = "", pill: str = "") -> QFrame:
    hero = QFrame()
    hero.setObjectName("StudioHero")
    hero.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    lay = QVBoxLayout(hero)
    lay.setContentsMargins(16, 14, 16, 14)
    lay.setSpacing(6)
    row = QHBoxLayout()
    row.setSpacing(10)
    t = QLabel(title)
    t.setObjectName("StudioTitle")
    row.addWidget(t, 0)
    if pill:
        p = QLabel(pill)
        p.setObjectName("StudioPill")
        row.addWidget(p, 0)
    row.addStretch(1)
    lay.addLayout(row)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("StudioSubtitle")
        s.setWordWrap(True)
        lay.addWidget(s)
    return hero


def make_studio_card(title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("StudioCard")
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(10)
    head = QVBoxLayout()
    head.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("StudioCardTitle")
    head.addWidget(t)
    if hint:
        h = QLabel(hint)
        h.setObjectName("StudioCardHint")
        h.setWordWrap(True)
        head.addWidget(h)
    lay.addLayout(head)
    return card, lay


def studio_btn(text: str, *, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("StudioPrimary" if primary else "StudioGhost")
    b.setMinimumHeight(max(32, b.fontMetrics().height() + 16))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
    return b
