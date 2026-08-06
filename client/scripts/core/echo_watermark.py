"""音频回声水印——自研精简版。

思路参考 HideInfo echo_watermark（MIT）：用不同回声延迟编码 0/1。
不依赖 HideInfo 包。https://github.com/guofei9987/HideInfo

载荷固定封装：魔数 + 长度 + 64 字节 UTF-8 填充，便于可靠提取。
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np

ProgressFn = Callable[[float, str], None]

_MAGIC = b"MEEC"
_MAX_CHARS = 32
_PAYLOAD_PAD = 32  # 固定载荷区（UTF-8）
_PACKET_BYTES = 4 + 2 + _PAYLOAD_PAD  # 38
_PACKET_BITS = _PACKET_BYTES * 8  # 304
_DELAY0 = 80
_DELAY1 = 140
_ALPHA = 0.55
_SEG_SAMPLES = 1536  # ~10.6s 一轮（304*1536/44100）


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _find_ffmpeg() -> Path:
    root = _project_root()
    for p in (
        root / "third_party" / "ffmpeg" / "x64" / "bin" / "ffmpeg.exe",
        root / "third_party" / "ffmpeg" / "x86" / "bin" / "ffmpeg.exe",
    ):
        if p.is_file():
            return p
    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        return Path(found)
    raise FileNotFoundError("未找到 ffmpeg.exe")


def _text_to_bits(text: str) -> List[int]:
    raw = text.encode("utf-8")
    if len(text) > _MAX_CHARS:
        raise ValueError(f"文字请 ≤ {_MAX_CHARS} 字")
    if len(raw) > _PAYLOAD_PAD:
        raise ValueError("UTF-8 过长")
    packet = _MAGIC + struct.pack(">H", len(raw)) + raw.ljust(_PAYLOAD_PAD, b"\0")
    bits: List[int] = []
    for b in packet:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    assert len(bits) == _PACKET_BITS
    return bits


def _bits_to_text(bits: List[int]) -> str:
    if len(bits) < _PACKET_BITS:
        raise RuntimeError("比特不足")
    bits = bits[:_PACKET_BITS]
    raw = bytearray()
    for i in range(0, _PACKET_BITS, 8):
        v = 0
        for j in range(8):
            v = (v << 1) | (bits[i + j] & 1)
        raw.append(v)
    if bytes(raw[:4]) != _MAGIC:
        raise RuntimeError("未检测到回声水印魔数")
    (length,) = struct.unpack(">H", bytes(raw[4:6]))
    if length > _PAYLOAD_PAD:
        raise RuntimeError(f"长度异常: {length}")
    return bytes(raw[6 : 6 + length]).decode("utf-8")


def _read_wav_mono(path: str) -> Tuple[np.ndarray, int]:
    with wave.open(path, "rb") as wf:
        ch = wf.getnchannels()
        sw = wf.getsampwidth()
        rate = wf.getframerate()
        n = wf.getnframes()
        data_raw = wf.readframes(n)
    if sw != 2:
        raise RuntimeError("仅支持 16-bit PCM WAV")
    data = np.frombuffer(data_raw, dtype=np.int16).astype(np.float32)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    data /= 32768.0
    return data, rate


def _write_wav_mono(path: str, samples: np.ndarray, rate: int) -> None:
    clip = np.clip(samples, -1.0, 1.0)
    pcm = (clip * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())


def _embed_echo(samples: np.ndarray, bits: List[int]) -> np.ndarray:
    need = len(bits) * _SEG_SAMPLES
    if len(samples) < need:
        raise ValueError(
            f"音频太短：至少约 {need / 44100:.1f}s（当前 {len(samples) / 44100:.1f}s）"
        )
    out = samples.copy()
    # 可重复多轮增强鲁棒性
    n_rounds = max(1, len(samples) // need)
    for r in range(n_rounds):
        base = r * need
        for i, bit in enumerate(bits):
            d = _DELAY1 if bit else _DELAY0
            a0 = base + i * _SEG_SAMPLES
            a1 = a0 + _SEG_SAMPLES
            if a1 > len(out):
                break
            seg = out[a0:a1].copy()
            echo = np.zeros_like(seg)
            echo[d:] = seg[:-d] * _ALPHA
            out[a0:a1] = seg + echo
    peak = float(np.max(np.abs(out)) or 1.0)
    if peak > 0.98:
        out *= 0.98 / peak
    return out


def _corr_at(seg: np.ndarray, delay: int) -> float:
    if delay >= len(seg) - 16:
        return -1.0
    a = seg[delay:]
    b = seg[: len(a)]
    # 去均值后相关
    a = a - np.mean(a)
    b = b - np.mean(b)
    den = float(np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)
    return float(np.dot(a, b) / den)


def _extract_echo(samples: np.ndarray) -> List[int]:
    need = _PACKET_BITS * _SEG_SAMPLES
    if len(samples) < need:
        raise RuntimeError("音频过短，无法含水印")
    n_rounds = max(1, len(samples) // need)
    # 多数表决
    votes = np.zeros(_PACKET_BITS, dtype=np.int32)
    for r in range(n_rounds):
        base = r * need
        for i in range(_PACKET_BITS):
            a0 = base + i * _SEG_SAMPLES
            a1 = a0 + _SEG_SAMPLES
            if a1 > len(samples):
                break
            seg = samples[a0:a1]
            e0 = _corr_at(seg, _DELAY0)
            e1 = _corr_at(seg, _DELAY1)
            if e1 > e0:
                votes[i] += 1
            else:
                votes[i] -= 1
    return [1 if v > 0 else 0 for v in votes]


def _ffmpeg_extract_wav(media: str, wav_out: str) -> None:
    ff = _find_ffmpeg()
    cmd = [
        str(ff), "-y", "-hide_banner", "-loglevel", "error",
        "-i", media,
        "-vn", "-ac", "1", "-ar", "44100", "-c:a", "pcm_s16le",
        wav_out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.isfile(wav_out):
        raise RuntimeError((r.stderr or "抽音频失败").strip())


def _ffmpeg_mux_video(video: str, wav: str, output: str) -> None:
    ff = _find_ffmpeg()
    cmd = [
        str(ff), "-y", "-hide_banner", "-loglevel", "error",
        "-i", video, "-i", wav,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        output,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0 or not os.path.isfile(output):
        raise RuntimeError((r.stderr or "混流失败").strip())


def embed_echo_watermark(
    media_path: str,
    output_path: str,
    text: str,
    *,
    on_progress: Optional[ProgressFn] = None,
) -> str:
    report = on_progress or (lambda _p, _m: None)
    text = (text or "").strip()
    if not text:
        raise ValueError("水印文字为空")
    if not os.path.isfile(media_path):
        raise FileNotFoundError(media_path)

    bits = _text_to_bits(text)
    ext = Path(media_path).suffix.lower()
    is_video = ext in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}
    tmp = tempfile.mkdtemp(prefix="me_echo_")
    try:
        wav_in = os.path.join(tmp, "in.wav")
        wav_out = os.path.join(tmp, "out.wav")
        report(10.0, "提取音轨…")
        if ext == ".wav":
            # 统一重采样
            _ffmpeg_extract_wav(media_path, wav_in)
        else:
            _ffmpeg_extract_wav(media_path, wav_in)

        report(35.0, "嵌入回声水印…")
        samples, rate = _read_wav_mono(wav_in)
        embedded = _embed_echo(samples, bits)
        _write_wav_mono(wav_out, embedded, rate)

        report(70.0, "写出结果…")
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        if is_video:
            if out.suffix.lower() not in {".mp4", ".mov", ".mkv"}:
                out = out.with_suffix(".mp4")
            _ffmpeg_mux_video(media_path, wav_out, str(out))
        else:
            if out.suffix.lower() != ".wav":
                out = out.with_suffix(".wav")
            shutil.copy2(wav_out, out)
        report(100.0, "完成")
        return str(out.resolve())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def extract_echo_watermark(
    media_path: str,
    *,
    on_progress: Optional[ProgressFn] = None,
) -> str:
    report = on_progress or (lambda _p, _m: None)
    if not os.path.isfile(media_path):
        raise FileNotFoundError(media_path)
    tmp = tempfile.mkdtemp(prefix="me_echo_x_")
    try:
        wav = os.path.join(tmp, "x.wav")
        report(20.0, "提取音轨…")
        _ffmpeg_extract_wav(media_path, wav)
        report(50.0, "分析回声…")
        samples, _rate = _read_wav_mono(wav)
        bits = _extract_echo(samples)
        text = _bits_to_text(bits)
        report(100.0, "完成")
        return text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def min_duration_hint() -> str:
    sec = _PACKET_BITS * _SEG_SAMPLES / 44100.0
    return f"建议素材音轨 ≥ {sec:.0f}s（约 {_PACKET_BITS} bit × {_SEG_SAMPLES} 样点）"
