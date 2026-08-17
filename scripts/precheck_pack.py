# -*- coding: utf-8 -*-
"""打包前快速预检（不真正打完整包）。"""
from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def main() -> int:
    src = (ROOT / "scripts" / "pack_portable.py").read_text(encoding="utf-8")
    bodies = re.findall(r'body = r"""(.*?)"""', src, flags=re.S)
    if len(bodies) != 2:
        print(f"[FAIL] expected 2 bat bodies, got {len(bodies)}")
        return 1
    for i, b in enumerate(bodies):
        try:
            b.encode("ascii")
        except UnicodeEncodeError as e:
            print(f"[FAIL] bat body {i} has non-ASCII: {e}")
            return 1
        print(f"[OK] bat body {i} ASCII ({len(b)} chars)")

    from pack_portable import (  # noqa: WPS433
        PLAYBACK_REQUIRED_GLOBS,
        PLAYBACK_REQUIRED_NAMES,
        REQUIRED_BIN,
        _write_launcher,
    )

    td = Path(tempfile.mkdtemp(prefix="me_precheck_"))
    (td / "runtime").mkdir()
    (td / "runtime" / "pythonw.exe").write_bytes(b"x")
    (td / "build_x64" / "bin" / "Release").mkdir(parents=True)
    (td / "build_x64" / "bin" / "Release" / "media_cli.exe").write_bytes(b"x")
    try:
        _write_launcher(td, embed_python=True)
        bat = next(td.glob("*.bat"))
        bat.read_text(encoding="ascii")
        print(f"[OK] _write_launcher -> {bat.name}")
    except Exception as e:
        print(f"[FAIL] _write_launcher: {e}")
        return 1

    bin_dir = ROOT / "build_x64" / "bin" / "Release"
    miss: list[str] = []
    for name in REQUIRED_BIN:
        if not (bin_dir / name).is_file():
            miss.append(name)
    for pat in PLAYBACK_REQUIRED_GLOBS:
        if not list(bin_dir.glob(pat)):
            miss.append(pat)
    for name in PLAYBACK_REQUIRED_NAMES:
        if name.startswith(("vcruntime", "msvcp")):
            continue  # 打包时再拷贝
        if not (bin_dir / name).is_file():
            miss.append(name)
    if miss:
        print(f"[FAIL] Release 缺文件: {miss}")
        return 1
    print("[OK] Release 关键引擎/播放 DLL 齐全")

    checks = {
        "requirements-iphoto-min.txt": (
            ROOT / "client" / "scripts" / "requirements-iphoto-min.txt"
        ).is_file(),
        "main.py QT_MEDIA_BACKEND": "QT_MEDIA_BACKEND"
        in (ROOT / "client" / "scripts" / "main.py").read_text(encoding="utf-8"),
        "portable_launcher.c QT_MEDIA_BACKEND": "QT_MEDIA_BACKEND"
        in (ROOT / "scripts" / "portable_launcher.c").read_text(encoding="utf-8"),
        "launcher 不污染 PATH": "SetEnvironmentVariableW(L\"PATH\""
        not in (ROOT / "scripts" / "portable_launcher.c").read_text(encoding="utf-8"),
        "只打包.bat -> pack_for_share": "pack_for_share.py"
        in (ROOT / "scripts" / "只打包.bat").read_text(encoding="utf-8", errors="replace"),
    }
    for k, ok in checks.items():
        print(("[OK] " if ok else "[FAIL] ") + k)
        if not ok:
            return 1

    print("\nPRECHECK_PASS — 可以运行 .\\scripts\\只打包.bat")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
