"""同步 / 核对 third_party/iphoto vendor 与上游 pin。

用法（仓库根目录）:
  python scripts/sync_iphoto_vendor.py              # 仅检查并打印状态
  python scripts/sync_iphoto_vendor.py --write-pin   # 把检测结果写回 VENDOR_PIN.md
  python scripts/sync_iphoto_vendor.py --from DIR    # 从本地上游快照复制 src/iPhoto + src/maps（不含 font/OBF）

不自动 git clone；不改本仓播放器。地图大资源仍按 ASSETS.md 手动补齐。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "third_party" / "iphoto"
PIN = VENDOR / "VENDOR_PIN.md"
SRC = VENDOR / "src"
UPSTREAM_URL = "https://github.com/OliverZhaohaibin/iPhotron-LocalPhotoAlbumManager"
SKIP_DIRS = {"font", "extension", "__pycache__", ".git"}


def _dir_stats(path: Path) -> tuple[int, int]:
    files = 0
    bytes_ = 0
    if not path.is_dir():
        return 0, 0
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            try:
                bytes_ += p.stat().st_size
            except OSError:
                pass
    return files, bytes_


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    def _ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set()
        base = Path(directory).name.lower()
        for name in names:
            if name in SKIP_DIRS or name.lower() in SKIP_DIRS:
                ignored.add(name)
            # maps/tiles/extension
            if base == "tiles" and name.lower() == "extension":
                ignored.add(name)
        return ignored

    shutil.copytree(src, dst, ignore=_ignore)


def check() -> int:
    iphoto = SRC / "iPhoto"
    maps = SRC / "maps"
    font = maps / "font"
    print(f"vendor: {VENDOR}")
    print(f"iPhoto exists: {iphoto.is_dir()}  files={_dir_stats(iphoto)[0]}")
    print(f"maps exists:   {maps.is_dir()}  files={_dir_stats(maps)[0]}")
    font_ok = font.is_dir() and any(font.iterdir()) if font.is_dir() else False
    print(f"maps/font:     {'present' if font_ok else 'MISSING (see ASSETS.md)'}")
    print(f"pin file:      {PIN.is_file()}")
    print(f"upstream:      {UPSTREAM_URL}")
    return 0 if iphoto.is_dir() and maps.is_dir() else 1


def write_pin(*, note: str = "") -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    iphoto_n, _ = _dir_stats(SRC / "iPhoto")
    maps_n, _ = _dir_stats(SRC / "maps")
    font = SRC / "maps" / "font"
    font_ok = font.is_dir() and any(font.iterdir()) if font.is_dir() else False
    body = f"""# Upstream pin

- Source: {UPSTREAM_URL}
- Upstream package version (pyproject): 6.6.8
- Vendor layout: `src/iPhoto` full; `src/maps` without `font/` and `tiles/extension` binaries
- Last checked: {now}
- Snapshot stats: iPhoto files≈{iphoto_n}; maps files≈{maps_n}; maps/font={'yes' if font_ok else 'no'}
- MusicEditing integration: `client/scripts/ui/iphoto_host_page.py` + `core/iphoto_bootstrap.py`
- Player boundary: do not replace MusicEditing `VideoPlayerWidget` / `media_player.exe`
- Sync helper: `python scripts/sync_iphoto_vendor.py`（`--from` 复制本地上游；`--write-pin` 刷新本文件）
- Maps assets: see `src/maps/ASSETS.md`
{f'- Note: {note}' if note else ''}
"""
    PIN.write_text(body.strip() + "\n", encoding="utf-8")
    print(f"wrote {PIN}")


def sync_from(upstream_root: Path) -> int:
    src = upstream_root / "src"
    if not (src / "iPhoto").is_dir():
        print(f"ERROR: {src / 'iPhoto'} missing", file=sys.stderr)
        return 2
    SRC.mkdir(parents=True, exist_ok=True)
    print("copying iPhoto…")
    _copy_tree(src / "iPhoto", SRC / "iPhoto")
    if (src / "maps").is_dir():
        print("copying maps (skip font/extension)…")
        _copy_tree(src / "maps", SRC / "maps")
    write_pin(note=f"synced from {upstream_root}")
    return check()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from", dest="from_dir", type=Path, help="本地上游仓库根目录")
    ap.add_argument("--write-pin", action="store_true", help="刷新 VENDOR_PIN.md")
    args = ap.parse_args()
    if args.from_dir:
        return sync_from(args.from_dir.resolve())
    rc = check()
    if args.write_pin:
        write_pin()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
