"""本地 ASR — Vosk 离线语音识别"""

from __future__ import annotations

import json
import os
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional


@dataclass
class AsrSegment:
    start_sec: float
    end_sec: float
    text: str


ProgressFn = Callable[[float, str], None]


def is_vosk_model_dir(path: Path | str) -> bool:
    """目录存在且含 Vosk 模型关键文件（避免把 '.' 或空目录当成模型）。"""
    p = Path(path) if path else Path()
    if not p.is_dir():
        return False
    # 常见结构：am/final.mdl 或 conf/model.conf
    markers = (
        p / "am" / "final.mdl",
        p / "conf" / "model.conf",
        p / "graph" / "phones" / "word_boundary.int",
    )
    return any(m.is_file() for m in markers)


def _looks_like_vosk_model(path: Path) -> bool:
    return is_vosk_model_dir(path)


def resolve_vosk_model_dir(model_dir: Optional[str] = None) -> Path:
    """解析可用的 Vosk 模型绝对路径；找不到则返回期望的默认路径（可能尚不存在）。"""
    root = Path(__file__).resolve().parent.parent.parent.parent
    default = root / "models" / "vosk-model-small-cn-0.22"
    candidates: List[Path] = []

    if model_dir and str(model_dir).strip():
        candidates.append(Path(str(model_dir).strip()).expanduser())

    env = (os.environ.get("VOSK_MODEL_PATH") or "").strip()
    if env:
        candidates.append(Path(env).expanduser())

    candidates.append(default)
    candidates.append(Path.home() / "models" / "vosk-model-small-cn-0.22")

    for p in candidates:
        try:
            resolved = p.resolve()
        except OSError:
            continue
        # 拒绝裸 '.' / 当前工作目录冒充模型
        if resolved == Path.cwd().resolve() and not _looks_like_vosk_model(resolved):
            continue
        if _looks_like_vosk_model(resolved):
            return resolved
    return default.resolve()


class AsrEngine:
    """Vosk 离线 ASR，输出带时间戳的句段"""

    def __init__(self, model_dir: Optional[str] = None):
        self._model_dir = resolve_vosk_model_dir(model_dir)
        self._model = None

    @property
    def model_dir(self) -> Path:
        return self._model_dir

    def is_available(self) -> bool:
        try:
            import vosk  # noqa: F401
        except ImportError:
            return False
        return _looks_like_vosk_model(self._model_dir)

    def _ensure_model(self):
        if self._model is not None:
            return
        from vosk import Model, SetLogLevel
        SetLogLevel(-1)
        if not _looks_like_vosk_model(self._model_dir):
            raise FileNotFoundError(
                f"未找到有效的 Vosk 模型目录: {self._model_dir}\n"
                "请下载 vosk-model-small-cn-0.22 并解压到项目 models/ 目录，"
                "或在 app.conf 设置 vosk_model_dir=绝对路径。\n"
                "无模型时可用「游戏高光」规则分析，或使用「手动切片」。"
            )
        self._model = Model(str(self._model_dir))

    def transcribe(
        self,
        wav_path: str,
        on_progress: Optional[ProgressFn] = None,
    ) -> List[AsrSegment]:
        from vosk import KaldiRecognizer

        self._ensure_model()

        with wave.open(wav_path, "rb") as wf:
            if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                raise ValueError("WAV 须为 16-bit 单声道")
            sample_rate = wf.getframerate()
            rec = KaldiRecognizer(self._model, sample_rate)
            rec.SetWords(True)

            frames = wf.getnframes()
            chunk = 4000
            segments: List[AsrSegment] = []
            pos = 0

            while True:
                data = wf.readframes(chunk)
                if not data:
                    break
                pos += len(data)
                if on_progress and frames > 0:
                    pct = min(99.0, pos / (frames * wf.getsampwidth()) * 100)
                    on_progress(pct, "语音识别中…")

                if rec.AcceptWaveform(data):
                    self._parse_vosk_result(rec.Result(), segments)
                else:
                    self._parse_vosk_partial(rec.PartialResult(), segments)

            self._parse_vosk_result(rec.FinalResult(), segments)

        return self._merge_segments(segments)

    @staticmethod
    def _parse_vosk_result(result_json: str, segments: List[AsrSegment]):
        try:
            obj = json.loads(result_json)
        except json.JSONDecodeError:
            return
        if "result" in obj:
            for w in obj["result"]:
                segments.append(AsrSegment(
                    start_sec=float(w.get("start", 0)),
                    end_sec=float(w.get("end", 0)),
                    text=str(w.get("word", "")),
                ))
        elif obj.get("text"):
            segments.append(AsrSegment(0.0, 0.0, obj["text"]))

    @staticmethod
    def _parse_vosk_partial(result_json: str, segments: List[AsrSegment]):
        pass

    @staticmethod
    def _merge_segments(words: List[AsrSegment], gap: float = 0.8) -> List[AsrSegment]:
        """将词级结果合并为句段"""
        if not words:
            return []
        merged: List[AsrSegment] = []
        cur_start = words[0].start_sec
        cur_end = words[0].end_sec
        cur_text = words[0].text

        for w in words[1:]:
            if not w.text:
                continue
            if w.start_sec - cur_end <= gap:
                cur_end = w.end_sec
                cur_text += w.text
            else:
                if cur_text.strip():
                    merged.append(AsrSegment(cur_start, cur_end, cur_text.strip()))
                cur_start = w.start_sec
                cur_end = w.end_sec
                cur_text = w.text

        if cur_text.strip():
            merged.append(AsrSegment(cur_start, cur_end, cur_text.strip()))
        return merged

    def save_transcript_json(self, segments: List[AsrSegment], json_path: str):
        data = {
            "segments": [
                {"start": s.start_sec, "end": s.end_sec, "text": s.text}
                for s in segments
            ]
        }
        Path(json_path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
