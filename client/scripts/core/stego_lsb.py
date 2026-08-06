"""图片 LSB 隐形文字水印（自研精简版）。

算法思路参考 HideInfo（MIT）的 hide_in_img / LSB 做法，本文件为独立实现，
未整库拷贝。https://github.com/guofei9987/HideInfo

适用：PNG 等近无损保存；再压 JPEG / 强缩放可能导致水印丢失。
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Tuple

# 魔数 + 4 字节大端长度 + UTF-8 载荷
_MAGIC = b"MEWM"
_MAX_CHARS = 128


def max_payload_bytes(width: int, height: int, channels: int = 3) -> int:
    """可用比特数 / 8（预留魔数与长度头）。"""
    bits = max(0, width * height * channels)
    header = (len(_MAGIC) + 4) * 8
    return max(0, (bits - header) // 8)


def _bits_from_bytes(data: bytes):
    for byte in data:
        for i in range(7, -1, -1):
            yield (byte >> i) & 1


def _bytes_from_bits(bits) -> bytes:
    out = bytearray()
    acc = 0
    n = 0
    for b in bits:
        acc = (acc << 1) | (b & 1)
        n += 1
        if n == 8:
            out.append(acc)
            acc = 0
            n = 0
    return bytes(out)


def embed_text(
    input_path: str,
    output_path: str,
    text: str,
) -> Tuple[str, int]:
    """
    将 UTF-8 文本嵌入图片最低位，写出 PNG。
    返回 (output_path, payload_byte_len)。
    """
    import cv2
    import numpy as np

    text = (text or "").strip()
    if not text:
        raise ValueError("水印文字为空")
    if len(text) > _MAX_CHARS:
        raise ValueError(f"水印文字请 ≤ {_MAX_CHARS} 字（当前 {len(text)}）")

    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(input_path)

    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"无法解码图片: {input_path}")

    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] == 4:
        # 只用 BGR，丢弃 alpha（输出仍为 BGR PNG）
        img = img[:, :, :3].copy()
    else:
        img = img.copy()

    h, w, c = img.shape
    payload = text.encode("utf-8")
    packet = _MAGIC + struct.pack(">I", len(payload)) + payload
    need_bits = len(packet) * 8
    capacity = h * w * c
    if need_bits > capacity:
        raise ValueError(
            f"图片容量不足：需 {len(packet)} 字节，约可容纳 "
            f"{max_payload_bytes(w, h, c)} 字节"
        )

    flat = img.reshape(-1)
    # 清 LSB 再写入
    flat = (flat.astype(np.uint16) & 0xFE).astype(np.uint8)
    for i, bit in enumerate(_bits_from_bytes(packet)):
        flat[i] = np.uint8((int(flat[i]) & 0xFE) | bit)
    out = flat.reshape(img.shape)

    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 强制 PNG
    if out_path.suffix.lower() != ".png":
        out_path = out_path.with_suffix(".png")
    if not cv2.imwrite(str(out_path), out):
        raise RuntimeError(f"写入失败: {out_path}")
    return str(out_path.resolve()), len(payload)


def extract_text(input_path: str) -> str:
    """从 LSB 提取文字；无魔数或损坏则抛错。"""
    import cv2

    path = Path(input_path)
    if not path.is_file():
        raise FileNotFoundError(input_path)
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"无法解码图片: {input_path}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    elif img.shape[2] >= 4:
        img = img[:, :, :3]
    flat = img.reshape(-1)
    # 读魔数 + 长度
    header_bits = (len(_MAGIC) + 4) * 8
    if flat.size < header_bits:
        raise RuntimeError("图片过小，无法含有水印")
    header = _bytes_from_bits(int(flat[i]) & 1 for i in range(header_bits))
    if header[:4] != _MAGIC:
        raise RuntimeError("未检测到本工具写入的隐形水印（魔数不匹配）")
    (length,) = struct.unpack(">I", header[4:8])
    if length <= 0 or length > 1024 * 1024:
        raise RuntimeError(f"水印长度异常: {length}")
    total_bits = header_bits + length * 8
    if flat.size < total_bits:
        raise RuntimeError("水印数据不完整（可能被压缩或裁剪）")
    payload = _bytes_from_bits(
        int(flat[i]) & 1 for i in range(header_bits, total_bits)
    )
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as e:
        raise RuntimeError("水印载荷不是合法 UTF-8（图片可能已损坏）") from e


def capacity_hint(input_path: str) -> str:
    """给人看的容量说明。"""
    import cv2

    img = cv2.imread(input_path, cv2.IMREAD_UNCHANGED)
    if img is None:
        return "无法读取"
    if img.ndim == 2:
        h, w = img.shape
        c = 3
    else:
        h, w = img.shape[:2]
        c = min(3, img.shape[2])
    n = max_payload_bytes(w, h, c)
    return f"{w}×{h} · 约可藏 {n} 字节（建议文案 ≤{_MAX_CHARS} 字）"
