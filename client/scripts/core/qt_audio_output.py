"""Qt 音频输出（视频伴音 / 纯音乐均可用）"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class QtAudioOutput:
    """使用 QMediaPlayer 播放音频；视频模式下与 FFmpeg 画面并行。"""

    def __init__(self):
        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._player.setAudioOutput(self._audio)
        self._current_path = ""
        self._duration_ms = 0
        self._on_duration: Optional[Callable[[float], None]] = None
        self._player.durationChanged.connect(self._on_duration_changed)

    def set_duration_callback(self, cb: Optional[Callable[[float], None]]):
        self._on_duration = cb

    def _on_duration_changed(self, duration_ms: int):
        if duration_ms > 0:
            self._duration_ms = int(duration_ms)
            if self._on_duration:
                self._on_duration(self._duration_ms / 1000.0)

    def open(self, path: str):
        self.stop()
        self._current_path = path
        self._duration_ms = 0
        self._player.setSource(QUrl.fromLocalFile(path))

    def play(self, position_sec: float = 0.0):
        if not self._current_path:
            return
        self._player.setPosition(int(max(0.0, position_sec) * 1000))
        self._player.play()

    def pause(self):
        self._player.pause()

    def stop(self):
        self._player.stop()
        self._player.setPosition(0)

    def seek(self, sec: float):
        self._player.setPosition(int(max(0.0, sec) * 1000))

    def position_sec(self) -> float:
        if not self._current_path:
            return 0.0
        return self._player.position() / 1000.0

    def duration_sec(self) -> float:
        d = self._player.duration()
        if d > 0:
            return d / 1000.0
        return self._duration_ms / 1000.0 if self._duration_ms > 0 else 0.0

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def set_volume(self, volume_0_1: float):
        self._audio.setVolume(max(0.0, min(1.0, volume_0_1)))

    def close(self):
        self.shutdown()

    def shutdown(self):
        self._player.stop()
        self._player.setSource(QUrl())
        self._current_path = ""
        self._duration_ms = 0
