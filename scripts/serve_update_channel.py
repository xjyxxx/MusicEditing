#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地静态托管 dist/update/，用于自动更新联调。

用法:
  python scripts/serve_update_channel.py
  python scripts/serve_update_channel.py --port 8777

然后在 app.conf:
  update_manifest_url=http://127.0.0.1:8777/musicediting_update.json
  update_check_on_startup=true
"""

from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UPDATE_DIR = ROOT / "dist" / "update"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory: str = "", **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        print("%s - %s" % (self.address_string(), fmt % args))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8777)
    args = ap.parse_args()

    UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    mf = UPDATE_DIR / "musicediting_update.json"
    if not mf.is_file():
        demo = {
            "version": "0.2.0",
            "url": "musicediting_demo_placeholder.exe",
            "notes": "本地演示 manifest（请先 publish_update_manifest.py）",
            "min_version": "0.1.0",
        }
        mf.write_text(json.dumps(demo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"[提示] 已写入演示 {mf.name}", flush=True)

    handler = partial(Handler, directory=str(UPDATE_DIR))
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"[update] http://{args.host}:{args.port}/musicediting_update.json", flush=True)
    print(f"[update] 根目录 {UPDATE_DIR}", flush=True)
    print(
        "app.conf 示例:\n"
        f"  update_manifest_url=http://{args.host}:{args.port}/musicediting_update.json\n"
        "  update_check_on_startup=true\n",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
