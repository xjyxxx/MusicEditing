"""在 MusicEditing「照片图库」页内嵌 iPhotron。

默认嵌入主窗口；大图走软件预览（SoftImageViewer），避免 QRhi 嵌套空白。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

_log = logging.getLogger(__name__)


class IPhotoHostPage(QWidget):
    """照片图库页：嵌入上游 iPhotron UI。"""

    def __init__(
        self,
        vm,
        open_image_editor: Callable[[str, str], None],
        open_video_editor: Callable[[str, str], None],
        open_video_preview: Callable[[str], None],
        parent=None,
    ):
        super().__init__(parent)
        self._vm = vm
        self._open_image_editor = open_image_editor
        self._open_video_editor = open_video_editor
        self._open_video_preview = open_video_preview
        self._iphoto_window = None
        self._coordinator = None
        self._context = None
        self._mods = None
        self._fallback = None
        self._embed_mode = False
        self._booting = False
        self._cache_sleeping = False
        self.setObjectName("IPhotoHostPage")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)
        # 嵌入默认启用软件大图，避免中间空白
        os.environ.setdefault("MUSIC_IPHOTO_SOFT_VIEWER", "1")
        # 标记由 MusicEditing 宿主；关闭图库时禁止 iPhoto shutdown 调用 app.quit()
        os.environ["MUSIC_IPHOTO_HOSTED"] = "1"
        try:
            from core.iphoto_bootstrap import install_hosted_qt_message_filter

            install_hosted_qt_message_filter()
        except Exception:  # noqa: BLE001
            pass
        self._build_chrome()
        self._selection_timer = QTimer(self)
        self._selection_timer.setInterval(700)
        self._selection_timer.timeout.connect(self._refresh_selection_chrome)
        QTimer.singleShot(0, self._boot_import)

    def _build_chrome(self) -> None:
        bar = QWidget()
        bar.setObjectName("IPhotoHostBar")
        bar.setStyleSheet(
            "#IPhotoHostBar { background:#F5F5F7; border-bottom:1px solid #D2D2D7; }"
            "#IPhotoHostBar QLabel { color:#1D1D1F; }"
            "#IPhotoHostBar QPushButton, #IPhotoHostBar QToolButton {"
            "  background:#FFFFFF; border:1px solid #D2D2D7; border-radius:6px;"
            "  padding:4px 10px; color:#1D1D1F; }"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(12, 8, 12, 8)
        self._status = QLabel("正在加载 iPhotron 图库…")
        self._status.setWordWrap(True)
        row.addWidget(self._status, 1)
        self._sel_label = QLabel("未选中")
        self._sel_label.setObjectName("IPhotoSelLabel")
        self._sel_label.setStyleSheet("#IPhotoSelLabel { color:#6E6E73; max-width: 280px; }")
        self._sel_label.setToolTip("当前选中项路径；点右侧按钮送入本应用工作流")
        row.addWidget(self._sel_label)
        self._btn_play = QPushButton("用本应用播放")
        self._btn_play.setToolTip("把选中视频送到首页播放器（不改 media_player 内核）")
        self._btn_play.clicked.connect(self._play_selection_in_app)
        row.addWidget(self._btn_play)
        self._btn_enhance = QToolButton()
        self._btn_enhance.setText("图片增强")
        self._btn_enhance.setToolTip("把选中图片/视频送到画质增强页")
        self._btn_enhance.clicked.connect(lambda: self._handoff_image("enhance"))
        row.addWidget(self._btn_enhance)
        self._btn_wm = QToolButton()
        self._btn_wm.setText("去水印")
        self._btn_wm.setToolTip("把选中图片/视频送到去水印页")
        self._btn_wm.clicked.connect(lambda: self._handoff_image("watermark"))
        row.addWidget(self._btn_wm)
        self._btn_legacy = QToolButton()
        self._btn_legacy.setText("经典图库")
        self._btn_legacy.setToolTip("切换到 MusicEditing 自研图库；可再点「iPhotron 图库」回来")
        self._btn_legacy.clicked.connect(self._toggle_library_mode)
        row.addWidget(self._btn_legacy)
        self._root.addWidget(bar)

        self._host = QWidget()
        self._host_layout = QVBoxLayout(self._host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._root.addWidget(self._host, 1)

    def _prefer_toplevel(self) -> bool:
        # 默认嵌入；MUSIC_IPHOTO_TOPLEVEL=1 时才独立窗口
        return os.environ.get("MUSIC_IPHOTO_TOPLEVEL", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    def _boot_import(self) -> None:
        if self._fallback is not None or self._booting:
            return
        self._booting = True
        self._status.setText("正在导入 iPhotron 模块…")
        try:
            from core.iphoto_bootstrap import try_import_iphoto

            mods, err = try_import_iphoto()
            if mods is None:
                _log.warning("iPhoto import failed: %s", err)
                self._status.setText(f"iPhotron 不可用，已回退经典图库（{err}）")
                self._booting = False
                self._mount_legacy()
                return
            self._mods = mods
            self._status.setText("正在创建图库…")
            QTimer.singleShot(0, self._boot_window)
        except Exception as exc:  # noqa: BLE001
            _log.exception("iPhoto import stage failed")
            self._status.setText(f"导入失败，已回退经典图库：{exc}")
            self._booting = False
            self._mount_legacy()

    def _boot_window(self) -> None:
        if self._fallback is not None or self._mods is None:
            self._booting = False
            return
        try:
            from core.iphoto_bootstrap import ensure_iphoto_on_path
            from iPhoto.utils.logging import get_logger as _init_logging

            ensure_iphoto_on_path()
            _init_logging()
            # 嵌入路径强制软件大图（可被 MUSIC_IPHOTO_SOFT_VIEWER=0 覆盖）
            if not self._prefer_toplevel():
                os.environ.setdefault("MUSIC_IPHOTO_SOFT_VIEWER", "1")

            SettingsManager = self._mods["SettingsManager"]
            RuntimeContext = self._mods["RuntimeContext"]
            MainWindow = self._mods["MainWindow"]

            settings = SettingsManager()
            settings.load()
            self._context = RuntimeContext.create(defer_startup=True, settings=settings)
            window = MainWindow(self._context)
            self._iphoto_window = window
            self._prepare_hosted_window(window)
            self._bind_hosted_theme(window)
            self._sync_hosted_theme_chrome()

            try:
                window.ui.ensure_feature("detail")
            except Exception as exc:  # noqa: BLE001
                _log.warning("ensure_feature(detail) failed: %s", exc)

            if self._prefer_toplevel():
                self._embed_mode = False
                self._show_as_toplevel(window)
                self._status.setText("iPhotron 图库（独立窗口）…")
            elif self._try_embed(window):
                self._embed_mode = True
                self._hide_embed_window_controls(window)
                self._status.setText("iPhotron 图库（嵌入）· 软件大图预览…")
            else:
                self._embed_mode = False
                self._show_as_toplevel(window)
                self._status.setText("嵌入失败，已改独立窗口…")

            QTimer.singleShot(0, self._start_coordinator)
        except Exception as exc:  # noqa: BLE001
            _log.exception("iPhoto window stage failed")
            self._status.setText(f"启动失败，已回退经典图库：{exc}")
            self._booting = False
            self._mount_legacy()

    def _prepare_hosted_window(self, window) -> None:
        try:
            window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
            window.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
            window.setAutoFillBackground(True)
        except Exception:  # noqa: BLE001
            pass

    def _bind_hosted_theme(self, window) -> None:
        """跟随 iPhotron 深/浅色切换，并用隔离 QSS 盖住宿主浅色级联。"""
        context = self._context
        if context is None:
            return
        theme = getattr(context, "theme", None)
        if theme is None or not hasattr(theme, "themeChanged"):
            return
        try:
            theme.themeChanged.disconnect(self._on_iphoto_theme_changed)
        except Exception:  # noqa: BLE001
            pass
        theme.themeChanged.connect(self._on_iphoto_theme_changed)

    def _on_iphoto_theme_changed(self, is_dark: bool) -> None:
        self._sync_hosted_theme_chrome(bool(is_dark))

    def _iphoto_is_dark(self) -> bool:
        theme = getattr(self._context, "theme", None) if self._context else None
        if theme is not None and hasattr(theme, "get_effective_theme_mode"):
            try:
                if getattr(theme, "_force_dark_mode", False):
                    return True
                return theme.get_effective_theme_mode() == "dark"
            except Exception:  # noqa: BLE001
                pass
        return False

    @staticmethod
    def _hosted_isolation_qss(is_dark: bool) -> str:
        """覆盖 MusicEditing 主窗浅色 QSS 级联，保证图库内深/浅色都可读。"""
        if is_dark:
            return """
            QWidget { color: #F5F5F7; }
            QLabel { color: #F5F5F7; background: transparent; }
            QAbstractItemView {
              background: #2C2C2E; color: #F5F5F7;
              selection-background-color: #0A84FF; selection-color: #FFFFFF;
            }
            QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
              background: #2C2C2E; color: #F5F5F7; border: 1px solid #48484A;
              selection-background-color: #0A84FF; selection-color: #FFFFFF;
            }
            QMenuBar, QMenu { background: #2C2C2E; color: #F5F5F7; }
            QMenu::item:selected { background: #3A3A3C; color: #FFFFFF; }
            QPushButton {
              background: #3A3A3C; color: #F5F5F7; border: 1px solid #48484A;
              border-radius: 6px; padding: 4px 10px;
            }
            QPushButton:hover { background: #48484A; }
            QGroupBox, QCheckBox, QRadioButton, QTabBar::tab { color: #F5F5F7; }
            QTabBar::tab:selected { color: #FFFFFF; }
            QHeaderView::section { background: #2C2C2E; color: #F5F5F7; }
            QStatusBar, QToolTip { background: #1C1C1E; color: #F5F5F7; }
            """
        return """
            QWidget { color: #1D1D1F; }
            QLabel { color: #1D1D1F; background: transparent; }
            QAbstractItemView {
              background: #FFFFFF; color: #1D1D1F;
              selection-background-color: #0A84FF; selection-color: #FFFFFF;
            }
            QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
              background: #FFFFFF; color: #1D1D1F; border: 1px solid #D2D2D7;
              selection-background-color: #0A84FF; selection-color: #FFFFFF;
            }
            QMenuBar, QMenu { background: #F5F5F7; color: #1D1D1F; }
            QMenu::item:selected { background: #E8E8ED; color: #1D1D1F; }
            QPushButton {
              background: #E8E8ED; color: #1D1D1F; border: 1px solid #C7C7CC;
              border-radius: 6px; padding: 4px 10px;
            }
            QPushButton:hover { background: #FFFFFF; }
            QGroupBox, QCheckBox, QRadioButton, QTabBar::tab { color: #1D1D1F; }
            QHeaderView::section { background: #F2F2F7; color: #1D1D1F; }
            QStatusBar, QToolTip { background: #F5F5F7; color: #1D1D1F; }
            """

    def _sync_hosted_theme_chrome(self, is_dark: bool | None = None) -> None:
        """按当前主题给图库窗刷隔离样式，并保持外层 MusicEditing 仍是浅色壳。"""
        window = self._iphoto_window
        if window is None:
            return
        if is_dark is None:
            is_dark = self._iphoto_is_dark()
        try:
            from PySide6.QtGui import QColor, QPalette

            if is_dark:
                bg, fg, muted = QColor("#1C1C1E"), QColor("#F5F5F7"), QColor("#8E8E93")
            else:
                bg, fg, muted = QColor("#F5F5F7"), QColor("#1D1D1F"), QColor("#6E6E73")
            pal = QPalette(window.palette())
            for role in (
                QPalette.ColorRole.Window,
                QPalette.ColorRole.Base,
                QPalette.ColorRole.AlternateBase,
                QPalette.ColorRole.Button,
                QPalette.ColorRole.ToolTipBase,
            ):
                pal.setColor(role, bg)
            for role in (
                QPalette.ColorRole.WindowText,
                QPalette.ColorRole.Text,
                QPalette.ColorRole.ButtonText,
                QPalette.ColorRole.ToolTipText,
            ):
                pal.setColor(role, fg)
            pal.setColor(QPalette.ColorRole.PlaceholderText, muted)
            window.setPalette(pal)
            window.setAutoFillBackground(True)
            window.setStyleSheet(self._hosted_isolation_qss(bool(is_dark)))
            self._restore_host_light_chrome()
        except Exception as exc:  # noqa: BLE001
            _log.debug("sync hosted theme chrome skipped: %s", exc)

    def _restore_host_light_chrome(self) -> None:
        """iPhoto 改全局 palette 后，把外层主窗刷回浅色（不影响图库子树）。"""
        host = self.window()
        if host is None or host is self._iphoto_window:
            return
        try:
            from PySide6.QtGui import QColor, QPalette
            from ui.theme import BG, TEXT, TEXT_MUTED, SURFACE_2, ELEVATED, ACCENT, ACCENT_ON

            pal = QPalette(host.palette())
            bg = QColor(BG)
            fg = QColor(TEXT)
            muted = QColor(TEXT_MUTED)
            pal.setColor(QPalette.ColorRole.Window, bg)
            pal.setColor(QPalette.ColorRole.WindowText, fg)
            pal.setColor(QPalette.ColorRole.Base, QColor(SURFACE_2))
            pal.setColor(QPalette.ColorRole.AlternateBase, QColor(ELEVATED))
            pal.setColor(QPalette.ColorRole.Text, fg)
            pal.setColor(QPalette.ColorRole.Button, QColor(ELEVATED))
            pal.setColor(QPalette.ColorRole.ButtonText, fg)
            pal.setColor(QPalette.ColorRole.PlaceholderText, muted)
            pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
            pal.setColor(QPalette.ColorRole.HighlightedText, QColor(ACCENT_ON))
            host.setPalette(pal)
        except Exception as exc:  # noqa: BLE001
            _log.debug("restore host light chrome skipped: %s", exc)

    def _hide_embed_window_controls(self, window) -> None:
        """嵌入主窗口后隐藏红绿灯（最小化/全屏/关闭），由外层应用管窗口。"""
        ui = getattr(window, "ui", None)
        if ui is None:
            return
        for name in ("window_controls", "minimize_button", "fullscreen_button", "close_button"):
            widget = getattr(ui, name, None)
            if widget is not None:
                try:
                    widget.hide()
                except Exception:  # noqa: BLE001
                    pass
        # 嵌入时也不需要右下角拉伸角
        for name in ("size_grip", "sizeGrip", "bottom_right_grip"):
            grip = getattr(ui, name, None)
            if grip is not None:
                try:
                    grip.hide()
                except Exception:  # noqa: BLE001
                    pass

    def _show_as_toplevel(self, window) -> None:
        window.setWindowTitle("iPhotron 图库 — MusicEditing")
        window.setWindowFlag(Qt.WindowType.Window, True)
        w = max(1100, self.window().width() if self.window() else 1200)
        h = max(700, self.window().height() if self.window() else 800)
        window.resize(w, h)
        if self.window() is not None:
            geo = self.window().geometry()
            window.move(geo.x() + 40, geo.y() + 40)
        window.show()
        window.raise_()
        window.activateWindow()

    def _try_embed(self, window) -> bool:
        try:
            window.setWindowFlags(Qt.WindowType.Widget)
            window.setParent(self._host)
            self._prepare_hosted_window(window)
            self._host_layout.addWidget(window)
            window.show()
            return True
        except Exception as exc:  # noqa: BLE001
            _log.warning("embed MainWindow failed: %s", exc)
            return False

    def _start_coordinator(self) -> None:
        window = self._iphoto_window
        context = self._context
        if window is None or context is None or self._fallback is not None:
            return
        try:
            from core.iphoto_bootstrap import ensure_iphoto_compat, ensure_iphoto_on_path

            ensure_iphoto_on_path()
            ensure_iphoto_compat()
            from iPhoto.gui.coordinators.main_coordinator import MainCoordinator

            for feature in ("preview", "people"):
                try:
                    window.ui.ensure_feature(feature)
                except Exception as exc:  # noqa: BLE001
                    _log.warning("ensure_feature(%s) failed: %s", feature, exc)

            if not hasattr(window.ui, "people_page"):
                raise RuntimeError(
                    "people 功能页未创建成功（缺依赖或导入失败），无法启动协调器"
                )

            coordinator = MainCoordinator(window, context)
            window.set_coordinator(coordinator)
            coordinator.start()
            self._coordinator = coordinator
            sm = getattr(coordinator, "_shortcut_manager", None)
            if sm is not None and hasattr(sm, "set_scope_root"):
                sm.set_scope_root(self if self._embed_mode else window)
            context.resume_startup_tasks()
            # 选中「全部照片」放到下一拍，先让界面可交互
            def _select_all():
                try:
                    window.ui.sidebar.select_all_photos(emit_signal=True)
                except Exception:  # noqa: BLE001
                    pass

            QTimer.singleShot(50, _select_all)
            QTimer.singleShot(0, self._focus_gallery_grid)
            QTimer.singleShot(800, self._ensure_detail_surface)
            QTimer.singleShot(0, self._sync_hosted_theme_chrome)
            mode = "嵌入·软件预览" if self._embed_mode else "独立窗口"
            # capability hints（含 pillow_heif 探测）延后，避免挡首屏就绪
            self._status.setText(f"iPhotron 图库（{mode}）· 已就绪 · ←→↑↓ 切图")
            QTimer.singleShot(0, lambda m=mode: self._apply_capability_hints(m))
            self._selection_timer.start()
            self._refresh_selection_chrome()
        except ModuleNotFoundError as exc:
            _log.exception("MainCoordinator start failed (missing module)")
            missing = getattr(exc, "name", None) or str(exc)
            QMessageBox.warning(
                self,
                "照片图库",
                f"iPhotron 协调器启动失败：缺少模块「{missing}」\n\n"
                "外发包请用最新 scripts\\只打包.bat 重打（含 requirements-iphoto-min）。\n"
                "可点「经典图库」回退。",
            )
        except Exception as exc:  # noqa: BLE001
            _log.exception("MainCoordinator start failed")
            QMessageBox.warning(
                self,
                "照片图库",
                f"iPhotron 协调器启动失败：\n{exc}\n\n可点「经典图库」回退。",
            )
        finally:
            self._booting = False

    def _apply_capability_hints(self, mode: str) -> None:
        hints: list[str] = []
        try:
            from core.iphoto_bootstrap import iphoto_capability_hints

            hints = iphoto_capability_hints()
        except Exception:  # noqa: BLE001
            hints = []
        status = f"iPhotron 图库（{mode}）· 已就绪 · 缓存模式 · ←→↑↓ 切图"
        if hints:
            status = f"{status} · {hints[0]}"
            self._status.setToolTip("\n".join(hints))
        else:
            try:
                from core.iphoto_bootstrap import iphoto_cache_mode_enabled

                if iphoto_cache_mode_enabled():
                    self._status.setToolTip(
                        "缓存模式：离开图库后窗体常驻，再进入秒开。"
                        "关闭：app.conf 设 iphoto_cache_mode=false"
                    )
            except Exception:  # noqa: BLE001
                pass
        self._status.setText(status)

    def pause_selection_watch(self) -> None:
        """离开图库页时停轮询，省 CPU；不卸载窗体。"""
        if getattr(self, "_selection_timer", None) is not None:
            self._selection_timer.stop()

    def resume_selection_watch(self) -> None:
        if self._iphoto_window is None or self._fallback is not None:
            return
        if getattr(self, "_selection_timer", None) is not None:
            self._selection_timer.start()
            self._refresh_selection_chrome()

    def enter_cache_sleep(self) -> None:
        """缓存模式：离开时休眠（不停毁窗体），再进可秒开。"""
        from core.iphoto_bootstrap import iphoto_cache_mode_enabled

        if not iphoto_cache_mode_enabled():
            self.pause_selection_watch()
            return
        if self._fallback is not None or self._iphoto_window is None:
            self.pause_selection_watch()
            return
        self.pause_selection_watch()
        self._cache_sleeping = True
        # 降低休眠时绘制开销
        try:
            if self._iphoto_window is not None:
                self._iphoto_window.setUpdatesEnabled(False)
        except Exception:  # noqa: BLE001
            pass
        self._status.setText("图库已缓存 · 再进入将秒开")

    def wake_from_cache(self) -> bool:
        """若窗体仍在缓存中，直接唤醒。命中返回 True。"""
        if self._fallback is not None:
            return False
        if self._iphoto_window is None:
            self._cache_sleeping = False
            return False
        try:
            self._iphoto_window.setUpdatesEnabled(True)
            self._iphoto_window.update()
        except Exception:  # noqa: BLE001
            pass
        self._cache_sleeping = False
        self.resume_selection_watch()
        mode = "嵌入·软件预览" if self._embed_mode else "独立窗口"
        self._status.setText(f"iPhotron 图库（{mode}）· 缓存命中 · 已就绪")
        QTimer.singleShot(0, self._focus_gallery_grid)
        return True

    def is_cache_hit(self) -> bool:
        return self._iphoto_window is not None and not self._booting

    def release_for_memory(self) -> None:
        """非缓存 / 显式卸载：销毁嵌入 iPhoto。"""
        if self._fallback is not None:
            return
        if self._iphoto_window is None and self._coordinator is None:
            return
        self._cache_sleeping = False
        self._status.setText("图库已卸载（再进入将重新加载）")
        self._teardown_iphoto()
        self._booting = False
        self._context = None

    def ensure_iphoto_awake(self) -> None:
        """切回图库：优先缓存唤醒，否则冷启动。"""
        if self._fallback is not None:
            return
        if self.wake_from_cache():
            return
        if self._booting:
            return
        self._status.setText("正在加载图库…")
        self._booting = False
        QTimer.singleShot(0, self._boot_import)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.ensure_iphoto_awake()

    def _ensure_detail_surface(self) -> None:
        window = self._iphoto_window
        if window is None or self._fallback is not None:
            return
        try:
            detail = getattr(window.ui, "detail_page", None)
            if detail is not None and hasattr(detail, "hide_rhi_init_cover"):
                cover = getattr(detail, "_rhi_init_cover", None)
                if cover is not None and cover.isVisible():
                    detail.hide_rhi_init_cover()
            viewer = getattr(window.ui, "image_viewer", None)
            if viewer is not None:
                viewer.update()
        except Exception as exc:  # noqa: BLE001
            _log.debug("ensure_detail_surface skipped: %s", exc)

    def _focus_gallery_grid(self) -> None:
        window = self._iphoto_window
        if window is None or self._fallback is not None:
            return
        try:
            grid = window.ui.grid_view
            grid.setFocus(Qt.FocusReason.OtherFocusReason)
            if not grid.currentIndex().isValid() and grid.model() is not None:
                model = grid.model()
                if model.rowCount() > 0:
                    grid.setCurrentIndex(model.index(0, 0))
        except Exception as exc:  # noqa: BLE001
            _log.debug("focus gallery grid skipped: %s", exc)

    def _mount_legacy(self) -> None:
        if self._fallback is not None:
            return
        self._status.setText("正在切换经典图库…")
        self._btn_legacy.setEnabled(False)
        # 下一拍再拆，避免在按钮槽里同步 shutdown 卡死/重入
        QTimer.singleShot(0, self._mount_legacy_deferred)

    def _mount_legacy_deferred(self) -> None:
        if self._fallback is not None:
            self._btn_legacy.setEnabled(True)
            return
        from ui.photo_library_page import PhotoLibraryPage

        try:
            self._teardown_iphoto()
            while self._host_layout.count():
                item = self._host_layout.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
            self._fallback = PhotoLibraryPage(
                self._vm,
                open_image_editor=self._open_image_editor,
                open_video_editor=self._open_video_editor,
                open_video_preview=self._open_video_preview,
                parent=self._host,
            )
            self._host_layout.addWidget(self._fallback)
            self._set_toolbar_for_legacy(True)
        except Exception:  # noqa: BLE001
            _log.exception("switch to legacy gallery failed")
            self._status.setText("切换经典图库失败，请查看日志")
        finally:
            self._btn_legacy.setEnabled(True)

    def _teardown_iphoto(self) -> None:
        if getattr(self, "_selection_timer", None) is not None:
            self._selection_timer.stop()
        window = self._iphoto_window
        coordinator = self._coordinator
        self._iphoto_window = None
        self._coordinator = None
        self._context = None
        if window is None:
            return
        try:
            window.hide()
            window.setParent(None)
        except Exception:  # noqa: BLE001
            pass
        # 先有序 shutdown（已禁用 app.quit），再销毁；避免 closeEvent 与布局抢删
        try:
            if coordinator is not None:
                coordinator.shutdown()
            elif getattr(window, "coordinator", None) is not None:
                window.coordinator.shutdown()
        except Exception:  # noqa: BLE001
            _log.exception("iPhoto coordinator shutdown failed")
        try:
            window.coordinator = None
        except Exception:  # noqa: BLE001
            pass
        try:
            wm = getattr(window, "window_manager", None)
            if wm is not None:
                wm.cleanup()
        except Exception:  # noqa: BLE001
            pass
        try:
            window.deleteLater()
        except Exception:  # noqa: BLE001
            pass

    def _set_toolbar_for_legacy(self, legacy: bool) -> None:
        self._btn_play.setEnabled(not legacy)
        self._btn_enhance.setEnabled(not legacy)
        self._btn_wm.setEnabled(not legacy)
        if legacy:
            self._btn_legacy.setText("iPhotron 图库")
            self._btn_legacy.setToolTip("回到 iPhotron 完整图库（嵌入本页）")
            self._status.setText("经典图库 · 点「iPhotron 图库」可切换回来")
        else:
            self._btn_legacy.setText("经典图库")
            self._btn_legacy.setToolTip("切换到 MusicEditing 自研图库；可再点「iPhotron 图库」回来")

    def _toggle_library_mode(self) -> None:
        if self._fallback is not None:
            self._switch_to_iphoto()
        else:
            self._switch_to_legacy()

    def _switch_to_legacy(self) -> None:
        self._mount_legacy()

    def _switch_to_iphoto(self) -> None:
        if self._fallback is not None:
            self._fallback.setParent(None)
            self._fallback.deleteLater()
            self._fallback = None
        while self._host_layout.count():
            item = self._host_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._set_toolbar_for_legacy(False)
        self._status.setText("正在重新打开 iPhotron…")
        self._booting = False
        self._embed_mode = False
        self._mods = None
        QTimer.singleShot(0, self._boot_import)

    def _selected_path(self) -> str | None:
        window = self._iphoto_window
        if window is not None:
            try:
                sel = window.current_selection()
                if sel:
                    return str(sel[0])
            except Exception:  # noqa: BLE001
                pass
        coord = self._coordinator
        if coord is None:
            return None
        detail_vm = getattr(coord, "_detail_vm", None)
        if detail_vm is not None:
            getter = getattr(detail_vm, "current_asset_path", None)
            if callable(getter):
                try:
                    path = getter()
                    if isinstance(path, Path):
                        return str(path)
                    if isinstance(path, str) and path:
                        return path
                except Exception:  # noqa: BLE001
                    pass
        return None

    def _refresh_selection_chrome(self) -> None:
        """把选中路径暴露在宿主栏，并按类型启用播放/增强/去水印。"""
        if self._fallback is not None:
            self._sel_label.setText("经典图库")
            self._btn_play.setEnabled(False)
            self._btn_enhance.setEnabled(False)
            self._btn_wm.setEnabled(False)
            return
        path = self._selected_path()
        if not path:
            self._sel_label.setText("未选中")
            self._sel_label.setToolTip("在图库中点选一张照片或视频")
            self._btn_play.setEnabled(False)
            self._btn_enhance.setEnabled(False)
            self._btn_wm.setEnabled(False)
            return
        name = Path(path).name
        self._sel_label.setText(name)
        self._sel_label.setToolTip(path)
        lower = path.lower()
        video_ext = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm")
        is_video = lower.endswith(video_ext)
        self._btn_play.setEnabled(is_video)
        self._btn_enhance.setEnabled(True)
        self._btn_wm.setEnabled(True)

    def _play_selection_in_app(self) -> None:
        path = self._selected_path()
        if not path:
            QMessageBox.information(
                self, "照片图库", "未找到当前选中项路径，请在图库中点选一张视频后再试。"
            )
            return
        self._open_video_preview(path)

    def _handoff_image(self, target: str) -> None:
        path = self._selected_path()
        if not path:
            QMessageBox.information(self, "照片图库", "请先选中一张图片。")
            return
        lower = path.lower()
        video_ext = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm")
        if lower.endswith(video_ext):
            self._open_video_editor(path, target)
        else:
            self._open_image_editor(path, target)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._iphoto_window is not None and not self._embed_mode:
            try:
                self._iphoto_window.close()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(event)
