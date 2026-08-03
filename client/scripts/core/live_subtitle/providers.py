"""预留后端：stub / 云厂商占位（未接 SDK 时明确不可用）。"""

from __future__ import annotations

from .asr_backend import StreamingAsrBackend, TranslationBackend
from .types import LiveSubtitleConfig


class StubStreamingAsr(StreamingAsrBackend):
    """本地占位：接口齐全，但不产生识别结果。"""

    name = "stub"

    def is_available(self) -> bool:
        return False

    def start(self) -> None:
        raise RuntimeError(self.availability_hint())

    def feed_pcm(self, pcm_s16le_16k_mono: bytes) -> None:
        _ = pcm_s16le_16k_mono

    def end_utterance(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def availability_hint(self) -> str:
        return (
            "实时字幕后端尚未接入。\n\n"
            "平台常见方案：\n"
            "1) 流式 ASR（FunASR / 云厂商）出草稿字\n"
            "2) 句末再用稳态模型订正（two_pass）\n"
            "3) 字幕走 WebSocket，与视频分路\n"
            "4) 配置热词提升游戏/口癖识别\n\n"
            "请在 core/live_subtitle/providers/ 实现 StreamingAsrBackend，\n"
            "并在 app.conf 设置 live_subtitle_provider=你的后端名。"
        )


class StubTranslation(TranslationBackend):
    name = "stub"

    def is_available(self) -> bool:
        return False

    def translate(self, text: str, *, source: str, target: str) -> str:
        _ = (source, target)
        return text

    def availability_hint(self) -> str:
        return "翻译后端未接入；可接云翻译或本地 NMT，并在 factory 注册。"


class AliyunStreamingAsrPlaceholder(StreamingAsrBackend):
    """阿里云直播 ASR / CreateRtcAsrTask 等能力占位。"""

    name = "aliyun"

    def is_available(self) -> bool:
        return bool(self.config.cloud_api_key and self.config.cloud_endpoint)

    def start(self) -> None:
        raise RuntimeError(self.availability_hint())

    def feed_pcm(self, pcm_s16le_16k_mono: bytes) -> None:
        _ = pcm_s16le_16k_mono

    def end_utterance(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def availability_hint(self) -> str:
        if not self.config.cloud_api_key:
            return (
                "阿里云实时字幕占位：请配置 live_subtitle_cloud_api_key / "
                "live_subtitle_cloud_endpoint，并实现拉流转写回调对接。"
            )
        return "阿里云 ASR SDK/回调协议尚未实现，仅预留 provider=aliyun。"


class TencentStreamingAsrPlaceholder(StreamingAsrBackend):
    """腾讯云字幕&同传 / MPS 智能字幕占位。"""

    name = "tencent"

    def is_available(self) -> bool:
        return bool(self.config.cloud_api_key and self.config.cloud_endpoint)

    def start(self) -> None:
        raise RuntimeError(self.availability_hint())

    def feed_pcm(self, pcm_s16le_16k_mono: bytes) -> None:
        _ = pcm_s16le_16k_mono

    def end_utterance(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def availability_hint(self) -> str:
        if not self.config.cloud_api_key:
            return (
                "腾讯云实时字幕占位：请配置密钥与 endpoint，"
                "对接「实时动态 / 延时稳态」回调后写入 SubtitleSink。"
            )
        return "腾讯云字幕&同传 SDK 尚未实现，仅预留 provider=tencent。"


class FunAsrStreamingPlaceholder(StreamingAsrBackend):
    """FunASR 流式 Paraformer 占位（可后续 pip + WebSocket runtime）。"""

    name = "funasr"

    def is_available(self) -> bool:
        try:
            import funasr  # noqa: F401
            return True
        except Exception:
            return False

    def start(self) -> None:
        raise RuntimeError(self.availability_hint())

    def feed_pcm(self, pcm_s16le_16k_mono: bytes) -> None:
        _ = pcm_s16le_16k_mono

    def end_utterance(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def availability_hint(self) -> str:
        if self.is_available():
            return "已检测到 funasr 包，但流式会话封装尚未实现（预留 provider=funasr）。"
        return (
            "FunASR 未安装。可后续接入流式 Paraformer（chunk + cache），"
            "实现 StreamingAsrBackend.feed_pcm。"
        )


def build_asr(config: LiveSubtitleConfig) -> StreamingAsrBackend:
    name = (config.provider or "stub").lower()
    mapping = {
        "stub": StubStreamingAsr,
        "aliyun": AliyunStreamingAsrPlaceholder,
        "tencent": TencentStreamingAsrPlaceholder,
        "funasr": FunAsrStreamingPlaceholder,
    }
    cls = mapping.get(name, StubStreamingAsr)
    return cls(config)


def build_translator(config: LiveSubtitleConfig) -> TranslationBackend:
    # 翻译同样先占位；有目标语言时仍返回 stub，pipeline 会因 is_available=False 跳过
    return StubTranslation(config)
