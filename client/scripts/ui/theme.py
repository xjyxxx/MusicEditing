"""全局视觉主题（Studio 炭黑 + 琥珀强调，借鉴 Splice / Cinema Studio 一类媒体工具）"""

from __future__ import annotations

# ── 设计令牌 ──────────────────────────────────────────────
# macOS 风格：暖白画布、半透明浅灰面板和系统蓝强调色。
BG = "#F5F5F7"          # 画布底
SURFACE = "#FFFFFF"     # 面板
SURFACE_2 = "#F2F2F7"   # 抬升面
ELEVATED = "#E8E8ED"    # 控件底
BORDER = "#D2D2D7"      # 发丝边
BORDER_STRONG = "#C7C7CC"
TEXT = "#1D1D1F"
TEXT_MUTED = "#6E6E73"
TEXT_DIM = "#8E8E93"
ACCENT = "#0A84FF"      # macOS 系统蓝
ACCENT_HOVER = "#0077ED"
ACCENT_PRESSED = "#006EDC"
ACCENT_ON = "#FFFFFF"   # 强调色上的字
SIGNAL = "#007AFF"      # 次要信号（链接/信息）
SIGNAL_SOFT = "#E5F1FF"
DANGER = "#D70015"
OK = "#248A3D"
PLAYER_BG = "#000000"

FONT_UI = '"SF Pro Display", "Segoe UI Variable", "Microsoft YaHei UI", "Segoe UI", sans-serif'
FONT_BODY = '"SF Pro Text", "Segoe UI", "Microsoft YaHei UI", sans-serif'


def app_stylesheet() -> str:
    """主窗口及应用级 QSS。"""
    return f"""
* {{
    font-family: {FONT_BODY};
}}
QMainWindow, QDialog {{
    background: {BG};
    color: {TEXT};
}}
QMainWindow > QWidget {{
    background: {BG};
}}
QWidget {{
    color: {TEXT};
    font-size: 13px;
}}
QToolTip {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    padding: 6px 10px;
    border-radius: 6px;
}}

/* ── 顶栏状态条 ── */
QFrame#TopChrome {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#ChromeBrand {{
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.5px;
    padding: 2px 4px;
}}
QLabel#ChromePill {{
    background: {ELEVATED};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 12px;
}}
QLabel#ChromeWeather {{
    background: {SIGNAL_SOFT};
    color: #B8EDE4;
    border: 1px solid #3A6A64;
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 12px;
}}
QLabel#ChromeVersion {{
    color: {TEXT_DIM};
    font-size: 12px;
    padding: 0 4px;
}}
QLabel#FooterStatus {{
    color: {TEXT_MUTED};
    font-size: 12px;
    padding: 6px 4px 2px 4px;
    background: transparent;
}}

/* ── 菜单栏（主功能导航）── */
QMenuBar {{
    background: {BG};
    color: {TEXT};
    border: none;
    padding: 2px 6px 0 6px;
    font-family: {FONT_UI};
    font-size: 13px;
}}
QMenuBar::item {{
    background: transparent;
    color: {TEXT_MUTED};
    padding: 6px 12px;
    border-radius: 6px;
    margin: 2px 2px;
}}
QMenuBar::item:selected {{
    background: {SURFACE_2};
    color: {TEXT};
}}
QMenuBar::item:pressed {{
    background: {ELEVATED};
    color: {ACCENT};
}}
QMenu {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 8px 28px 8px 16px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {ELEVATED};
    color: {TEXT};
}}
QMenu::item:checked {{
    color: {ACCENT};
    font-weight: 600;
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}
QLabel#ChromePage {{
    background: {ACCENT};
    color: {ACCENT_ON};
    border: 1px solid {ACCENT};
    border-radius: 999px;
    padding: 4px 12px;
    font-size: 12px;
    font-weight: 600;
}}
QStackedWidget#MainStack {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

/* ── 页内 Tabs（增强/去水印等）── */
QTabWidget::pane {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    top: -1px;
    padding: 8px;
}}
QTabWidget::tab-bar {{
    left: 8px;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_MUTED};
    padding: 10px 18px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-top-left-radius: 10px;
    border-top-right-radius: 10px;
    font-family: {FONT_UI};
    font-size: 13px;
}}
QTabBar::tab:hover {{
    color: {TEXT};
    background: {SURFACE_2};
}}
QTabBar::tab:selected {{
    color: {ACCENT_ON};
    background: {ACCENT};
    border: 1px solid {ACCENT};
    font-weight: 600;
}}

/* ── Buttons ── */
QPushButton {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 7px 14px;
    font-size: 13px;
}}
QPushButton:hover {{
    background: #2C3444;
    border-color: #4A5870;
}}
QPushButton:pressed {{
    background: #222833;
}}
QPushButton:disabled {{
    color: {TEXT_DIM};
    background: {SURFACE_2};
    border-color: {BORDER};
}}
QPushButton#primaryButton, QPushButton[cssClass="primary"] {{
    background: {ACCENT};
    color: {ACCENT_ON};
    border: 1px solid {ACCENT};
    font-weight: 600;
    padding: 8px 18px;
}}
QPushButton#primaryButton:hover, QPushButton[cssClass="primary"]:hover {{
    background: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
}}
QPushButton#primaryButton:pressed, QPushButton[cssClass="primary"]:pressed {{
    background: {ACCENT_PRESSED};
}}
QPushButton#primaryButton:disabled, QPushButton[cssClass="primary"]:disabled {{
    background: #4A3F32;
    color: #9A8A78;
    border-color: #4A3F32;
}}

/* ── Inputs ── */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_ON};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {SIGNAL};
}}

/* Combo：深色弹出列表，避免系统白边 */
QComboBox {{
    background: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 28px 6px 10px;
    min-height: 28px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_ON};
    /* 强制非原生弹出层，QSS 才吃得住 */
    combobox-popup: 0;
}}
QComboBox:hover {{
    border-color: {BORDER_STRONG};
    background: {ELEVATED};
}}
QComboBox:focus {{
    border: 1px solid {SIGNAL};
}}
QComboBox:disabled {{
    color: {TEXT_DIM};
    background: {SURFACE};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 26px;
    border: none;
    border-left: 1px solid {BORDER};
    background: {ELEVATED};
    border-top-right-radius: 7px;
    border-bottom-right-radius: 7px;
}}
QComboBox::drop-down:hover {{
    background: #2C3444;
}}
QComboBox::down-arrow {{
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {TEXT};
    margin-right: 2px;
}}
QComboBox QAbstractItemView {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 8px;
    padding: 4px;
    outline: 0;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_ON};
}}
QComboBox QAbstractItemView::item {{
    min-height: 30px;
    padding: 6px 12px;
    border-radius: 6px;
    color: {TEXT};
    background: transparent;
}}
QComboBox QAbstractItemView::item:hover {{
    background: {SURFACE_2};
    color: {TEXT};
}}
QComboBox QAbstractItemView::item:selected {{
    background: {ACCENT};
    color: {ACCENT_ON};
}}

/* Spin：加宽上下按钮，箭头用实心三角，避免暗色里看不见 */
QSpinBox, QDoubleSpinBox {{
    background: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px 36px 4px 10px;
    min-height: 28px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_ON};
}}
QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {SIGNAL};
}}
QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {BORDER_STRONG};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 28px;
    height: 16px;
    background: {ELEVATED};
    border-left: 1px solid {BORDER_STRONG};
    border-bottom: 1px solid {BORDER};
    border-top-right-radius: 7px;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 28px;
    height: 16px;
    background: {ELEVATED};
    border-left: 1px solid {BORDER_STRONG};
    border-bottom-right-radius: 7px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {ACCENT};
}}
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed {{
    background: {ACCENT_PRESSED};
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-bottom: 7px solid {ACCENT};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 7px solid {ACCENT};
}}
QSpinBox::up-arrow:on, QDoubleSpinBox::up-arrow:on {{
    border-bottom-color: {ACCENT_ON};
}}
QSpinBox::down-arrow:on, QDoubleSpinBox::down-arrow:on {{
    border-top-color: {ACCENT_ON};
}}

/* ── Group / lists / progress ── */
QGroupBox {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 12px;
    /* 标题画在 margin 带；加大上下留白，避免标题压住组内第一行控件 */
    margin-top: 20px;
    padding: 22px 12px 12px 12px;
    font-family: {FONT_UI};
    font-weight: 600;
    color: {TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    top: 2px;
    padding: 2px 8px;
    color: {SIGNAL};
    background: {SURFACE_2};
}}
QListWidget, QTreeWidget, QTableWidget {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 10px;
    outline: 0;
    padding: 4px;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
}}
QListWidget::item:selected {{
    background: {ACCENT};
    color: {ACCENT_ON};
}}
QListWidget::item:hover:!selected {{
    background: {ELEVATED};
}}
QProgressBar {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    text-align: center;
    color: {TEXT_MUTED};
    min-height: 16px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 7px;
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: {ELEVATED};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    background: {ACCENT};
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {SIGNAL};
    border-radius: 3px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_STRONG};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QSplitter::handle {{
    background: {BORDER};
}}
QCheckBox, QRadioButton {{
    spacing: 8px;
    color: {TEXT};
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
}}

/* ── 首页 ── */
QLabel#HomeTitle {{
    font-family: {FONT_UI};
    font-size: 26px;
    font-weight: 700;
    color: {TEXT};
    padding: 4px 2px 2px 2px;
}}
QLabel#HomeSubtitle {{
    color: {TEXT_MUTED};
    font-size: 13px;
    padding-bottom: 4px;
}}
QLabel#SectionHint {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QFrame#FeatureCard {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QFrame#FeatureCard:hover {{
    background: {ELEVATED};
    border: 1px solid {ACCENT};
}}
QLabel#FeatureCardTitle {{
    font-family: {FONT_UI};
    font-size: 15px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel#FeatureCardDesc {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#InfoText {{
    color: {SIGNAL};
}}
QLabel#MutedText {{
    color: {TEXT_MUTED};
}}
QLabel#WarnText {{
    color: {ACCENT};
}}
"""


def apply_dark_palette(app) -> None:
    """Fusion + 深色 QPalette，压掉下拉/弹层系统白边。"""
    from PySide6.QtGui import QColor, QPalette

    p = QPalette()
    bg = QColor(BG)
    surface = QColor(SURFACE)
    elevated = QColor(ELEVATED)
    text = QColor(TEXT)
    muted = QColor(TEXT_MUTED)
    accent = QColor(ACCENT)
    accent_on = QColor(ACCENT_ON)
    border = QColor(BORDER_STRONG)

    p.setColor(QPalette.Window, bg)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, QColor(SURFACE_2))
    p.setColor(QPalette.AlternateBase, elevated)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, elevated)
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.BrightText, accent)
    p.setColor(QPalette.Highlight, accent)
    p.setColor(QPalette.HighlightedText, accent_on)
    p.setColor(QPalette.ToolTipBase, elevated)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.PlaceholderText, muted)
    p.setColor(QPalette.Link, QColor(SIGNAL))
    p.setColor(QPalette.Light, border)
    p.setColor(QPalette.Mid, QColor(BORDER))
    p.setColor(QPalette.Dark, surface)
    p.setColor(QPalette.Shadow, QColor(PLAYER_BG))
    app.setPalette(p)


def style_spinbox(spin) -> None:
    """秒数等 Spin：用明显的 + / − 按钮符号，加高一点好点。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractSpinBox

    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
    spin.setMinimumHeight(32)
    spin.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)


def enhance_page_stylesheet() -> str:
    """画质增强页局部样式（对齐全局令牌；压住 ScrollArea 默认白底）。"""
    return f"""
EnhancePage {{
    background: {BG};
    color: {TEXT};
}}
QWidget#EnhanceScrollBody {{
    background: {BG};
    color: {TEXT};
}}
QScrollArea#EnhanceScroll {{
    background: {BG};
    border: none;
}}
QScrollArea#EnhanceScroll > QWidget > QWidget {{
    background: {BG};
}}
QTabWidget#EnhanceInnerTabs::pane {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    top: 0px;
    padding: 8px;
}}
QTabWidget#EnhanceInnerTabs QTabBar::tab {{
    background: {SURFACE_2};
    color: {TEXT_MUTED};
    padding: 8px 16px;
    margin-right: 4px;
    border: 1px solid {BORDER};
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}}
QTabWidget#EnhanceInnerTabs QTabBar::tab:hover {{
    color: {TEXT};
    background: {ELEVATED};
}}
QTabWidget#EnhanceInnerTabs QTabBar::tab:selected {{
    background: {ACCENT};
    color: {ACCENT_ON};
    border-color: {ACCENT};
    font-weight: 600;
}}
QLabel#HintLabel {{
    color: {TEXT_MUTED}; font-size: 12px; padding: 8px 10px;
    background: {SURFACE_2}; border: 1px solid {BORDER}; border-radius: 8px;
}}
QLabel#MetaBadge {{
    color: #B8EDE4; font-size: 13px; font-weight: 600;
    padding: 6px 12px; min-height: 28px;
    background: {SIGNAL_SOFT}; border: 1px solid #3A6A64; border-radius: 8px;
}}
QLabel#SideTitle {{
    color: {TEXT}; font-size: 13px; font-weight: 700; padding: 4px 0;
}}
QLabel#PathLabel {{
    color: {TEXT_MUTED};
}}
QPushButton#PrimaryBtn {{
    background: {ACCENT}; color: {ACCENT_ON}; padding: 10px 20px;
    border-radius: 8px; font-weight: 600; border: 1px solid {ACCENT};
}}
QPushButton#PrimaryBtn:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#PrimaryBtn:disabled {{ background: #4A3F32; color: #9A8A78; border-color: #4A3F32; }}
QPushButton#GhostBtn {{
    background: {ELEVATED}; color: {TEXT}; padding: 8px 14px;
    border-radius: 8px; border: 1px solid {BORDER_STRONG};
}}
QPushButton#GhostBtn:hover {{ background: #2C3444; }}
QPushButton#GhostBtn:disabled {{ color: {TEXT_DIM}; border-color: {BORDER}; }}
QLineEdit#ProfileKeyEdit {{
    min-height: 34px;
    padding: 8px 12px;
    font-size: 13px;
}}
QPushButton#PresetBtn {{
    background: {SURFACE_2}; color: {TEXT_MUTED}; padding: 4px 10px;
    border-radius: 6px; border: 1px solid {BORDER};
}}
QPushButton#PresetBtn:hover {{ background: {ELEVATED}; color: {TEXT}; border-color: {ACCENT}; }}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 12px;
    margin-top: 20px; padding: 22px 12px 12px 12px; font-weight: 600; color: {TEXT};
    background: {SURFACE_2};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 2px 6px;
    color: {SIGNAL};
    background: {SURFACE_2};
}}
QProgressBar {{
    border: 1px solid {BORDER}; border-radius: 8px; text-align: center;
    min-height: 18px; background: {SURFACE_2}; color: {TEXT_MUTED};
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 7px; }}
QFrame#CompareBox {{
    background: {PLAYER_BG};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#CenterLine {{
    background: {BORDER_STRONG};
    max-width: 1px; min-width: 1px; border: none;
}}
QGraphicsView {{
    background: {PLAYER_BG};
    border: none;
    color: {TEXT_MUTED};
}}
QRadioButton {{
    color: {TEXT};
    spacing: 8px;
    background: transparent;
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
    border-radius: 8px;
    border: 2px solid {BORDER_STRONG};
    background: {ELEVATED};
}}
QRadioButton::indicator:hover {{
    border-color: {SIGNAL};
}}
QRadioButton::indicator:checked {{
    border: 2px solid {ACCENT};
    background: {ACCENT};
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: {ELEVATED};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    background: {ACCENT};
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {SIGNAL};
    border-radius: 3px;
}}
"""


def hot_comments_stylesheet() -> str:
    """热评 / 下载三合一页局部样式（夜色歌单 + 琥珀 CTA）。"""
    return f"""
HotCommentsPage, QWidget#HotPage {{
    background: {BG};
    color: {TEXT};
}}
QScrollArea#HotScroll {{
    background: transparent;
    border: none;
}}
QScrollArea#HotScroll > QWidget > QWidget {{
    background: transparent;
}}

QLabel#HotHint {{
    color: {TEXT_MUTED};
    font-size: 12px;
    padding: 8px 12px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {SURFACE_2}, stop:1 #1A1820);
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

QFrame#HotFetchPanel, QFrame#HotResultPanel {{
    background: transparent;
    border: none;
}}

QFrame#HotSongBar {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #1A2230, stop:0.55 {SURFACE}, stop:1 #1C1812);
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#HotSongTitle {{
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 20px;
    font-weight: 700;
    letter-spacing: 0.3px;
}}
QLabel#HotSongMeta {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLabel#HotPathMuted {{
    color: {TEXT_DIM};
    font-size: 11px;
}}

QPushButton#HotChip {{
    background: {SIGNAL_SOFT};
    color: #B8EDE4;
    border: 1px solid #3A6A64;
    border-radius: 999px;
    padding: 6px 16px;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#HotChip:hover {{
    background: #355E5A;
    color: {TEXT};
}}

QFrame#HotFetchRow {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLineEdit#HotUrlEdit {{
    background: {ELEVATED};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 12px;
    color: {TEXT};
    selection-background-color: {ACCENT};
}}
QLineEdit#HotUrlEdit:focus {{
    border: 1px solid {ACCENT};
}}

QPushButton#HotGhostBtn {{
    background: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 12px;
}}
QPushButton#HotGhostBtn:hover {{
    border-color: {ACCENT};
    background: {ELEVATED};
}}
QPushButton#HotGhostBtn:disabled {{
    color: {TEXT_DIM};
    border-color: {BORDER};
}}

QFrame#HotSegment {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QRadioButton#HotSegmentBtn {{
    spacing: 6px;
    padding: 6px 14px;
    color: {TEXT_MUTED};
    background: transparent;
    border-radius: 8px;
}}
QRadioButton#HotSegmentBtn::indicator {{
    width: 0;
    height: 0;
}}
QRadioButton#HotSegmentBtn:checked {{
    color: {ACCENT_ON};
    background: {ACCENT};
    font-weight: 600;
}}
QRadioButton#HotSegmentBtn:hover:!checked {{
    color: {TEXT};
    background: {ELEVATED};
}}

QLabel#HotStatus {{
    color: {SIGNAL};
    font-size: 12px;
    padding: 2px 2px;
}}
QLabel#HotStatus[tone="warn"] {{
    color: {ACCENT};
}}
QLabel#HotStatus[tone="ok"] {{
    color: #8FD4D0;
}}
QLabel#HotStatus[tone="danger"] {{
    color: {DANGER};
}}

QProgressBar#HotProgress {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 6px;
    text-align: center;
    color: {TEXT};
    min-height: 14px;
}}
QProgressBar#HotProgress::chunk {{
    background: {ACCENT};
    border-radius: 5px;
}}

QFrame#HotMediaCard {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#HotKindBadge {{
    background: {SURFACE_2};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 12px;
    font-size: 12px;
    font-weight: 700;
}}
QLabel#HotKindBadge[kind="audio"] {{
    background: {SIGNAL_SOFT};
    color: #B8EDE4;
    border-color: #3A6A64;
}}
QLabel#HotKindBadge[kind="video"] {{
    background: #3A2E1A;
    color: {ACCENT};
    border-color: #6A4E28;
}}
QLabel#HotMediaName {{
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 15px;
    font-weight: 700;
}}
QLabel#HotMediaPath {{
    color: {TEXT_DIM};
    font-size: 11px;
}}

QLabel#HotSectionTitle {{
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 14px;
    font-weight: 700;
}}
QLabel#HotCountBadge {{
    background: {SIGNAL_SOFT};
    color: #B8EDE4;
    border: 1px solid #3A6A64;
    border-radius: 999px;
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
}}

QListWidget#HotCommentList {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 8px;
    outline: none;
}}
QListWidget#HotMediaList {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 4px;
    outline: none;
}}
QListWidget#HotMediaList::item {{
    padding: 6px 8px;
    border-radius: 6px;
}}
QListWidget#HotMediaList::item:selected {{
    background: {ELEVATED};
    color: {TEXT};
}}
QListWidget#HotCommentList::item {{
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 0;
    margin: 2px 0;
}}
QListWidget#HotCommentList::item:hover {{
    background: transparent;
}}
QListWidget#HotCommentList::item:selected {{
    background: transparent;
}}
QFrame#HotCommentRow {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-left: 3px solid {BORDER};
    border-radius: 10px;
}}
QListWidget#HotCommentList::item:selected QFrame#HotCommentRow,
QListWidget#HotCommentList::item:hover QFrame#HotCommentRow {{
    border-left: 3px solid {ACCENT};
    background: {ELEVATED};
}}
QLabel#HotCommentNick {{
    color: {ACCENT};
    font-size: 12px;
    font-weight: 700;
}}
QLabel#HotCommentLike {{
    color: {TEXT_MUTED};
    font-size: 11px;
}}
QLabel#HotCommentBody {{
    color: {TEXT};
    font-size: 13px;
}}

QGroupBox#HotAdvanced {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    margin-top: 12px;
    padding: 14px 10px 10px 10px;
    font-size: 12px;
    color: {TEXT_MUTED};
}}
QGroupBox#HotAdvanced::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 6px;
    color: {SIGNAL};
}}
"""
