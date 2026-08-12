"""将 third_party/iphoto/src 注入 sys.path，并补齐运行 iPhoto 所需的兼容层。

上游 iPhotron 声明 Python>=3.12；本仓常用 3.10。此处仅做最小兼容（StrEnum 等），
不改动 vendor 内业务逻辑。播放器链路不在此模块处理。
"""

from __future__ import annotations

import enum
import sys
from pathlib import Path

_BOOTSTRAPPED = False
_QT_FILTER_INSTALLED = False


def vendor_src_root() -> Path:
    """返回 vendored iPhoto 的 ``src`` 目录（含 ``iPhoto`` / ``maps`` 包）。"""
    # client/scripts/core -> repo root
    repo = Path(__file__).resolve().parents[3]
    return repo / "third_party" / "iphoto" / "src"


def ensure_iphoto_compat() -> None:
    """安装 3.10 上缺失的标准库符号。"""
    if not hasattr(enum, "StrEnum"):

        class StrEnum(str, enum.Enum):
            """``enum.StrEnum`` 的最小 backport（Py3.11+）。"""

            def __str__(self) -> str:
                return str(self.value)

        enum.StrEnum = StrEnum  # type: ignore[attr-defined, assignment]


def ensure_iphoto_on_path() -> Path:
    """确保可 ``import iPhoto`` / ``import maps``，返回 src 根路径。"""
    global _BOOTSTRAPPED
    ensure_iphoto_compat()
    src = vendor_src_root()
    src_s = str(src)
    if src.is_dir() and src_s not in sys.path:
        sys.path.insert(0, src_s)
    _BOOTSTRAPPED = True
    return src


def iphoto_capability_hints() -> list[str]:
    """返回可选依赖 / 地图资源缺失时的白话提示（空列表表示齐全）。"""
    hints: list[str] = []
    try:
        import pillow_heif  # noqa: F401
    except ImportError:
        hints.append(
            "未装 pillow-heif：HEIC 可能无法预览（pip install -r client/scripts/requirements-iphoto.txt）"
        )
    font_dir = vendor_src_root() / "maps" / "font"
    font_ok = False
    if font_dir.is_dir():
        try:
            font_ok = any(font_dir.iterdir())
        except OSError:
            font_ok = False
    if not font_ok:
        hints.append(
            "未补齐 maps/font：地点地图地名可能异常（见 third_party/iphoto/src/maps/ASSETS.md）"
        )
    return hints


def install_hosted_qt_message_filter() -> None:
    """宿主嵌入时压制 maps 缺字体 / 叠层 QPainter 噪音，避免控制台像崩溃。"""
    global _QT_FILTER_INSTALLED
    if _QT_FILTER_INSTALLED:
        return
        try:
            from PySide6.QtCore import qInstallMessageHandler
        except Exception:  # noqa: BLE001
            return

        suppress_substrings = (
        "QFont::setPointSizeF: Point size <= 0",
        "QPainter::begin: A paint device can only be painted by one painter",
        "QPainter::translate: Painter not active",
        "QPainter::worldTransform: Painter not active",
        "QPainter::setWorldTransform: Painter not active",
        "QWidgetEffectSourcePrivate::pixmap: Painter not active",
    )

    def _handler(mode, context, message):  # noqa: ANN001
        text = str(message or "")
        if any(s in text for s in suppress_substrings):
            return
        # 保留其它 Qt 消息到 stderr，避免完全静音
        try:
            sys.stderr.write(f"{text}\n")
        except Exception:  # noqa: BLE001
            pass

    try:
        qInstallMessageHandler(_handler)
        _QT_FILTER_INSTALLED = True
    except Exception:  # noqa: BLE001
        pass


def try_import_iphoto():
    """尝试导入 iPhoto GUI 入口类型；失败返回 (None, 错误信息)。"""
    try:
        ensure_iphoto_on_path()
        from iPhoto.gui.ui.main_window import MainWindow  # noqa: WPS433
        from iPhoto.bootstrap.runtime_context import RuntimeContext  # noqa: WPS433
        from iPhoto.settings.manager import SettingsManager  # noqa: WPS433

        return {
            "MainWindow": MainWindow,
            "RuntimeContext": RuntimeContext,
            "SettingsManager": SettingsManager,
        }, None
    except Exception as exc:  # noqa: BLE001 — 宿主页需要展示可读错误
        return None, f"{type(exc).__name__}: {exc}"
