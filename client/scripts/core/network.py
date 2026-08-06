"""网络模块（授权校验等）"""

from __future__ import annotations

import hashlib
import re


def normalize_license_key(key: str) -> str:
    return re.sub(r"\s+", "", (key or "").strip()).upper()


def validate_license_key(key: str) -> bool:
    """本地卡密格式校验（联网支付未接入前的联调实现）。

    规则：去掉空白后 ≥16 字符，且含字母与数字。
    """
    k = normalize_license_key(key)
    if len(k) < 16:
        return False
    has_alpha = any(c.isalpha() for c in k)
    has_digit = any(c.isdigit() for c in k)
    return has_alpha and has_digit


def license_fingerprint(key: str) -> str:
    """存配置用指纹，避免明文整段写入日志。"""
    k = normalize_license_key(key)
    if not k:
        return ""
    return hashlib.sha256(k.encode("utf-8")).hexdigest()[:32]
