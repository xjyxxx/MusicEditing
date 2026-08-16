#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""根据 dist 产物生成更新 manifest（检查更新 + OTA 预留字段）。

用法（仓库根）:
  python scripts/publish_update_manifest.py --version 0.2.0
  python scripts/publish_update_manifest.py --version 0.2.0 --notes "修复抖动；加速超分"
  python scripts/publish_update_manifest.py --version 0.2.0 --base-url https://cdn.example.com/me/

输出默认: dist/update/musicediting_update.json
同时把最新 Setup/zip/Share 拷到 dist/update/（若存在），并写入 sha256 / package_kind。

本地联调:
  python scripts/serve_update_channel.py
  # app.conf: update_manifest_url=http://127.0.0.1:8777/musicediting_update.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
OUT_DIR = DIST / "update"


def _latest(patterns: list[str]) -> Path | None:
    files: list[Path] = []
    for pat in patterns:
        files.extend(DIST.glob(pat))
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _guess_kind(name: str) -> str:
    low = name.lower()
    if low.endswith(".exe") or "setup" in low:
        return "inno_setup"
    if "share" in low and low.endswith(".zip"):
        return "share_zip"
    if low.endswith(".zip"):
        return "portable_zip"
    return "unknown"


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
    ap.add_argument(
        "--apply-mode",
        default="inplace",
        choices=("manual_replace", "inno_setup", "inplace"),
        help="OTA 应用策略建议（客户端真正替换仍需用户确认「立即升级」）",
    )
    ap.add_argument(
        "--landing-url",
        default="",
        help="可选说明/下载落地页；客户端「打开下载页」优先用它",
    )
    ap.add_argument(
        "--allow-placeholder",
        action="store_true",
        help="无 dist 产物时仍写占位 manifest（不含 sha256，正式客户端会拒绝升级）",
    )
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = _latest(
        [
            "MusicEditing_Setup_*.exe",
            "MusicEditing_Share_*.zip",
            "MusicEditing_Portable_*.zip",
        ]
    )

    sha = ""
    size_bytes = 0
    kind = "unknown"
    if artifact is None:
        if not args.allow_placeholder:
            print(
                "[失败] dist 下没有 Setup / Share / Portable。\n"
                "请先打包，或显式加 --allow-placeholder（将不含 sha256，客户端默认拒绝升级）。",
                flush=True,
            )
            return 1
        print("[警告] 占位 manifest：无产物、无 sha256")
        fname = f"MusicEditing_Setup_{args.version}.exe"
        kind = "inno_setup"
    else:
        dest = OUT_DIR / artifact.name
        if artifact.resolve() != dest.resolve():
            shutil.copy2(artifact, dest)
            print(f"[拷贝] {artifact.name} → dist/update/")
        fname = artifact.name
        kind = _guess_kind(fname)
        sha = _sha256(dest if dest.is_file() else artifact)
        size_bytes = (dest if dest.is_file() else artifact).stat().st_size
        print(f"[校验] sha256={sha[:16]}… size={size_bytes}")

    base = (args.base_url or "").rstrip("/")
    url = f"{base}/{fname}" if base else fname
    landing = (args.landing_url or "").strip()

    data = {
        "version": args.version.strip(),
        "url": url,
        "download_url": url,
        "notes": (args.notes or "").strip() or f"MusicEditing {args.version}",
        "min_version": args.min_version.strip(),
        "channel": "stable",
        "package_kind": kind,
        "size_bytes": size_bytes,
        "ota": {
            "apply_mode": args.apply_mode,
            "restart_required": True,
            "template": "v1",
        },
    }
    if sha:
        data["sha256"] = sha
    if landing:
        data["landing_url"] = landing
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
        "     （正式包禁止 127.0.0.1）\n"
        "  3) 本机试: python scripts/serve_update_channel.py\n"
        "  4) OTA：检查更新 →「下载并升级」→ 确认立即升级（见 distribution.md §5.3）\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
