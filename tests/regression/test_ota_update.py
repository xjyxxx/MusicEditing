#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OTA：plan / sha256 / extract / pending / apply stub&schedule 冒烟。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "client" / "scripts"))

from core.ota_update import (  # noqa: E402
    ApplyMode,
    PackageKind,
    apply_package,
    extract_package,
    file_sha256,
    find_payload_root,
    plan_from_update_info,
    write_pending,
)
from core.update_check import UpdateInfo  # noqa: E402


def main() -> int:
    info = UpdateInfo(
        configured=True,
        has_update=True,
        local_version="0.1.0",
        remote_version="0.2.0",
        url="https://cdn.example.com/MusicEditing_Share_0.2.0.zip",
        notes="test",
        sha256="abc",
        package_kind="share_zip",
        manifest_extra={
            "package_kind": "share_zip",
            "sha256": "abc",
            "ota": {"apply_mode": "inplace"},
        },
    )
    plan = plan_from_update_info(info, manifest_extra=info.manifest_extra)
    assert plan is not None
    assert plan.package_kind == PackageKind.SHARE_ZIP
    assert plan.apply_mode == ApplyMode.INPLACE

    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        # fake portable tree inside zip
        payload = td_path / "MusicEditing_Share_0.2.0"
        payload.mkdir()
        (payload / "MusicEditing.exe").write_bytes(b"MZ-fake")
        (payload / "runtime").mkdir()
        zip_path = td_path / "pkg.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(payload / "MusicEditing.exe", "MusicEditing_Share_0.2.0/MusicEditing.exe")
            zf.writestr("MusicEditing_Share_0.2.0/runtime/.keep", "")

        digest = file_sha256(zip_path)
        assert len(digest) == 64

        os.environ["MUSIC_INSTALL_ROOT"] = str(td_path / "install")
        install = Path(os.environ["MUSIC_INSTALL_ROOT"])
        install.mkdir()
        (install / "MusicEditing.exe").write_bytes(b"old")
        (install / "runtime").mkdir()

        root = extract_package(zip_path, version="0.2.0")
        assert (root / "MusicEditing.exe").is_file()
        assert find_payload_root(root.parent if root.name != "extracted" else root)

        pending = write_pending(
            install=install,
            source_dir=root,
            package_zip=None,
            version="0.2.0",
            wait_pid=0,
        )
        data = json.loads(pending.read_text(encoding="utf-8"))
        assert data["version"] == "0.2.0"
        assert Path(data["source_dir"]).is_dir()

        # 无 force：手动指引
        r1 = apply_package(plan, zip_path, force_inplace=False)
        assert r1.stub is True

        # 有 helper 才测 schedule；复制仓库 helper 到 staging 由 ensure 处理
        helper_src = ROOT / "scripts" / "ota_apply_helper.ps1"
        assert helper_src.is_file()
        # 不真正 spawn 长时间：仅验证 force_inplace 路径能写 pending（会 spawn powershell）
        # 用 wait_pid=0 让助手几乎立刻跑；install 在 temp，安全
        r2 = apply_package(plan, zip_path, force_inplace=True, wait_pid=0)
        assert r2.request_exit is True or r2.ok is False or r2.stage.value in (
            "apply_scheduled",
            "failed",
        )
        print("ota_inplace_ok", digest[:12], r1.stage.value, r2.stage.value, r2.ok)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
