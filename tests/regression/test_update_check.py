"""回归：版本比较 / 未配置更新 URL。"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ensure_scripts_path, fail, ok

ensure_scripts_path()
from core import update_check  # noqa: E402


def main() -> int:
    if not update_check.version_newer("0.2.0", "0.1.0"):
        fail("0.2 > 0.1")
        return 1
    if update_check.version_newer("0.1.0", "0.2.0"):
        fail("0.1 should not > 0.2")
        return 1
    ok("version_newer")

    info = update_check.check_for_update("0.1.0")
    if info.configured:
        # 环境可能已设 URL，不强制
        ok(f"check configured={info.configured} msg={info.message[:40]}")
    else:
        if "未配置" not in info.message:
            fail(info.message)
            return 1
        ok("unconfigured message")

    # 本地临时 HTTP manifest
    payload = {"version": "9.9.9", "url": "http://example/x.exe", "notes": "test"}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            b = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):  # noqa: A003
            return

    httpd = HTTPServer(("127.0.0.1", 0), H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    import os
    os.environ["MUSIC_UPDATE_URL"] = f"http://127.0.0.1:{port}/u.json"
    info2 = update_check.check_for_update("0.1.0")
    httpd.shutdown()
    if not info2.has_update or info2.remote_version != "9.9.9":
        fail(str(info2))
        return 1
    ok("remote update detected")

    # 相对 url 拼到 manifest 目录
    payload_rel = {"version": "9.9.8", "url": "pkg.exe", "notes": "rel"}
    class H2(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            b = json.dumps(payload_rel).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):  # noqa: A003
            return

    httpd2 = HTTPServer(("127.0.0.1", 0), H2)
    port2 = httpd2.server_address[1]
    threading.Thread(target=httpd2.serve_forever, daemon=True).start()
    os.environ["MUSIC_UPDATE_URL"] = f"http://127.0.0.1:{port2}/dir/u.json"
    info3 = update_check.check_for_update("0.1.0")
    httpd2.shutdown()
    if info3.url != f"http://127.0.0.1:{port2}/dir/pkg.exe":
        fail(f"relative url resolve: {info3.url}")
        return 1
    ok("relative url")

    # 启动静默：同版本不重复提示
    info_u = update_check.UpdateInfo(
        configured=True, has_update=True, local_version="0.1", remote_version="1.0"
    )
    # 不依赖写盘：手动模拟 last
    _orig = update_check.last_notified_version
    update_check.last_notified_version = lambda: "1.0"  # type: ignore
    if update_check.should_prompt_startup(info_u):
        fail("should not prompt same version")
        return 1
    update_check.last_notified_version = lambda: ""  # type: ignore
    if not update_check.should_prompt_startup(info_u):
        fail("should prompt new version")
        return 1
    update_check.last_notified_version = _orig
    ok("should_prompt_startup")

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
