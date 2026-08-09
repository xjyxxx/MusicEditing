#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 dist 产物生成更新 manifest（给自动更新用）。

用法（仓库根）:
  python scripts/publish_update_manifest.py --version 0.2.0
  python scripts/publish_update_manifest.py --version 0.2.0 --notes "修复抖动；加速超分"
  python scripts/publish_update_manifest.py --version 0.2.0 --base-url https://cdn.example.com/me/

输出默认: dist/update/musicediting_update.json
同时把最新 Setup/zip 拷到 dist/update/（若存在），方便用本地 HTTP 测。

本地联调:
  python scripts/serve_update_channel.py
  # app.conf: update_manifest_url=http://127.0.0.1:8777/musicediting_update.json
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
OUT_DIR = DIST / "update"


def _latest(glob_pat: str) -> Path | None:
    files = sorted(DIST.glob(glob_pat), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def main() -> int:
    ap = argparse.ArgumentParser(description="发布 MusicEditing 更新 manifest")
    ap.add_argument("--version", required=True, help="新版本号，如 0.2.0")
    ap.add_argument("--notes", default="", help="更新说明")
    ap.add_argument(
        "--base-url",
        default="",
        help="下载基址，如 https://cdn.example.com/me/ ；空则用相对文件名（配合本地 serve）",
    )
    ap.add_argument("--min-version", default="0.1.0")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    setup = _latest("MusicEditing_Setup_*.exe")
    zips = sorted(
        DIST.glob("MusicEditing_Portable_*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    portable_zip = zips[0] if zips else None

    artifact: Path | None = setup or portable_zip
    if artifact is None:
        print("[警告] dist 下没有 Setup.exe / Portable zip，manifest 的 url 仅写占位名")
        fname = f"MusicEditing_Setup_{args.version}.exe"
    else:
        dest = OUT_DIR / artifact.name
        if artifact.resolve() != dest.resolve():
            shutil.copy2(artifact, dest)
            print(f"[拷贝] {artifact.name} → dist/update/")
        fname = artifact.name

    base = (args.base_url or "").rstrip("/")
    url = f"{base}/{fname}" if base else fname

    data = {
        "version": args.version.strip(),
        "url": url,
        "notes": (args.notes or "").strip() or f"MusicEditing {args.version}",
        "min_version": args.min_version.strip(),
        "channel": "stable",
    }
    out = args.out or (OUT_DIR / "musicediting_update.json")
    if not out.is_absolute():
        out = (ROOT / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[完成] {out}")
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(
        "\n上线步骤:\n"
        "  1) 把 dist/update/ 上传到你的 CDN/静态站\n"
        "  2) app.conf 设 update_manifest_url=https://你的域名/.../musicediting_update.json\n"
        "  3) 本机试: python scripts/serve_update_channel.py\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
