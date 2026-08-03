"""全局视觉主题（Studio 炭黑 + 琥珀强调，借鉴 Splice / Cinema Studio 一类媒体工具）"""

from __future__ import annotations

# ── 设计令牌 ──────────────────────────────────────────────
BG = "#0E1116"          # 画布底
SURFACE = "#161B22"     # 面板
SURFACE_2 = "#1C2330"   # 抬升面
ELEVATED = "#242B38"    # 控件底
BORDER = "#2A3344"      # 发丝边
BORDER_STRONG = "#3A465C"
TEXT = "#E8EDF5"
TEXT_MUTED = "#8B95A8"
TEXT_DIM = "#5C677A"
ACCENT = "#E8A45C"      # 主强调（CTA）
ACCENT_HOVER = "#F0B874"
ACCENT_PRESSED = "#D49048"
ACCENT_ON = "#12151C"   # 强调色上的字
SIGNAL = "#3DB8A8"      # 次要信号（链接/信息）
SIGNAL_SOFT = "#2A4A48"
DANGER = "#E07070"
OK = "#6BCB8A"
PLAYER_BG = "#080A0E"

FONT_UI = '"Segoe UI Semibold", "Microsoft YaHei UI", "Segoe UI", sans-serif'
FONT_BODY = '"Microsoft YaHei UI", "Segoe UI", sans-serif'


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
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {SURFACE_2};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_ON};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {SIGNAL};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_ON};
    outline: 0;
}}

/* ── Group / lists / progress ── */
QGroupBox {{
    background: {SURFACE_2};
    border: 1px solid {BORDER};
    border-radius: 12px;
    margin-top: 14px;
    padding: 14px 12px 12px 12px;
    font-family: {FONT_UI};
    font-weight: 600;
    color: {TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: {SIGNAL};
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
    top: -1px;
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
    color: #B8EDE4; font-size: 13px; font-weight: 600; padding: 6px 10px;
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
QPushButton#PresetBtn {{
    background: {SURFACE_2}; color: {TEXT_MUTED}; padding: 4px 10px;
    border-radius: 6px; border: 1px solid {BORDER};
}}
QPushButton#PresetBtn:hover {{ background: {ELEVATED}; color: {TEXT}; border-color: {ACCENT}; }}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 12px;
    margin-top: 10px; padding-top: 12px; font-weight: 600; color: {TEXT};
    background: {SURFACE_2};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {SIGNAL}; }}
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
