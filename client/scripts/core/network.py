"""网络模块（授权校验等，预留）"""

from __future__ import annotations


def validate_license_key(key: str) -> bool:
    """本地卡密校验（预留实现）"""
    return len(key.strip()) >= 16
