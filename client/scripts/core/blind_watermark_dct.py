"""封面频域（DCT）隐形文字水印——自研精简版。

思路参考 blind-watermark（频域嵌入、抗轻度压缩优于 LSB），
不依赖 blind-watermark 包。https://github.com/guofei9987/blind_watermark

在 Y 通道 8×8 DCT 块的中频系数上嵌入比特；输出建议 PNG/高质量 JPEG。
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np

_MAGIC = b"MEDC"
_MAX_CHARS = 96
_BLOCK = 8
# 中频位置（相对 DC）
_C1 = (3, 4)
_C2 = (4, 3)
_STRENGTH = 28.0  # 系数差强度


def _text_to_bits(text: str) -> List[int]:
    payload = text.encode("utf-8")
    if len(text) > _MAX_CHARS:
        raise ValueError(f"文字请 ≤ {_MAX_CHARS} 字")
    packet = _MAGIC + struct.pack(">H", len(payload)) + payload
    bits: List[int] = []
    for b in packet:
        for i in range(7, -1, -1):
            bits.append((b >> i) & 1)
    return bits


def _bits_to_text(bits: List[int]) -> str:
    if len(bits) < (4 + 2) * 8:
        raise RuntimeError("比特不足")
    raw = bytearray()
    for i in range(0, len(bits) - 7, 8):
        v = 0
        for j in range(8):
            v = (v << 1) | (bits[i + j] & 1)
        raw.append(v)
    if raw[:4] != _MAGIC:
        raise RuntimeError("未检测到本工具频域水印（魔数不匹配）")
    (length,) = struct.unpack(">H", bytes(raw[4:6]))
    if length <= 0 or length > 4096:
        raise RuntimeError(f"水印长度异常: {length}")
    end = 6 + length
    if len(raw) < end:
        raise RuntimeError("水印数据不完整")
    return bytes(raw[6:end]).decode("utf-8")


def _pad_to_block(gray: np.ndarray) -> Tuple[np.ndarray, int, int]:
    h, w = gray.shape
    nh = ((h + _BLOCK - 1) // _BLOCK) * _BLOCK
    nw = ((w + _BLOCK - 1) // _BLOCK) * _BLOCK
    if nh == h and nw == w:
        return gray, h, w
    out = np.zeros((nh, nw), dtype=np.float32)
    out[:h, :w] = gray
    return out, h, w


def embed_text_dct(
    input_path: str,
    output_path: str,
    text: str,
    *,
    strength: float = _STRENGTH,
) -> Tuple[str, int]:
    """嵌入文字到图片 Y 通道 DCT；返回 (路径, 字节数)。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("水印文字为空")
    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(input_path)

    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"无法解码: {input_path}")
    ycrcb = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb).astype(np.float32)
    y = ycrcb[:, :, 0]
    work, oh, ow = _pad_to_block(y)
    bits = _text_to_bits(text)
    bh = work.shape[0] // _BLOCK
    bw = work.shape[1] // _BLOCK
    n_blocks = bh * bw
    if n_blocks < len(bits):
        raise ValueError(
            f"图片过小：需要至少 {len(bits)} 个 8×8 块，当前 {n_blocks}"
        )

    # 重复铺满可用块，提高鲁棒性
    reps = max(1, n_blocks // len(bits))
    flat_bits = (bits * reps)[:n_blocks]

    idx = 0
    for by in range(bh):
        for bx in range(bw):
            if idx >= len(flat_bits):
                break
            r0, c0 = by * _BLOCK, bx * _BLOCK
            block = work[r0 : r0 + _BLOCK, c0 : c0 + _BLOCK]
            dct = cv2.dct(block)
            bit = flat_bits[idx]
            a = float(dct[_C1])
            b = float(dct[_C2])
            s = float(strength)
            if bit == 1:
                if a <= b:
                    mid = (a + b) * 0.5
                    dct[_C1] = mid + s
                    dct[_C2] = mid - s
            else:
                if a >= b:
                    mid = (a + b) * 0.5
                    dct[_C1] = mid - s
                    dct[_C2] = mid + s
            work[r0 : r0 + _BLOCK, c0 : c0 + _BLOCK] = cv2.idct(dct)
            idx += 1

    ycrcb[:oh, :ow, 0] = np.clip(work[:oh, :ow], 0, 255)
    out_bgr = cv2.cvtColor(ycrcb[:oh, :ow].astype(np.uint8), cv2.COLOR_YCrCb2BGR)
    out = Path(output_path)
    if out.suffix.lower() not in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        out = out.with_suffix(".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() in (".jpg", ".jpeg"):
        ok = cv2.imwrite(str(out), out_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
    else:
        ok = cv2.imwrite(str(out), out_bgr)
    if not ok:
        raise RuntimeError(f"写入失败: {out}")
    return str(out.resolve()), len(text.encode("utf-8"))


def extract_text_dct(input_path: str) -> str:
    """从 DCT 块多数表决提取文字。"""
    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(input_path)
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise RuntimeError(f"无法解码: {input_path}")
    y = cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb)[:, :, 0].astype(np.float32)
    work, _, _ = _pad_to_block(y)
    bh = work.shape[0] // _BLOCK
    bw = work.shape[1] // _BLOCK

    raw_bits: List[int] = []
    for by in range(bh):
        for bx in range(bw):
            r0, c0 = by * _BLOCK, bx * _BLOCK
            block = work[r0 : r0 + _BLOCK, c0 : c0 + _BLOCK]
            dct = cv2.dct(block)
            bit = 1 if float(dct[_C1]) > float(dct[_C2]) else 0
            raw_bits.append(bit)

    # 估计水印长度：先读前 48 bit（魔数+长度）
    header_n = (4 + 2) * 8
    if len(raw_bits) < header_n:
        raise RuntimeError("图片过小")

    # 尝试不同重复次数：假设 watermark 长度 L，n_blocks = k*L
    # 先按单次读取；若魔数失败再按多数表决折叠
    def _try_fold(period: int) -> str:
        if period <= 0 or len(raw_bits) < period:
            raise RuntimeError("fold fail")
        folded: List[int] = []
        for i in range(period):
            ones = 0
            cnt = 0
            j = i
            while j < len(raw_bits):
                ones += raw_bits[j]
                cnt += 1
                j += period
            folded.append(1 if ones * 2 >= cnt else 0)
        return _bits_to_text(folded)

    # 从 header 猜长度：扫描可能 period
    last_err = None
    # period 至少 header+最小载荷；最多块数
    for period in range(header_n, min(len(raw_bits), header_n + 800) + 1):
        try:
            # 快速检查魔数折叠
            folded_hdr = []
            for i in range(header_n):
                ones = sum(raw_bits[j] for j in range(i, len(raw_bits), period))
                cnt = len(range(i, len(raw_bits), period))
                folded_hdr.append(1 if ones * 2 >= cnt else 0)
            hdr = bytearray()
            for i in range(0, header_n, 8):
                v = 0
                for j in range(8):
                    v = (v << 1) | folded_hdr[i + j]
                hdr.append(v)
            if bytes(hdr[:4]) != _MAGIC:
                continue
            (length,) = struct.unpack(">H", bytes(hdr[4:6]))
            need = header_n + length * 8
            if period < need or period > len(raw_bits):
                continue
            return _try_fold(period)
        except Exception as e:
            last_err = e
            continue

    # 回退：无重复（period = 全部按顺序取 need）
    try:
        return _bits_to_text(raw_bits)
    except Exception as e:
        raise RuntimeError(
            f"提取失败（可能被重度压缩）。{last_err or e}"
        ) from e
