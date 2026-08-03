"""实时字幕：流式草稿 + 稳态订正 + 字幕分路（接口预留）。

平台常见手法（B站/虎牙/云厂商同类能力）在本包中的对应关系：

| 手法 | 本仓库入口 |
|------|------------|
| 2-pass（动态草稿→稳态订正） | `TwoPassSubtitlePipeline` + `SubtitleDisplayMode.TWO_PASS` |
| 字幕与视频分路 | `WebSocketSubtitleSink` / `PlayerOverlaySink` |
| 游戏热词 | `HotwordLexicon` + `StreamingAsrBackend.set_hotwords` |
| 云 ASR/同传 | `providers.build_asr`：`aliyun` / `tencent` / `funasr` 占位 |

当前默认 `live_subtitle_provider=stub`，UI 可提示接入路径；外挂 SRT 加载不受影响。
"""

from __future__ import annotations

from .asr_backend import StreamingAsrBackend, TranslationBackend
from .hotwords import HotwordLexicon
from .pipeline import TwoPassSubtitlePipeline
from .providers import build_asr, build_translator
from .transport import FanOutSink, PlayerOverlaySink, SubtitleSink, WebSocketSubtitleSink
from .types import (
    CueStability,
    LiveSubtitleConfig,
    LiveSubtitleCue,
    SubtitleDisplayMode,
)


def create_pipeline(
    config: LiveSubtitleConfig,
    overlay_set_text,
    *,
    enable_ws: bool = True,
) -> TwoPassSubtitlePipeline:
    """根据配置组装管线（后端未实现时 start() 会抛出明确提示）。"""
    asr = build_asr(config)
    translator = build_translator(config) if config.target_lang else None
    sinks: list[SubtitleSink] = [PlayerOverlaySink(overlay_set_text)]
    if enable_ws and config.ws_url:
        sinks.append(WebSocketSubtitleSink(config.ws_url))
    sink: SubtitleSink = sinks[0] if len(sinks) == 1 else FanOutSink(sinks)
    return TwoPassSubtitlePipeline(
        config,
        asr,
        sink,
        translator=translator,
        lexicon=HotwordLexicon.from_csv(config.hotwords),
    )


def provider_status(config: LiveSubtitleConfig) -> str:
    """给 UI 用的状态说明。"""
    asr = build_asr(config)
    lines = [
        f"provider: {config.provider}",
        f"mode: {config.mode.value}",
        f"source_lang: {config.source_lang}",
        f"target_lang: {config.target_lang or '(关闭翻译)'}",
        f"hotwords: {config.hotwords or '(无)'}",
        f"ws_url: {config.ws_url or '(无，仅播放器叠加)'}",
        "",
        asr.availability_hint(),
    ]
    return "\n".join(lines)


__all__ = [
    "CueStability",
    "LiveSubtitleConfig",
    "LiveSubtitleCue",
    "SubtitleDisplayMode",
    "StreamingAsrBackend",
    "TranslationBackend",
    "HotwordLexicon",
    "TwoPassSubtitlePipeline",
    "PlayerOverlaySink",
    "WebSocketSubtitleSink",
    "FanOutSink",
    "SubtitleSink",
    "build_asr",
    "build_translator",
    "create_pipeline",
    "provider_status",
]
