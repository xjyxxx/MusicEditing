"""两遍管线：流式草稿 → 句末稳态订正 → 可选翻译 → 字幕分路。"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from .asr_backend import StreamingAsrBackend, TranslationBackend
from .hotwords import HotwordLexicon
from .transport import SubtitleSink
from .types import CueStability, LiveSubtitleConfig, LiveSubtitleCue, SubtitleDisplayMode

log = logging.getLogger(__name__)


class TwoPassSubtitlePipeline:
    """
    平台常见工程手法的本地编排层：

    1. Pass-1 流式 ASR → PARTIAL（实时动态）
    2. 句末 / VAD → Pass-2 更准模型（可同一后端 end_utterance）→ FINAL（延时稳态）
    3. 可选 TranslationBackend
    4. SubtitleSink（播放器叠加 / WebSocket 分路）
    """

    def __init__(
        self,
        config: LiveSubtitleConfig,
        draft_asr: StreamingAsrBackend,
        sink: SubtitleSink,
        *,
        steady_asr: Optional[StreamingAsrBackend] = None,
        translator: Optional[TranslationBackend] = None,
        lexicon: Optional[HotwordLexicon] = None,
    ):
        self.config = config
        self.draft_asr = draft_asr
        self.steady_asr = steady_asr  # 预留：独立 Pass-2；None 则用 draft 的 final
        self.translator = translator
        self.sink = sink
        self.lexicon = lexicon or HotwordLexicon.from_csv(config.hotwords)
        self._running = False
        self._utt = ""

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> None:
        if not self.draft_asr.is_available():
            raise RuntimeError(self.draft_asr.availability_hint())
        words = self.lexicon.as_list()
        self.draft_asr.set_hotwords(words)
        if self.steady_asr is not None:
            if not self.steady_asr.is_available():
                raise RuntimeError(self.steady_asr.availability_hint())
            self.steady_asr.set_hotwords(words)

        self.draft_asr.set_handlers(on_partial=self._on_partial, on_final=self._on_draft_final)
        if self.steady_asr is not None:
            self.steady_asr.set_handlers(on_final=self._on_steady_final)

        self.draft_asr.start()
        if self.steady_asr is not None:
            self.steady_asr.start()
        self._running = True
        self._utt = uuid.uuid4().hex[:12]
        log.info(
            "live subtitle pipeline start provider=%s mode=%s",
            self.config.provider,
            self.config.mode.value,
        )

    def feed_pcm(self, pcm_s16le_16k_mono: bytes) -> None:
        if not self._running:
            return
        self.draft_asr.feed_pcm(pcm_s16le_16k_mono)
        if self.steady_asr is not None:
            self.steady_asr.feed_pcm(pcm_s16le_16k_mono)

    def end_utterance(self) -> None:
        if not self._running:
            return
        self.draft_asr.end_utterance()
        if self.steady_asr is not None:
            self.steady_asr.end_utterance()
        self._utt = uuid.uuid4().hex[:12]

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        try:
            self.draft_asr.stop()
        finally:
            if self.steady_asr is not None:
                try:
                    self.steady_asr.stop()
                except Exception:
                    log.exception("steady asr stop")
            self.sink.clear()
            self.sink.close()
            log.info("live subtitle pipeline stopped")

    def _maybe_translate(self, cue: LiveSubtitleCue) -> LiveSubtitleCue:
        target = (self.config.target_lang or "").strip()
        if not target or not self.translator or not cue.text:
            return cue
        if not self.translator.is_available():
            return cue
        try:
            cue.translated_text = self.translator.translate(
                cue.text,
                source=self.config.source_lang,
                target=target,
            )
            cue.target_language = target
        except Exception:
            log.exception("translate failed")
        return cue

    def _on_partial(self, cue: LiveSubtitleCue) -> None:
        if self.config.mode == SubtitleDisplayMode.DELAYED_STEADY:
            return  # 稳态模式不刷草稿
        cue.stability = CueStability.PARTIAL
        cue.utterance_id = cue.utterance_id or self._utt
        # 草稿一般不做翻译，或做轻量翻译；此处仅原文以保延迟
        self.sink.publish(cue)

    def _on_draft_final(self, cue: LiveSubtitleCue) -> None:
        cue.stability = CueStability.FINAL
        cue.utterance_id = cue.utterance_id or self._utt
        if self.steady_asr is not None and self.config.mode == SubtitleDisplayMode.TWO_PASS:
            # 独立 Pass-2 尚未回时，可先显示 draft final；steady 回调再覆盖
            cue = self._maybe_translate(cue)
            self.sink.publish(cue)
            return
        cue = self._maybe_translate(cue)
        self.sink.publish(cue)

    def _on_steady_final(self, cue: LiveSubtitleCue) -> None:
        cue.stability = CueStability.FINAL
        cue.utterance_id = cue.utterance_id or self._utt
        cue = self._maybe_translate(cue)
        self.sink.publish(cue)
