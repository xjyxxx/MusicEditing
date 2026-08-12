"""将 third_party/iphoto/src 注入 sys.path，并补齐运行 iPhoto 所需的兼容层。

上游 iPhotron 声明 Python>=3.12；本仓常用 3.10。此处仅做最小兼容（StrEnum 等），
不改动 vendor 内业务逻辑。播放器链路不在此模块处理。
"""

from __future__ import annotations

import enum
import sys
from pathlib import Path

_BOOTSTRAPPED = False


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
