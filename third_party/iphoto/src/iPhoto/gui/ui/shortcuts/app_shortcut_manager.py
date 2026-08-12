"""Centralised keyboard shortcut registry for the main application window.

All global (window-level) keyboard shortcuts are **defined and wired in this
single module**.  Adding, modifying, or removing a shortcut requires touching
only this file – not individual coordinators or widgets.

Design principles
-----------------
* Every shortcut uses ``Qt.ShortcutContext.WindowShortcut`` so delivery is
  guaranteed while the application window is active.
* Routing is done at *dispatch time* by inspecting the ``ViewRouter`` state,
  which avoids creating multiple overlapping shortcuts for the same key.
* Arrow keys navigate the gallery / detail timeline.  Edit-video transport
  (frame step) still wins for Left / Right when a video trim session is active.

Shortcut table (all in one place)
----------------------------------
Key       Context              Action
--------- -------------------- ----------------------------------------
Space     Detail / Edit video  Toggle play / pause
M         Detail / Edit video  Toggle mute
Left      Edit video           Step one frame backward
          Detail / Gallery     Previous asset / move selection
Right     Edit video           Step one frame forward
          Detail / Gallery     Next asset / move selection
Up/Down   Detail / Gallery     Previous / next asset (or grid move)
.         Any                  Toggle favourite
Escape    App-wide             Exit full-screen
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QLineEdit,
    QTextEdit,
    QWidget,
)

if TYPE_CHECKING:
    from iPhoto.gui.coordinators.edit_coordinator import EditCoordinator
    from iPhoto.gui.coordinators.view_router import ViewRouter
    from iPhoto.gui.ui.widgets.video_area import VideoArea


class AppShortcutManager(QObject):
    """Owns and dispatches all window-level keyboard shortcuts."""

    def __init__(
        self,
        window: QWidget,
        router: ViewRouter,
        *,
        toggle_favorite_cb: Callable[[], None],
        exit_fullscreen_cb: Callable[[], None],
        next_item_cb: Callable[[], None] | None = None,
        prev_item_cb: Callable[[], None] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._router = router
        self._toggle_favorite_cb = toggle_favorite_cb
        self._exit_fullscreen_cb = exit_fullscreen_cb
        self._next_item_cb = next_item_cb
        self._prev_item_cb = prev_item_cb

        self._video_area: VideoArea | None = None
        self._edit: EditCoordinator | None = None
        self._scope_root: QWidget | None = None

        self._shortcuts: list[QShortcut] = []
        self._register_all()

    def set_video_area(self, video_area: VideoArea) -> None:
        """Bind the shared ``VideoArea`` instance."""
        self._video_area = video_area

    def set_edit_coordinator(self, edit: EditCoordinator) -> None:
        """Bind the ``EditCoordinator`` for edit-mode transport shortcuts."""
        self._edit = edit

    def set_scope_root(self, root: QWidget | None) -> None:
        """Limit ApplicationShortcut 生效范围（嵌入宿主页时传入 IPhotoHostPage）。"""
        self._scope_root = root

    def set_navigation_callbacks(
        self,
        *,
        next_item_cb: Callable[[], None] | None,
        prev_item_cb: Callable[[], None] | None,
    ) -> None:
        """Late-bind previous / next asset callbacks."""
        self._next_item_cb = next_item_cb
        self._prev_item_cb = prev_item_cb

    def _add(self, key: Qt.Key | QKeySequence, handler: Callable[[], None]) -> QShortcut:
        seq = QKeySequence(key) if isinstance(key, Qt.Key) else key
        sc = QShortcut(seq, self._window)
        # ApplicationShortcut：嵌入 MusicEditing 后 MainWindow 不再是顶层窗，
        # WindowShortcut 可能收不到键；应用级仍只在本进程生效。
        sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        sc.activated.connect(handler)
        self._shortcuts.append(sc)
        return sc

    def _add_app(self, key: Qt.Key | QKeySequence, handler: Callable[[], None]) -> QShortcut:
        return self._add(key, handler)

    def _register_all(self) -> None:
        # fmt: off
        self._add(Qt.Key.Key_Space,  self._on_play_pause)
        self._add(Qt.Key.Key_M,      self._on_mute_toggle)
        self._add(Qt.Key.Key_Left,   self._on_left)
        self._add(Qt.Key.Key_Right,  self._on_right)
        self._add(Qt.Key.Key_Up,     self._on_up)
        self._add(Qt.Key.Key_Down,   self._on_down)
        self._add(QKeySequence("."), self._on_toggle_favorite)
        self._add_app(Qt.Key.Key_Escape, self._on_exit_fullscreen)
        # fmt: on

    @staticmethod
    def _focus_is_text_input() -> bool:
        w = QApplication.focusWidget()
        return isinstance(w, (QLineEdit, QTextEdit, QAbstractSpinBox))

    def _shortcut_scope_active(self) -> bool:
        """仅当焦点落在 iPhoto 窗或嵌入宿主根内时响应，避免抢其它工作流页的按键。"""
        root = self._scope_root if self._scope_root is not None else self._window
        if root is None or not root.isVisible():
            return False
        fw = QApplication.focusWidget()
        if fw is None:
            return False
        return fw is root or root.isAncestorOf(fw)

    def _is_video_visible(self) -> bool:
        return self._video_area is not None and self._video_area.has_video()

    def _edit_video_transport_active(self) -> bool:
        return self._edit is not None and self._edit.video_is_transport_active()

    def _on_play_pause(self) -> None:
        if self._focus_is_text_input() or not self._shortcut_scope_active():
            return
        if self._video_area is None:
            return
        if self._edit_video_transport_active():
            self._edit.toggle_video_playback()  # type: ignore[union-attr]
            self._video_area.note_activity()
        elif self._router.is_detail_view_active() and self._is_video_visible():
            if self._video_area.is_playing():
                self._video_area.pause()
            else:
                self._video_area.play()
            self._video_area.note_activity()

    def _on_mute_toggle(self) -> None:
        if self._focus_is_text_input() or not self._shortcut_scope_active():
            return
        if self._video_area is None:
            return
        if not (self._router.is_detail_view_active() or self._router.is_edit_view_active()):
            return
        if not self._is_video_visible():
            return
        self._video_area.toggle_mute()
        self._video_area.note_activity()

    def _on_left(self) -> None:
        if self._focus_is_text_input() or not self._shortcut_scope_active():
            return
        if self._edit_video_transport_active():
            self._edit.step_video_frame(-1)  # type: ignore[union-attr]
            return
        self._navigate_previous(horizontal=True)

    def _on_right(self) -> None:
        if self._focus_is_text_input() or not self._shortcut_scope_active():
            return
        if self._edit_video_transport_active():
            self._edit.step_video_frame(1)  # type: ignore[union-attr]
            return
        self._navigate_next(horizontal=True)

    def _on_up(self) -> None:
        if self._focus_is_text_input() or not self._shortcut_scope_active():
            return
        self._navigate_previous(horizontal=False)

    def _on_down(self) -> None:
        if self._focus_is_text_input() or not self._shortcut_scope_active():
            return
        self._navigate_next(horizontal=False)

    def _navigate_previous(self, *, horizontal: bool) -> None:
        if self._router.is_detail_view_active() or self._router.is_edit_view_active():
            if self._prev_item_cb is not None:
                self._prev_item_cb()
            return
        if self._router.is_gallery_view_active():
            action = (
                QAbstractItemView.CursorAction.MoveLeft
                if horizontal
                else QAbstractItemView.CursorAction.MoveUp
            )
            self._nudge_gallery(action)

    def _navigate_next(self, *, horizontal: bool) -> None:
        if self._router.is_detail_view_active() or self._router.is_edit_view_active():
            if self._next_item_cb is not None:
                self._next_item_cb()
            return
        if self._router.is_gallery_view_active():
            action = (
                QAbstractItemView.CursorAction.MoveRight
                if horizontal
                else QAbstractItemView.CursorAction.MoveDown
            )
            self._nudge_gallery(action)

    def _nudge_gallery(self, action: QAbstractItemView.CursorAction) -> None:
        ui = getattr(self._window, "ui", None)
        grid = getattr(ui, "grid_view", None) if ui is not None else None
        if grid is None:
            return
        current = grid.currentIndex()
        if not current.isValid() and grid.model() is not None and grid.model().rowCount() > 0:
            grid.setCurrentIndex(grid.model().index(0, 0))
            current = grid.currentIndex()
        nxt = grid.moveCursor(action, Qt.KeyboardModifier.NoModifier)
        if nxt.isValid() and nxt != current:
            grid.setCurrentIndex(nxt)
            grid.scrollTo(nxt)
            grid.setFocus(Qt.FocusReason.ShortcutFocusReason)

    def _on_toggle_favorite(self) -> None:
        if not self._shortcut_scope_active():
            return
        self._toggle_favorite_cb()

    def _on_exit_fullscreen(self) -> None:
        self._exit_fullscreen_cb()
