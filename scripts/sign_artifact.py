#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对产物做 Authenticode 签名（无证书则跳过，属正常）。

用法（仓库根）:
  python scripts/sign_artifact.py dist\\MusicEditing_Setup_0.1.0.exe
  python scripts/sign_artifact.py --latest-setup
  python scripts/sign_artifact.py --latest-portable-exe

环境变量: MUSIC_CODE_SIGN_THUMBPRINT=证书 SHA1（可选）
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_try_sign():
    path = ROOT / "scripts" / "pack_portable.py"
    spec = importlib.util.spec_from_file_location("pack_portable", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.try_sign_exe


def _latest(glob_pat: str) -> Path | None:
    files = sorted((ROOT / "dist").glob(glob_pat), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def main() -> int:
    ap = argparse.ArgumentParser(description="签名 MusicEditing 产物")
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--latest-setup", action="store_true")
    ap.add_argument("--latest-portable-exe", action="store_true")
    args = ap.parse_args()

    targets: list[Path] = []
    for p in args.paths:
        targets.append(p if p.is_absolute() else (ROOT / p).resolve())
    if args.latest_setup:
        s = _latest("MusicEditing_Setup_*.exe")
        if s:
            targets.append(s)
        else:
            print("[签名] 未找到 dist/MusicEditing_Setup_*.exe，跳过", flush=True)
    if args.latest_portable_exe:
        for d in sorted(
            (ROOT / "dist").glob("MusicEditing_*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            if d.is_dir():
                exe = d / "MusicEditing.exe"
                if exe.is_file():
                    targets.append(exe)
                    break

    if not targets:
        print("[签名] 无目标文件（无证书时也可忽略）", flush=True)
        return 0

    try_sign = _load_try_sign()
    ok_n = 0
    for t in targets:
        if not t.is_file():
            print(f"[签名] 不存在: {t}", flush=True)
            continue
        print(f"[签名] 尝试 {t.name} …", flush=True)
        if try_sign(t):
            ok_n += 1
            print(f"[签名] 成功: {t}", flush=True)
        else:
            print(f"[签名] 跳过/失败: {t}（无证书属正常）", flush=True)
    print(f"[签名] 完成成功 {ok_n}/{len(targets)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
