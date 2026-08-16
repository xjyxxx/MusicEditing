#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OTA 打磨冒烟：sha 强制、Zip Slip、pending、取消下载。"""

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
    OtaManifest,
    PackageKind,
    apply_package,
    download_package,
    extract_package,
    file_sha256,
    plan_from_update_info,
    safe_extract_zip,
    write_pending,
)
from core.update_check import UpdateInfo  # noqa: E402


def _plan(**kw) -> OtaManifest:
    base = dict(
        remote_version="0.2.0",
        package_url="https://cdn.example.com/pkg.zip",
        package_kind=PackageKind.SHARE_ZIP,
        apply_mode=ApplyMode.INPLACE,
    )
    base.update(kw)
    return OtaManifest(**base)


def main() -> int:
    # 1) 无 sha256 默认拒绝
    os.environ.pop("MUSIC_OTA_ALLOW_NO_HASH", None)
    r = download_package(_plan(sha256=""), require_sha256=True)
    assert not r.ok and "sha256" in r.message.lower(), r.message
    print("OK require_sha256")

    # 2) Zip Slip 拒绝
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        evil = td_path / "evil.zip"
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("../outside.txt", "nope")
            zf.writestr("ok/MusicEditing.exe", b"MZ")
        out = td_path / "extracted"
        out.mkdir()
        try:
            with zipfile.ZipFile(evil, "r") as zf:
                safe_extract_zip(zf, out)
            raise AssertionError("Zip Slip should fail")
        except ValueError as e:
            assert "Zip Slip" in str(e)
        print("OK zip_slip")

    # 3) 正常解压 + pending
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        payload = td_path / "MusicEditing_Share_0.2.0"
        payload.mkdir()
        (payload / "MusicEditing.exe").write_bytes(b"MZ-fake")
        (payload / "runtime").mkdir()
        zip_path = td_path / "pkg.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(payload / "MusicEditing.exe", "MusicEditing_Share_0.2.0/MusicEditing.exe")
            zf.writestr("MusicEditing_Share_0.2.0/runtime/.keep", "")

        digest = file_sha256(zip_path)
        os.environ["MUSIC_INSTALL_ROOT"] = str(td_path / "install")
        install = Path(os.environ["MUSIC_INSTALL_ROOT"])
        install.mkdir()
        (install / "MusicEditing.exe").write_bytes(b"old")
        (install / "runtime").mkdir()

        # redirect staging via env-like: monkey patch staging by setting LOCALAPPDATA
        os.environ["LOCALAPPDATA"] = str(td_path / "la")
        root = extract_package(zip_path, version="0.2.0")
        assert (root / "MusicEditing.exe").is_file()

        pending = write_pending(
            install=install,
            source_dir=root,
            package_zip=None,
            version="0.2.0",
            wait_pid=0,
        )
        assert json.loads(pending.read_text(encoding="utf-8"))["version"] == "0.2.0"

        info = UpdateInfo(
            configured=True,
            has_update=True,
            local_version="0.1.0",
            remote_version="0.2.0",
            url="https://cdn.example.com/pkg.zip",
            sha256=digest,
            package_kind="share_zip",
            landing_url="https://cdn.example.com/download.html",
            manifest_extra={"sha256": digest, "package_kind": "share_zip", "ota": {"apply_mode": "inplace"}},
        )
        plan = plan_from_update_info(info, manifest_extra=info.manifest_extra)
        assert plan is not None and plan.sha256 == digest

        r1 = apply_package(plan, zip_path, force_inplace=False)
        assert r1.stub is True

        # 取消：abort 立即返回
        aborted = download_package(
            _plan(sha256=digest, package_url="http://127.0.0.1:9/nope.zip"),
            abort=lambda: True,
            require_sha256=True,
            timeout=2.0,
        )
        assert not aborted.ok and "取消" in aborted.message
        print("OK abort_before_download")

        print("ota_polish_ok", digest[:12], r1.stage.value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
