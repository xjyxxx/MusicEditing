#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MusicEditing 简易卡密签发 / 激活服务（stdlib only）。

协议（与 client/scripts/core/network.py 对齐）:
  POST /v1/activate
    {"key","machine","product"} → {"ok": true|false, "message": "..."}
  POST /v1/issue   （支付成功后发卡钩子，演示用）
    {"product","note","token"?} → {"ok": true, "key": "..."}
    若环境变量 MUSIC_LICENSE_ISSUE_TOKEN 非空，则要求 body.token 一致。

另提供简易购买说明页 GET / （演示用，非真实支付收银台）。

用法（仓库根）:
  python scripts/license_server/gen_keys.py --count 5
  python scripts/license_server/server.py --port 8765
  # app.conf:
  #   license_server_url=http://127.0.0.1:8765
  #   license_purchase_url=http://127.0.0.1:8765/
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import string
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
KEYS_PATH = HERE / "keys.json"
BINDINGS_PATH = HERE / "bindings.json"


def _load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_key(key: str) -> str:
    return "".join((key or "").split()).upper()


def issue_key() -> str:
    """签发符合客户端本地格式：≥16 且含字母数字。"""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        raw = "".join(secrets.choice(alphabet) for _ in range(20))
        if any(c.isalpha() for c in raw) and any(c.isdigit() for c in raw):
            parts = [raw[i : i + 4] for i in range(0, 20, 4)]
            return "-".join(parts)


def persist_issued_key(*, note: str = "") -> str:
    """写入 keys.json 并返回卡密明文。"""
    keys: dict = _load_json(KEYS_PATH, {})
    if not isinstance(keys, dict):
        keys = {}
    k = issue_key()
    keys[normalize_key(k)] = {
        "active": True,
        "allow_rebind": True,
        "note": note or "issue-api",
    }
    _save_json(KEYS_PATH, keys)
    return k


SHOP_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>MusicEditing 购买 / 卡密</title>
<style>
body{font-family:Segoe UI,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;color:#222;line-height:1.5}
code,pre{background:#f4f4f5;padding:2px 6px;border-radius:4px}
.box{border:1px solid #ddd;border-radius:10px;padding:16px;margin:16px 0}
h1{font-size:1.4rem}
button{padding:8px 14px;font-size:1rem;cursor:pointer}
#out{margin-top:12px;font-size:1.1rem;word-break:break-all}
</style>
</head>
<body>
<h1>MusicEditing 正式版</h1>
<p>本页为<strong>演示购买入口</strong>。真实收款请换成你的商店（微信/支付宝/Lemon/Stripe 等），
支付成功后由商店 webhook 调 <code>POST /v1/issue</code> 发卡，再把卡密发给用户。</p>
<div class="box">
<p><strong>客户端配置</strong>（<code>app.conf</code>）：</p>
<pre>license_purchase_url=http://本机或域名:8765/
license_server_url=http://本机或域名:8765</pre>
<p>个人中心 →「打开购买页」；兑换时请求 <code>POST /v1/activate</code>。</p>
</div>
<div class="box">
<p><strong>演示：模拟支付成功并发卡</strong></p>
<p>生产请设环境变量 <code>MUSIC_LICENSE_ISSUE_TOKEN</code>，并在 JSON 里带同名 <code>token</code>。</p>
<button type="button" id="btn">模拟支付成功 → 发卡</button>
<div id="out"></div>
</div>
<div class="box">
<p><strong>命令行发卡</strong>：</p>
<pre>python scripts/license_server/gen_keys.py --count 5</pre>
</div>
<p style="color:#666;font-size:0.9rem">闪退请装 VC++ 可再发行组件 x64（不是 Visual Studio）；SmartScreen 点「仍要运行」。</p>
<script>
document.getElementById('btn').onclick = async () => {
  const out = document.getElementById('out');
  out.textContent = '请求中…';
  try {
    const r = await fetch('/v1/issue', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({product: 'MusicEditing', note: 'shop-demo'})
    });
    const j = await r.json();
    if (j.ok && j.key) {
      out.textContent = '卡密（请复制到个人中心）：' + j.key;
    } else {
      out.textContent = '失败：' + (j.message || r.status);
    }
  } catch (e) {
    out.textContent = '网络错误：' + e;
  }
};
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "MusicEditingLicense/0.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, data, "application/json; charset=utf-8")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html", "/buy"):
            self._send(200, SHOP_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/health":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"ok": False, "message": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "message": "invalid json"})
            return

        if path == "/v1/issue":
            self._handle_issue(payload)
            return
        if path != "/v1/activate":
            self._send_json(404, {"ok": False, "message": "not found"})
            return

        key = normalize_key(str(payload.get("key") or ""))
        machine = str(payload.get("machine") or "").strip()
        product = str(payload.get("product") or "")
        if product and product != "MusicEditing":
            self._send_json(400, {"ok": False, "message": "unknown product"})
            return
        if len(key) < 16:
            self._send_json(400, {"ok": False, "message": "卡密无效"})
            return

        keys: dict = _load_json(KEYS_PATH, {})
        if not isinstance(keys, dict):
            keys = {}
        meta = keys.get(key) or keys.get(key.replace("-", ""))
        if meta is None:
            for k, v in keys.items():
                if normalize_key(k).replace("-", "") == key.replace("-", ""):
                    meta = v
                    key = normalize_key(k)
                    break
        if not meta or not meta.get("active", True):
            self._send_json(403, {"ok": False, "message": "卡密不存在或已停用"})
            return

        bindings: dict = _load_json(BINDINGS_PATH, {})
        if not isinstance(bindings, dict):
            bindings = {}
        canon = key.replace("-", "")
        prev = bindings.get(canon)
        if prev and machine and prev != machine:
            allow = meta.get("allow_rebind", True)
            if not allow:
                self._send_json(403, {"ok": False, "message": "卡密已绑定其他设备"})
                return
        if machine:
            bindings[canon] = machine
            _save_json(BINDINGS_PATH, bindings)

        self._send_json(200, {"ok": True, "message": "联网激活成功", "auth_type": "正式版"})

    def _handle_issue(self, payload: dict) -> None:
        product = str(payload.get("product") or "MusicEditing")
        if product != "MusicEditing":
            self._send_json(400, {"ok": False, "message": "unknown product"})
            return
        expect = (os.environ.get("MUSIC_LICENSE_ISSUE_TOKEN") or "").strip()
        got = str(payload.get("token") or "").strip()
        if expect and got != expect:
            self._send_json(403, {"ok": False, "message": "issue token 无效"})
            return
        note = str(payload.get("note") or "api-issue").strip()
        try:
            key = persist_issued_key(note=note)
        except OSError as e:
            self._send_json(500, {"ok": False, "message": f"写入失败: {e}"})
            return
        self._send_json(
            200,
            {
                "ok": True,
                "key": key,
                "message": "已发卡（演示钩子；生产请仅在支付成功 webhook 调用）",
            },
        )


def main() -> int:
    ap = argparse.ArgumentParser(description="MusicEditing license server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if not KEYS_PATH.is_file():
        _save_json(KEYS_PATH, {})
        print(f"[提示] 已创建空 {KEYS_PATH.name}", flush=True)
    token = (os.environ.get("MUSIC_LICENSE_ISSUE_TOKEN") or "").strip()
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[license] http://{args.host}:{args.port}/", flush=True)
    print(f"[license] activate POST /v1/activate  issue POST /v1/issue", flush=True)
    print(
        f"[license] ISSUE_TOKEN={'set' if token else 'unset(demo open)'}",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
