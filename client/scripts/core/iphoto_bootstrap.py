"""将 third_party/iphoto/src 注入 sys.path，并补齐运行 iPhoto 所需的兼容层。

上游 iPhotron 声明 Python>=3.12；本仓常用 3.10。此处仅做最小兼容（StrEnum 等），
不改动 vendor 内业务逻辑。播放器链路不在此模块处理。
"""

from __future__ import annotations

import enum
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional

_BOOTSTRAPPED = False
_QT_FILTER_INSTALLED = False
_CACHED_MODS: Optional[dict[str, Any]] = None
_CACHED_ERR: Optional[str] = None
_PREWARM_LOCK = threading.Lock()
_PREWARM_STARTED = False

_log = logging.getLogger(__name__)


def _env_truthy(name: str) -> Optional[bool]:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return None
    if raw in ("1", "true", "on", "yes"):
        return True
    if raw in ("0", "false", "off", "no"):
        return False
    return None


def iphoto_cache_mode_enabled() -> bool:
    """图库缓存模式：首次加载后常驻，离开只休眠，再进秒开。

    优先级：环境变量 MUSIC_IPHOTO_CACHE_MODE > app.conf iphoto_cache_mode > 默认 true。
    """
    env = _env_truthy("MUSIC_IPHOTO_CACHE_MODE")
    if env is not None:
        return env
    try:
        from core.app_logic import load_app_config

        v = (load_app_config().get("iphoto_cache_mode") or "true").strip().lower()
        return v not in ("0", "false", "off", "no")
    except Exception:  # noqa: BLE001
        return True


def iphoto_idle_teardown_sec() -> int:
    """缓存关闭时可空闲卸载；秒。缓存模式开启时强制为 0。"""
    if iphoto_cache_mode_enabled():
        return 0
    raw = (os.environ.get("MUSIC_IPHOTO_IDLE_TEARDOWN_SEC") or "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            pass
    try:
        from core.app_logic import load_app_config

        v = (load_app_config().get("iphoto_idle_teardown_sec") or "0").strip()
        return max(0, int(v or "0"))
    except Exception:  # noqa: BLE001
        return 0


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
    """尝试导入 iPhoto GUI 入口类型；失败返回 (None, 错误信息)。结果会缓存。"""
    global _CACHED_MODS, _CACHED_ERR
    if _CACHED_MODS is not None:
        return _CACHED_MODS, None
    if _CACHED_ERR is not None:
        return None, _CACHED_ERR
    try:
        ensure_iphoto_on_path()
        from iPhoto.gui.ui.main_window import MainWindow  # noqa: WPS433
        from iPhoto.bootstrap.runtime_context import RuntimeContext  # noqa: WPS433
        from iPhoto.settings.manager import SettingsManager  # noqa: WPS433

        mods = {
            "MainWindow": MainWindow,
            "RuntimeContext": RuntimeContext,
            "SettingsManager": SettingsManager,
        }
        _CACHED_MODS = mods
        _CACHED_ERR = None
        return mods, None
    except Exception as exc:  # noqa: BLE001 — 宿主页需要展示可读错误
        err = f"{type(exc).__name__}: {exc}"
        low = err.lower()
        if "jsonschema" in low or "no module named" in low:
            err += (
                "（外发包需含 requirements-iphoto-min；完整 HEIC 等请 --with-iphoto-extras 重打包）"
            )
        _CACHED_ERR = err
        return None, err


def prewarm_iphoto_import(*, background: bool = True) -> None:
    """空闲时预热 import（不建窗）；缩短首次进入图库的等待。"""
    global _PREWARM_STARTED
    with _PREWARM_LOCK:
        if _PREWARM_STARTED or _CACHED_MODS is not None:
            return
        _PREWARM_STARTED = True

    def _run() -> None:
        try:
            mods, err = try_import_iphoto()
            if mods is not None:
                _log.info("iPhoto 模块预热完成")
            else:
                _log.info("iPhoto 模块预热失败: %s", err)
        except Exception:  # noqa: BLE001
            _log.exception("iPhoto 模块预热异常")

    if background:
        threading.Thread(target=_run, name="iphoto-prewarm", daemon=True).start()
    else:
        _run()
