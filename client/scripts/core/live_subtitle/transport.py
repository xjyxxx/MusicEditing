"""字幕分路传输：播放器叠加 / WebSocket（与视频 HLS·FLV 解耦）。"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Callable, Optional

from .types import LiveSubtitleCue

log = logging.getLogger(__name__)

OverlayCallback = Callable[[str], None]  # 显示文本（可空=清屏）


class SubtitleSink(ABC):
    """字幕下行通道（独立于视频流）。"""

    @abstractmethod
    def publish(self, cue: LiveSubtitleCue) -> None:
        ...

    @abstractmethod
    def clear(self) -> None:
        ...

    def close(self) -> None:
        pass


class PlayerOverlaySink(SubtitleSink):
    """把实时字幕送到播放器底部叠加层（主线程回调由调用方保证）。"""

    def __init__(self, set_text: OverlayCallback):
        self._set_text = set_text
        self._last_final = ""

    def publish(self, cue: LiveSubtitleCue) -> None:
        text = cue.display_text.strip()
        if cue.stability.value == "final":
            self._last_final = text
        self._set_text(text)

    def clear(self) -> None:
        self._last_final = ""
        self._set_text("")


class WebSocketSubtitleSink(SubtitleSink):
    """
    字幕走 WebSocket 分路（预留）。

    生产环境典型做法：视频走 FLV/HLS，字幕 JSON 经 WS 推送，
    客户端按 pts 对齐后渲染，避免卡在切片 GOP。
    """

    def __init__(self, url: str):
        self.url = (url or "").strip()
        self._ws = None  # 预留：websocket-client / Qt 网络

    def is_configured(self) -> bool:
        return bool(self.url)

    def publish(self, cue: LiveSubtitleCue) -> None:
        if not self.url:
            return
        payload = {
            "type": "subtitle",
            "stability": cue.stability.value,
            "text": cue.text,
            "translated": cue.translated_text,
            "start": cue.start_sec,
            "end": cue.end_sec,
            "utterance_id": cue.utterance_id,
        }
        # 预留：self._ws.send(json.dumps(payload, ensure_ascii=False))
        log.debug("WS subtitle stub → %s %s", self.url, json.dumps(payload, ensure_ascii=False)[:200])

    def clear(self) -> None:
        if not self.url:
            return
        log.debug("WS subtitle clear stub → %s", self.url)

    def close(self) -> None:
        self._ws = None


class FanOutSink(SubtitleSink):
    """同时发往多个下行（播放器 + WS）。"""

    def __init__(self, sinks: list[SubtitleSink]):
        self._sinks = list(sinks)

    def publish(self, cue: LiveSubtitleCue) -> None:
        for s in self._sinks:
            try:
                s.publish(cue)
            except Exception:
                log.exception("subtitle sink publish failed: %s", type(s).__name__)

    def clear(self) -> None:
        for s in self._sinks:
            try:
                s.clear()
            except Exception:
                log.exception("subtitle sink clear failed: %s", type(s).__name__)

    def close(self) -> None:
        for s in self._sinks:
            try:
                s.close()
            except Exception:
                pass
