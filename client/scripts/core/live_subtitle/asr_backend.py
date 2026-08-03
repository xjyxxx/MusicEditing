"""流式 ASR 后端抽象（Pass-1 草稿 / Pass-2 稳态订正）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List, Optional, Sequence

from .types import LiveSubtitleConfig, LiveSubtitleCue

# pcm s16le mono 16kHz chunk → 可选回调
AudioChunkHandler = Callable[[bytes], None]
CueHandler = Callable[[LiveSubtitleCue], None]


class StreamingAsrBackend(ABC):
    """
    流式语音识别后端。

    实现方需支持连续喂 PCM，并通过 on_partial / on_final 推送结果。
    Pass-1（草稿）与 Pass-2（订正）可以是同一后端的不同模式，也可以是两个实例。
    """

    name: str = "base"

    def __init__(self, config: LiveSubtitleConfig):
        self.config = config
        self._on_partial: Optional[CueHandler] = None
        self._on_final: Optional[CueHandler] = None

    def set_handlers(
        self,
        *,
        on_partial: Optional[CueHandler] = None,
        on_final: Optional[CueHandler] = None,
    ) -> None:
        self._on_partial = on_partial
        self._on_final = on_final

    @abstractmethod
    def is_available(self) -> bool:
        """依赖是否就绪（模型/密钥/SDK）。"""

    @abstractmethod
    def start(self) -> None:
        """开始会话（建连 / 加载模型）。"""

    @abstractmethod
    def feed_pcm(self, pcm_s16le_16k_mono: bytes) -> None:
        """喂入一帧/一块 PCM。"""

    @abstractmethod
    def end_utterance(self) -> None:
        """外部 VAD 判定一句结束时调用，触发稳态结果。"""

    @abstractmethod
    def stop(self) -> None:
        """结束会话并释放资源。"""

    def set_hotwords(self, words: Sequence[str]) -> None:
        """场景热词（游戏术语、主播口癖等）；默认忽略。"""
        _ = words

    def availability_hint(self) -> str:
        return f"后端 {self.name} 尚未接入，请实现 StreamingAsrBackend 并在 factory 注册。"


class TranslationBackend(ABC):
    """机器翻译 / 同传后端（可与 ASR 分服务）。"""

    name: str = "base"

    def __init__(self, config: LiveSubtitleConfig):
        self.config = config

    @abstractmethod
    def is_available(self) -> bool:
        ...

    @abstractmethod
    def translate(self, text: str, *, source: str, target: str) -> str:
        ...

    def availability_hint(self) -> str:
        return f"翻译后端 {self.name} 尚未接入。"
