"""实时字幕类型：与外挂 SRT 分路，面向直播/同传常见协议。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CueStability(str, Enum):
    """对应腾讯云等文档里的动态 vs 稳态。"""

    PARTIAL = "partial"   # 实时动态草稿，可能被改写
    FINAL = "final"       # 延时稳态 / 一句结束订正结果


class SubtitleDisplayMode(str, Enum):
    REALTIME_DYNAMIC = "realtime_dynamic"  # 边说边改
    DELAYED_STEADY = "delayed_steady"      # 整句再出
    TWO_PASS = "two_pass"                  # 草稿 + 订正（推荐）


@dataclass
class LiveSubtitleCue:
    """一条实时字幕（可仅原文，或含译文）。"""

    text: str
    start_sec: float = 0.0
    end_sec: float = 0.0
    stability: CueStability = CueStability.PARTIAL
    translated_text: str = ""
    language: str = "zh"
    target_language: str = ""
    confidence: float = 0.0
    utterance_id: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def display_text(self) -> str:
        if self.translated_text and self.text:
            return f"{self.text}\n{self.translated_text}"
        return self.translated_text or self.text


@dataclass
class LiveSubtitleConfig:
    """来自 app.conf 的实时字幕配置。"""

    provider: str = "stub"  # stub | funasr | aliyun | tencent | custom
    mode: SubtitleDisplayMode = SubtitleDisplayMode.TWO_PASS
    source_lang: str = "zh"
    target_lang: str = ""  # 空 = 不翻译
    hotwords: str = ""  # 逗号分隔
    ws_url: str = ""  # 字幕分路 WebSocket（预留）
    cloud_endpoint: str = ""
    cloud_api_key: str = ""

    @classmethod
    def from_mapping(cls, cfg: dict) -> "LiveSubtitleConfig":
        mode_raw = (cfg.get("live_subtitle_mode") or "two_pass").strip().lower()
        try:
            mode = SubtitleDisplayMode(mode_raw)
        except ValueError:
            mode = SubtitleDisplayMode.TWO_PASS
        return cls(
            provider=(cfg.get("live_subtitle_provider") or "stub").strip().lower(),
            mode=mode,
            source_lang=(cfg.get("live_subtitle_source_lang") or "zh").strip() or "zh",
            target_lang=(cfg.get("live_subtitle_target_lang") or "").strip(),
            hotwords=(cfg.get("live_subtitle_hotwords") or "").strip(),
            ws_url=(cfg.get("live_subtitle_ws_url") or "").strip(),
            cloud_endpoint=(cfg.get("live_subtitle_cloud_endpoint") or "").strip(),
            cloud_api_key=(cfg.get("live_subtitle_cloud_api_key") or "").strip(),
        )
