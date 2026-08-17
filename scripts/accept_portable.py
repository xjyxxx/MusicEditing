#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干净机 / 本机：验收便携包关键文件（不启动 GUI）。

用法（仓库根）:
  python scripts/accept_portable.py
  python scripts/accept_portable.py dist\\MusicEditing_Portable_20260810
  python scripts/accept_portable.py --zip dist\\MusicEditing_Portable_20260810.zip

退出码 0=通过，1=失败。人类步骤（SmartScreen/VC++）会打印在末尾。
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_pack_module():
    path = ROOT / "scripts" / "pack_portable.py"
    spec = importlib.util.spec_from_file_location("pack_portable", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"无法加载 {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _find_latest_portable() -> Path | None:
    dist = ROOT / "dist"
    if not dist.is_dir():
        return None
    cands = [
        p for p in dist.iterdir()
        if p.is_dir()
        and (
            p.name.startswith("MusicEditing_Portable")
            or p.name.startswith("MusicEditing_Share")
        )
    ]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def _signature_status(path: Path) -> str:
    """返回 Valid / NotSigned / Unknown（仅 Windows）。"""
    if sys.platform != "win32" or not path.is_file():
        return "Unknown"
    try:
        import subprocess

        ps = (
            f"(Get-AuthenticodeSignature -LiteralPath '{path}').Status.ToString()"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        st = (r.stdout or "").strip()
        return st or "Unknown"
    except Exception:
        return "Unknown"


def _human_checklist() -> None:
    print(
        """
======== 干净机人工验收（约 5 分钟）========
1. 解压到无空格短路径，例如 D:\\ME\\
2. 若 SmartScreen「已保护你的电脑」→ 更多信息 → 仍要运行（未签名时正常）
3. 双击 MusicEditing.exe（无黑框）；闪退则装 VC++ 可再发行组件 x64（不是 VS）
4. 首页能开；帮助→个人中心 能进；试跑/切片任选一
5. 正式发版：有证书则 pack --sign，且 build_installer 后会再签 Setup；无证书跳过属正常
==========================================
""",
        flush=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="验收 MusicEditing 便携包")
    ap.add_argument("path", nargs="?", type=Path, default=None, help="便携目录或 .zip")
    ap.add_argument("--zip", type=Path, default=None, help="从 zip 解压到临时目录再验")
    args = ap.parse_args()

    target: Path | None = args.zip or args.path or _find_latest_portable()
    if target is None:
        print("[失败] 未找到 dist/MusicEditing_Share_* 或 MusicEditing_Portable_*，请先打包", flush=True)
        return 1
    if not target.is_absolute():
        target = (ROOT / target).resolve()

    tmp: tempfile.TemporaryDirectory | None = None
    root = target
    try:
        if target.suffix.lower() == ".zip" or args.zip is not None:
            zpath = args.zip or target
            if not zpath.is_file():
                print(f"[失败] zip 不存在: {zpath}", flush=True)
                return 1
            tmp = tempfile.TemporaryDirectory(prefix="me_accept_")
            with zipfile.ZipFile(zpath, "r") as zf:
                zf.extractall(tmp.name)
            # zip 顶层通常是 MusicEditing_Portable_xxx/
            extracted = Path(tmp.name)
            kids = [p for p in extracted.iterdir() if p.is_dir()]
            root = kids[0] if len(kids) == 1 else extracted
            print(f"[解压] {zpath.name} → {root}", flush=True)
        elif not root.is_dir():
            print(f"[失败] 不是目录: {root}", flush=True)
            return 1

        print(f"[验收] {root}", flush=True)
        mod = _load_pack_module()
        # 启发式：有 runtime 即视为内嵌 Python
        embed = (root / "runtime" / "python.exe").is_file() or (
            root / "runtime" / "pythonw.exe"
        ).is_file()
        ship_source = (root / "client" / "scripts" / "main.py").is_file() and not (
            root / "client" / "scripts" / "main.pyc"
        ).is_file()
        try:
            mod.verify_portable_pack(root, embed_python=embed, ship_source=ship_source)
        except SystemExit as e:
            code = int(e.code) if isinstance(e.code, int) else 1
            _human_checklist()
            return code if code != 0 else 1

        exe = root / "MusicEditing.exe"
        if exe.is_file():
            print(f"[验收] MusicEditing.exe  {exe.stat().st_size} bytes", flush=True)
            print(f"[验收] MusicEditing.exe 签名状态: {_signature_status(exe)}", flush=True)
        setups = sorted(
            (ROOT / "dist").glob("MusicEditing_Setup_*.exe"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if setups:
            print(
                f"[验收] 最近 Setup: {setups[0].name} 签名状态: {_signature_status(setups[0])}",
                flush=True,
            )
        print("[验收] PASS", flush=True)
        _human_checklist()
        return 0
    finally:
        if tmp is not None:
            tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
