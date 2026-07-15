"""网易云热评页：输入歌曲链接/ID → 拉取热评 → 播放器区域滚动显示。"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from core.app_logic import AppLogic
from core.netease_comments import HotComment, fetch_hot_comments
from ui.video_player import VideoPlayerWidget
from viewmodels.main_vm import MainViewModel


class _FetchWorker(QObject):
    finished = Signal(list)
    failed = Signal(str)

    def __init__(self, song_input: str, script: str, api_base: str, allow_demo: bool):
        super().__init__()
        self._song_input = song_input
        self._script = script
        self._api_base = api_base
        self._allow_demo = allow_demo

    @Slot()
    def run(self):
        try:
            comments = fetch_hot_comments(
                self._song_input,
                script_path=self._script,
                api_base=self._api_base,
                limit=100,
                allow_demo=self._allow_demo,
            )
            self.finished.emit(comments)
        except Exception as e:
            self.failed.emit(str(e))


class CommentMarquee(QWidget):
    """播放器上方的热评滚动层（从右向左）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")
        self._comments: List[str] = []
        self._labels: List[QLabel] = []
        self._lane_y = [16, 48, 80]
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self._emit_idx = 0
        self._spawn = QTimer(self)
        self._spawn.setInterval(2200)
        self._spawn.timeout.connect(self._spawn_one)

    def set_comments(self, comments: List[HotComment]):
        self.stop()
        self._comments = [c.display_text() for c in comments if c.display_text()]
        self._emit_idx = 0
        if self._comments:
            self._spawn_one()
            self._spawn.start()
            self._timer.start()

    def stop(self):
        self._spawn.stop()
        self._timer.stop()
        for lb in self._labels:
            lb.deleteLater()
        self._labels.clear()

    def _spawn_one(self):
        if not self._comments:
            return
        text = self._comments[self._emit_idx % len(self._comments)]
        self._emit_idx += 1
        lane = (self._emit_idx - 1) % len(self._lane_y)
        lbl = QLabel(text, self)
        lbl.setStyleSheet(
            "color: #fff8e7; background: rgba(0,0,0,140); padding: 4px 10px;"
            "border-radius: 4px; font-size: 14px;"
        )
        f = QFont()
        f.setPointSize(12)
        lbl.setFont(f)
        lbl.adjustSize()
        y = self._lane_y[lane]
        lbl.move(self.width() + 8, y)
        lbl.show()
        self._labels.append(lbl)

        # 最多同时保留有限弹幕，防止堆积
        while len(self._labels) > 18:
            old = self._labels.pop(0)
            old.deleteLater()

    def _tick(self):
        speed = 3
        alive: List[QLabel] = []
        for lb in self._labels:
            x = lb.x() - speed
            if x + lb.width() < -20:
                lb.deleteLater()
                continue
            lb.move(x, lb.y())
            alive.append(lb)
        self._labels = alive

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 保持现有弹幕 y，x 相对不变即可


class HotCommentsPage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._thread: QThread | None = None
        self._worker: _FetchWorker | None = None
        self._comments: List[HotComment] = []

        root = QVBoxLayout(self)

        hint = QLabel(
            "输入网易云歌曲链接或歌曲 ID（例：晴天 186016），回车或点「确定」拉取热评（最多 100 条）并滚动。"
            "默认直连网易云评论接口（思路参考 ObjTube 晴天评论）；"
            "可在 app.conf 配置 netease_api_base 或 netease_hot_comments_script。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        root.addWidget(hint)

        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "例如 https://music.163.com/song?id=347230 或 347230"
        )
        self._input.returnPressed.connect(self._on_confirm)
        self._btn = QPushButton("确定")
        self._btn.setStyleSheet("background: #5b5bd6; color: white; padding: 8px 18px;")
        self._btn.clicked.connect(self._on_confirm)
        row.addWidget(self._input, 1)
        row.addWidget(self._btn)
        root.addLayout(row)

        self._status = QLabel("")
        self._status.setStyleSheet("color: #8cf;")
        root.addWidget(self._status)

        # 播放器 + 热评滚动叠层
        stage = QWidget()
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        self._player = VideoPlayerWidget()
        stage_layout.addWidget(self._player)
        self._marquee = CommentMarquee(stage)
        # 叠在播放器上：用 event filter 式布局 —— 把 marquee 提到同级用绝对定位
        self._stage = stage
        root.addWidget(stage, 1)

        self._list = QTextEdit()
        self._list.setReadOnly(True)
        self._list.setMaximumHeight(140)
        self._list.setPlaceholderText("热评列表预览…")
        root.addWidget(self._list)

        vm.videoLoaded.connect(self._on_video_loaded)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_marquee()

    def showEvent(self, event):
        super().showEvent(event)
        self._layout_marquee()

    def _layout_marquee(self):
        if not self._player or not self._marquee:
            return
        # 覆盖整个 stage（含播放器）顶部三分之一做弹幕区
        geo = self._stage.geometry()
        # marquee 是 stage 的子控件，相对 stage
        w = self._stage.width()
        h = max(120, self._stage.height() // 3)
        self._marquee.setGeometry(0, 0, w, h)
        self._marquee.raise_()

    @Slot(object)
    def _on_video_loaded(self, video):
        if not video or not getattr(video, "file_path", ""):
            return
        # 同步当前工程视频到本页播放器，便于边听边看热评
        try:
            self._player.load_from_video_model(video, auto_play=False)
        except Exception:
            pass

    @Slot()
    def _on_confirm(self):
        text = self._input.text().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请输入歌曲链接或 ID")
            return
        if self._thread and self._thread.isRunning():
            QMessageBox.information(self, "提示", "正在拉取热评，请稍候…")
            return

        app = AppLogic()
        script = app.netease_hot_comments_script
        api_base = getattr(app, "netease_api_base", "") or ""
        allow_demo = app.netease_hot_comments_demo
        self._btn.setEnabled(False)
        self._status.setText("正在获取热评…")
        self._marquee.stop()
        self._list.clear()

        self._thread = QThread(self)
        self._worker = _FetchWorker(text, script, api_base, allow_demo)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_fetched)
        self._worker.failed.connect(self._on_fetch_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()

    @Slot(list)
    def _on_fetched(self, comments: list):
        self._btn.setEnabled(True)
        self._comments = list(comments)
        n = len(self._comments)
        self._status.setText(f"已加载 {n} 条热评，滚动播放中")
        lines = []
        for i, c in enumerate(self._comments, 1):
            like = f"  ♥{c.liked_count}" if c.liked_count else ""
            lines.append(f"{i}. {c.display_text()}{like}")
        self._list.setPlainText("\n".join(lines))
        self._layout_marquee()
        self._marquee.set_comments(self._comments)

    @Slot(str)
    def _on_fetch_failed(self, message: str):
        self._btn.setEnabled(True)
        self._status.setText("获取失败")
        QMessageBox.warning(self, "热评获取失败", message)

    @Slot()
    def _cleanup_worker(self):
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None

    def shutdown(self):
        self._marquee.stop()
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
        self._player.shutdown()
