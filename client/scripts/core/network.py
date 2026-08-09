"""授权：本地卡密 + 可选联网激活 / 购买页。

联网协议（可选，配置 license_server_url 后启用）:
  POST {server}/v1/activate
  JSON: {"key": "...", "machine": "<fingerprint>", "product": "MusicEditing"}
  成功响应 JSON: {"ok": true} 或 {"ok": true, "auth_type": "正式版"}
  失败: {"ok": false, "message": "..."} 或 HTTP 非 2xx

未配置服务器时仅本地格式校验（联调默认）。
购买页：license_purchase_url 或环境变量 MUSIC_LICENSE_PURCHASE_URL。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from typing import Any


def normalize_license_key(key: str) -> str:
    return re.sub(r"\s+", "", (key or "").strip()).upper()


def validate_license_key(key: str) -> bool:
    """本地卡密格式校验。

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


def machine_fingerprint() -> str:
    """本机弱指纹（网卡 MAC 哈希），仅用于联网绑机，非安全硬件 ID。"""
    try:
        node = uuid.getnode()
    except Exception:
        node = 0
    raw = f"MusicEditing|{node}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def purchase_url(cfg: dict[str, str] | None = None) -> str:
    env = (os.environ.get("MUSIC_LICENSE_PURCHASE_URL") or "").strip()
    if env:
        return env
    if cfg:
        return (cfg.get("license_purchase_url") or "").strip()
    try:
        from core.app_logic import load_app_config
        return (load_app_config().get("license_purchase_url") or "").strip()
    except Exception:
        return ""


def license_server_url(cfg: dict[str, str] | None = None) -> str:
    env = (os.environ.get("MUSIC_LICENSE_SERVER") or "").strip()
    if env:
        return env.rstrip("/")
    if cfg:
        return (cfg.get("license_server_url") or "").strip().rstrip("/")
    try:
        from core.app_logic import load_app_config
        return (load_app_config().get("license_server_url") or "").strip().rstrip("/")
    except Exception:
        return ""


def _post_json(url: str, payload: dict[str, Any], *, timeout: float = 12.0) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    if not body.strip():
        return {"ok": True}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"服务器返回非 JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise ValueError("服务器返回格式错误")
    return parsed


def activate_online(key: str, *, server: str | None = None) -> tuple[bool, str]:
    """向 license_server 请求激活。成功仅表示服务器认可，调用方仍写本地指纹。"""
    k = normalize_license_key(key)
    if not k:
        return False, "卡密为空"
    base = (server or license_server_url()).rstrip("/")
    if not base:
        return False, "未配置 license_server_url"
    url = f"{base}/v1/activate"
    try:
        result = _post_json(
            url,
            {"key": k, "machine": machine_fingerprint(), "product": "MusicEditing"},
        )
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            pass
        return False, f"服务器拒绝（HTTP {e.code}）{('：' + detail) if detail else ''}"
    except Exception as e:
        return False, f"联网激活失败：{e}"
    if result.get("ok") is True or result.get("success") is True:
        return True, str(result.get("message") or "联网激活成功")
    return False, str(result.get("message") or result.get("error") or "服务器未通过卡密")


def redeem_license_key(key: str) -> tuple[bool, str, str]:
    """兑换入口：优先联网，失败可回退本地格式校验。

    返回 (ok, message, mode)，mode ∈ online | local | local_fallback。
    """
    k = normalize_license_key(key)
    if not k:
        return False, "请输入卡密", "local"

    server = license_server_url()
    if server:
        ok, msg = activate_online(k, server=server)
        if ok:
            return True, msg, "online"
        # 服务器明确拒绝（格式外）则不回退；网络错误可回退本地联调
        if "HTTP 4" in msg or "未通过" in msg or "拒绝" in msg:
            # 4xx / 业务拒绝：若本地格式也过，仍允许本地联调（便于无后端时开发）
            allow_fb = (os.environ.get("MUSIC_LICENSE_OFFLINE_FALLBACK") or "1").strip() not in (
                "0", "false", "no",
            )
            if allow_fb and validate_license_key(k):
                return True, f"{msg}；已回退本地激活（联调）", "local_fallback"
            return False, msg, "online"
        if validate_license_key(k):
            return True, f"{msg}；已回退本地激活", "local_fallback"
        return False, msg, "online"

    if not validate_license_key(k):
        return False, "卡密无效：需至少 16 位，且同时包含字母与数字", "local"
    return True, "已激活为正式版（本地校验）", "local"
