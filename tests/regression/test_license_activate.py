"""回归：license 签发 + /v1/activate 协议。"""

from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fail, ok, project_root

ROOT = project_root()
LS_DIR = ROOT / "scripts" / "license_server"
sys.path.insert(0, str(LS_DIR))


def main() -> int:
    import server as lic  # noqa: E402

    key = lic.issue_key()
    nk = lic.normalize_key(key)
    keys = {nk: {"active": True, "allow_rebind": True, "note": "test"}}
    # 用临时 keys 路径：直接写回测试文件太危险，改为 monkeypatch 内存
    # 这里起服务器前写入独立临时 keys
    import tempfile

    td = tempfile.TemporaryDirectory(prefix="me_lic_")
    try:
        kpath = Path(td.name) / "keys.json"
        bpath = Path(td.name) / "bindings.json"
        kpath.write_text(json.dumps(keys), encoding="utf-8")
        bpath.write_text("{}", encoding="utf-8")
        lic.KEYS_PATH = kpath
        lic.BINDINGS_PATH = bpath

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), lic.Handler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        time.sleep(0.15)
        url = f"http://127.0.0.1:{port}/v1/activate"
        body = json.dumps(
            {"key": key, "machine": "test-machine", "product": "MusicEditing"}
        ).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            fail(f"activate failed: {data}")
            return 1
        ok(f"activate {key[:8]}…")

        # 无效卡密
        bad = json.dumps(
            {"key": "SHORT", "machine": "x", "product": "MusicEditing"}
        ).encode("utf-8")
        req2 = urllib.request.Request(
            url, data=bad, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            urllib.request.urlopen(req2, timeout=5)
            fail("short key should fail")
            return 1
        except Exception:
            ok("reject short key")

        httpd.shutdown()
    finally:
        td.cleanup()

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
