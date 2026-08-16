#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键发版：regression → pack → accept →（可选）Inno → 写出清单。

用法（仓库根）:
  python scripts/release_oneclick.py
  python scripts/release_oneclick.py --profile slim --no-installer
  python scripts/release_oneclick.py --skip-regression --sign

环境:
  MUSIC_CODE_SIGN_THUMBPRINT  有证书时配合 --sign
"""

from __future__ import annotations

import argparse
import datetime as _dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], *, check: bool = True) -> int:
    print("+", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=str(ROOT))
    if check and r.returncode != 0:
        raise SystemExit(r.returncode)
    return int(r.returncode or 0)


def _latest_portable(profile: str) -> Path | None:
    dist = ROOT / "dist"
    if not dist.is_dir():
        return None
    all_p = [
        p for p in dist.iterdir()
        if p.is_dir() and p.name.startswith("MusicEditing_Portable")
    ]
    if not all_p:
        return None
    if profile == "slim":
        pref = [p for p in all_p if p.name.endswith("_slim")]
    elif profile == "full":
        pref = [p for p in all_p if p.name.endswith("_full")]
    else:
        pref = [
            p for p in all_p
            if not p.name.endswith("_slim") and not p.name.endswith("_full")
        ]
    pool = pref or all_p
    return max(pool, key=lambda p: p.stat().st_mtime)


def main() -> int:
    ap = argparse.ArgumentParser(description="MusicEditing 一键发版")
    ap.add_argument("--profile", choices=("slim", "standard", "full"), default="standard")
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--no-installer", action="store_true", help="跳过 Inno 安装包")
    ap.add_argument("--skip-regression", action="store_true")
    ap.add_argument("--sign", action="store_true")
    ap.add_argument("--skip-pack", action="store_true", help="只用已有 dist 便携目录")
    args = ap.parse_args()

    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
    manifest_lines: list[str] = [
        f"MusicEditing release {stamp}",
        f"profile={args.profile}",
        "",
    ]

    if not args.skip_regression:
        print("=== 1/4 回归短测 ===", flush=True)
        rc = _run(["cmd", "/c", str(ROOT / "scripts" / "run_regression_short.bat")], check=False)
        if rc != 0:
            print("[失败] 回归未通过，中止发版", flush=True)
            return rc
        manifest_lines.append("regression=PASS")
    else:
        manifest_lines.append("regression=SKIPPED")

    portable: Path | None = None
    if not args.skip_pack:
        print("=== 2/4 便携打包 ===", flush=True)
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "pack_portable.py"),
            "--profile",
            args.profile,
        ]
        if not args.no_zip:
            cmd.append("--zip")
        if args.sign:
            cmd.append("--sign")
        _run(cmd)
    else:
        print("=== 2/4 跳过打包，使用已有便携目录 ===", flush=True)

    portable = _latest_portable(args.profile)
    if portable is None:
        print("[失败] 未找到便携目录", flush=True)
        return 1
    manifest_lines.append(f"portable={portable}")

    print("=== 3/4 验收 ===", flush=True)
    _run([sys.executable, str(ROOT / "scripts" / "accept_portable.py"), str(portable)])
    manifest_lines.append("accept=PASS")

    zip_path = portable.with_suffix(".zip")
    if zip_path.is_file():
        manifest_lines.append(f"zip={zip_path} ({zip_path.stat().st_size // (1024*1024)} MB)")

    installer = None
    if not args.no_installer:
        print("=== 4/4 Inno 安装包（可选）===", flush=True)
        rc = _run(
            ["cmd", "/c", str(ROOT / "scripts" / "build_installer.bat"), str(portable)],
            check=False,
        )
        if rc != 0:
            print("[警告] Inno 未生成（可能未安装 Inno Setup 6），继续写清单", flush=True)
            manifest_lines.append("installer=SKIPPED_OR_FAILED")
        else:
            setups = sorted(
                (ROOT / "dist").glob("MusicEditing_Setup_*.exe"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if setups:
                installer = setups[0]
                if args.sign:
                    print("[签名] Setup …", flush=True)
                    _run(
                        [sys.executable, str(ROOT / "scripts" / "sign_artifact.py"), str(installer)],
                        check=False,
                    )
                manifest_lines.append(
                    f"installer={installer} ({installer.stat().st_size // (1024*1024)} MB)"
                )
                manifest_lines.append(
                    "installer_sign=ATTEMPTED" if args.sign else "installer_sign=SKIPPED"
                )
            else:
                manifest_lines.append("installer=NOT_FOUND")
    else:
        manifest_lines.append("installer=SKIPPED")

    manifest_lines.extend(
        [
            "",
            "干净机下一步:",
            "  1) 解压 zip 或运行 Setup.exe",
            "  2) SmartScreen → 更多信息 → 仍要运行（未签名时；有证书则不明显）",
            "  3) 闪退则装 VC++ 可再发行组件 x64（不是 Visual Studio）",
            "  4) 详见 docs/design/distribution.md",
            "",
        ]
    )
    out = ROOT / "dist" / f"RELEASE_MANIFEST_{stamp}.txt"
    out.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    print("\n======== 发版清单 ========", flush=True)
    print(out.read_text(encoding="utf-8"), flush=True)
    print(f"已写入 {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
