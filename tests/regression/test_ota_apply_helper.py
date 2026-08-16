#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ota_apply_helper.ps1 冒烟：坏源拒收；bak 后失败回滚。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "ota_apply_helper.ps1"


def _run_helper(pending: Path, *, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(HELPER),
            "-PendingPath",
            str(pending),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        env=run_env,
    )


def _write_pending(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_reject_bad_source(td: Path) -> int:
    install = td / "MusicEditing_Install"
    install.mkdir()
    (install / "MusicEditing.exe").write_bytes(b"MZ-KEEP")
    (install / "runtime").mkdir()
    (install / "runtime" / "marker.txt").write_text("alive", encoding="utf-8")

    bad_src = td / "bad_src"
    bad_src.mkdir()
    (bad_src / "readme.txt").write_text("no exe", encoding="utf-8")

    pending = td / "pending_bad.json"
    _write_pending(
        pending,
        {
            "version": "9.9.9",
            "install_root": str(install),
            "source_dir": str(bad_src),
            "package_zip": "",
            "relaunch_exe": str(install / "MusicEditing.exe"),
            "wait_pid": 0,
        },
    )

    r = _run_helper(pending)
    if r.returncode == 0:
        print("FAIL helper should fail when source missing exe")
        print(r.stdout)
        print(r.stderr)
        return 1
    if not (install / "MusicEditing.exe").is_file():
        print("FAIL install MusicEditing.exe missing after failed apply")
        return 1
    if (install / "MusicEditing.exe").read_bytes() != b"MZ-KEEP":
        print("FAIL install exe overwritten")
        return 1
    if not (install / "runtime" / "marker.txt").is_file():
        print("FAIL install tree damaged")
        return 1
    print("OK helper_reject_bad_source rc=", r.returncode)
    return 0


def test_rollback_after_bak(td: Path) -> int:
    """MUSIC_OTA_TEST_FAIL_AFTER_BAK=1：install→bak 后强制失败，应 bak 回滚。"""
    install = td / "MusicEditing_Install"
    install.mkdir()
    (install / "MusicEditing.exe").write_bytes(b"MZ-ORIG")
    (install / "keep.txt").write_text("orig", encoding="utf-8")

    good_src = td / "good_src"
    good_src.mkdir()
    (good_src / "MusicEditing.exe").write_bytes(b"MZ-NEW")
    (good_src / "new.txt").write_text("new", encoding="utf-8")

    pending = td / "pending_roll.json"
    _write_pending(
        pending,
        {
            "version": "9.9.9",
            "install_root": str(install),
            "source_dir": str(good_src),
            "package_zip": "",
            "relaunch_exe": str(install / "MusicEditing.exe"),
            "wait_pid": 0,
        },
    )

    r = _run_helper(pending, env={"MUSIC_OTA_TEST_FAIL_AFTER_BAK": "1"})
    if r.returncode == 0:
        print("FAIL helper should fail under TEST_FAIL_AFTER_BAK")
        print(r.stdout)
        print(r.stderr)
        return 1
    if not install.is_dir():
        print("FAIL install dir missing after rollback")
        return 1
    exe = install / "MusicEditing.exe"
    if not exe.is_file() or exe.read_bytes() != b"MZ-ORIG":
        print("FAIL bak not restored to install")
        return 1
    if not (install / "keep.txt").is_file():
        print("FAIL keep.txt missing after rollback")
        return 1
    if (install / "new.txt").is_file():
        print("FAIL new tree leaked into install")
        return 1
    print("OK helper_rollback_bak rc=", r.returncode)
    return 0


def main() -> int:
    if sys.platform != "win32":
        print("SKIP non-windows")
        return 0
    if not HELPER.is_file():
        print("FAIL missing helper", HELPER)
        return 1

    with tempfile.TemporaryDirectory(prefix="me_ota_hlp_") as td_raw:
        td = Path(td_raw)
        bad_td = td / "case_bad"
        bad_td.mkdir()
        rc = test_reject_bad_source(bad_td)
        if rc != 0:
            return rc
        roll_td = td / "case_roll"
        roll_td.mkdir()
        rc = test_rollback_after_bak(roll_td)
        if rc != 0:
            return rc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
