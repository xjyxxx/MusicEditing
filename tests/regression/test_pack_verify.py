"""回归：便携包验收逻辑（无完整包时造最小目录冒烟）。"""

from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fail, ok, project_root

ROOT = project_root()


def _load_pack():
    path = ROOT / "scripts" / "pack_portable.py"
    spec = importlib.util.spec_from_file_location("pack_portable", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _minimal_tree(root: Path) -> None:
    bin_dir = root / "build_x64" / "bin" / "Release"
    bin_dir.mkdir(parents=True)
    for name in (
        "media_cli.exe",
        "media_player.exe",
        "media_engine.dll",
        "ffmpeg.exe",
        "ffprobe.exe",
    ):
        (bin_dir / name).write_bytes(b"MZ")
    scripts = root / "client" / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "main.pyc").write_bytes(b"\0")
    (root / "MusicEditing.exe").write_bytes(b"MZ")
    (root / "启动 MusicEditing.bat").write_text("@echo off\n", encoding="ascii")
    rt = root / "runtime"
    rt.mkdir(parents=True)
    (rt / "pythonw.exe").write_bytes(b"MZ")
    (root / "使用说明.txt").write_text("ok", encoding="utf-8")


def main() -> int:
    mod = _load_pack()
    with tempfile.TemporaryDirectory(prefix="me_pack_ok_") as td:
        root = Path(td) / "pkg"
        _minimal_tree(root)
        try:
            mod.verify_portable_pack(root, embed_python=True, ship_source=False)
        except SystemExit:
            fail("minimal pack should pass verify")
            return 1
        ok("verify minimal pack")

    with tempfile.TemporaryDirectory(prefix="me_pack_bad_") as td:
        root = Path(td) / "pkg"
        root.mkdir()
        (root / "启动 MusicEditing.bat").write_text("@echo off\n", encoding="ascii")
        try:
            mod.verify_portable_pack(root, embed_python=True, ship_source=False)
            fail("incomplete pack should fail")
            return 1
        except SystemExit:
            ok("verify rejects incomplete pack")

    # 若仓库已有真实便携目录，再验一次（非必须）
    dist = ROOT / "dist"
    if dist.is_dir():
        cands = sorted(
            (p for p in dist.iterdir() if p.is_dir() and p.name.startswith("MusicEditing_Portable")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if cands and (cands[0] / "build_x64" / "bin" / "Release" / "media_cli.exe").is_file():
            try:
                mod.verify_portable_pack(
                    cands[0],
                    embed_python=(cands[0] / "runtime").is_dir(),
                    ship_source=False,
                )
                ok(f"verify existing {cands[0].name}")
            except SystemExit as e:
                # 真实包可能缺 exe，只警告
                print(f"WARN existing pack: {e}")

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
