"""Qt 音频输出（仅声音，视频仍由 FFmpeg 解码）"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer


class QtAudioOutput:
    """使用 QMediaPlayer 播放音频轨，与 FFmpeg 视频帧解码并行"""

    def __init__(self):
        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._player.setAudioOutput(self._audio)
        self._current_path = ""

    def open(self, path: str):
        self.stop()
        self._current_path = path
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
        """当前播放位置（秒），作为音视频同步主时钟"""
        if not self._current_path:
            return 0.0
        return self._player.position() / 1000.0

    def set_volume(self, volume_0_1: float):
        self._audio.setVolume(max(0.0, min(1.0, volume_0_1)))

    def close(self):
        self.shutdown()

    def shutdown(self):
        """停止播放并释放音频（退出应用时调用）"""
        self._player.stop()
        self._player.setSource(QUrl())
        self._current_path = ""
