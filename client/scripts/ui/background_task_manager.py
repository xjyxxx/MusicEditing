"""GUI 后台任务调度：QThreadPool、取消令牌和按 key 替换旧任务。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()


class _TaskSignals(QObject):
    succeeded = Signal(str, object, object)
    failed = Signal(str, str, object)
    finished = Signal(str, object)


class _Task(QRunnable):
    def __init__(self, key: str, token: CancelToken, fn: Callable[[CancelToken], object]):
        super().__init__()
        self.key, self.token, self.fn = key, token, fn
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(self.token)
            if not self.token.cancelled:
                self.signals.succeeded.emit(self.key, result, self.token)
        except Exception as exc:
            if not self.token.cancelled:
                self.signals.failed.emit(self.key, str(exc), self.token)
        finally:
            self.signals.finished.emit(self.key, self.token)


class BackgroundTaskManager(QObject):
    taskSucceeded = Signal(str, object)
    taskFailed = Signal(str, str)
    taskFinished = Signal(str)

    def __init__(self, parent=None, max_threads: int = 4):
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max(1, int(max_threads)))
        self._tokens: dict[str, CancelToken] = {}
        self._tasks: dict[str, _Task] = {}

    def submit(self, key: str, fn: Callable[[CancelToken], object], *, replace: bool = True) -> CancelToken:
        if replace:
            self.cancel(key)
        token = CancelToken()
        task = _Task(key, token, fn)
        task.signals.succeeded.connect(self._on_succeeded)
        task.signals.failed.connect(self._on_failed)
        task.signals.finished.connect(self._on_finished)
        self._tokens[key] = token
        self._tasks[key] = task
        self._pool.start(task)
        return token

    def cancel(self, key: str) -> None:
        token = self._tokens.pop(key, None)
        if token is not None:
            token.cancel()
        # QThreadPool 会持有正在运行的 QRunnable；管理器无需继续保留取消任务。
        self._tasks.pop(key, None)

    def cancel_prefix(self, prefix: str) -> None:
        for key in tuple(self._tokens):
            if key.startswith(prefix):
                self.cancel(key)

    def cancel_all(self) -> None:
        for token in tuple(self._tokens.values()):
            token.cancel()
        self._tokens.clear()
        self._tasks.clear()
        self._pool.clear()

    @Slot(str, object, object)
    def _on_succeeded(self, key: str, result: object, token: CancelToken) -> None:
        if self._tokens.get(key) is token and not token.cancelled:
            self.taskSucceeded.emit(key, result)

    @Slot(str, str, object)
    def _on_failed(self, key: str, message: str, token: CancelToken) -> None:
        if self._tokens.get(key) is token and not token.cancelled:
            self.taskFailed.emit(key, message)

    @Slot(str, object)
    def _on_finished(self, key: str, token: CancelToken) -> None:
        if self._tokens.get(key) is token:
            self._tokens.pop(key, None)
            self._tasks.pop(key, None)
            self.taskFinished.emit(key)
