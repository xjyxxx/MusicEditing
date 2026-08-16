"""OTA 远程升级。

已实现：
  - 检查更新（update_check）→ 下载暂存 → SHA256 校验
  - 便携 zip：写 pending → 系统 PowerShell 助手等待退出 → 换目录 → 再拉起

配置（app.conf）:
  update_manifest_url=…
  ota_apply_enabled=false   # true 时下载后默认尝试半自动；UI 也可临时确认
  ota_staging_dir=          # 空则 %LOCALAPPDATA%/MusicEditing/ota

manifest 见 docs/examples/musicediting_update.example.json
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

from core.update_check import UpdateInfo


class PackageKind(str, Enum):
    UNKNOWN = "unknown"
    PORTABLE_ZIP = "portable_zip"
    INNO_SETUP = "inno_setup"
    SHARE_ZIP = "share_zip"


class ApplyMode(str, Enum):
    MANUAL_REPLACE = "manual_replace"
    INNO_SETUP = "inno_setup"
    INPLACE = "inplace"


class OtaStage(str, Enum):
    IDLE = "idle"
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    READY = "ready"
    APPLY_STUB = "apply_stub"
    APPLY_SCHEDULED = "apply_scheduled"
    FAILED = "failed"


@dataclass
class OtaManifest:
    remote_version: str
    package_url: str
    package_kind: PackageKind = PackageKind.UNKNOWN
    sha256: str = ""
    size_bytes: int = 0
    notes: str = ""
    apply_mode: ApplyMode = ApplyMode.MANUAL_REPLACE
    restart_required: bool = True
    channel: str = "stable"
    raw: dict = field(default_factory=dict)


@dataclass
class OtaDownloadResult:
    ok: bool
    path: Path | None = None
    stage: OtaStage = OtaStage.IDLE
    message: str = ""
    sha256_ok: bool | None = None


@dataclass
class OtaApplyResult:
    ok: bool
    stage: OtaStage
    message: str
    stub: bool = True
    package_path: Path | None = None
    """True：调用方应尽快退出进程，以便助手完成替换。"""
    request_exit: bool = False
    pending_path: Path | None = None


ProgressCb = Callable[[int, int], None]


def ota_apply_enabled() -> bool:
    env = (os.environ.get("MUSIC_OTA_APPLY") or "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    try:
        from core.app_logic import load_app_config

        v = (load_app_config().get("ota_apply_enabled") or "").strip().lower()
        return v in ("1", "true", "yes", "on")
    except Exception:
        return False


def staging_root() -> Path:
    try:
        from core.app_logic import load_app_config

        raw = (load_app_config().get("ota_staging_dir") or "").strip()
        if raw:
            return Path(raw).expanduser()
    except Exception:
        pass
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP") or str(Path.home())
    return Path(base) / "MusicEditing" / "ota"


def install_root() -> Path:
    """便携包根目录（含 MusicEditing.exe / runtime / client）。"""
    env = (os.environ.get("MUSIC_INSTALL_ROOT") or "").strip()
    if env and Path(env).is_dir():
        return Path(env).resolve()
    # client/scripts/core/ota_update.py → 上四级 = 包根（便携布局）
    here = Path(__file__).resolve()
    cand = here.parents[3]
    if (cand / "MusicEditing.exe").is_file() or (cand / "runtime").is_dir():
        return cand
    # 开发树：client/scripts/core → 仓库根
    if (here.parents[3] / "client").is_dir():
        return here.parents[3]
    return Path.cwd().resolve()


def pending_path(root: Path | None = None) -> Path:
    return (root or install_root()) / "pending_ota.json"


def helper_ps1_candidates() -> list[Path]:
    root = install_root()
    return [
        root / "scripts" / "ota_apply_helper.ps1",
        Path(__file__).resolve().parents[3] / "scripts" / "ota_apply_helper.ps1",
        staging_root() / "ota_apply_helper.ps1",
    ]


def ensure_helper_in_staging() -> Path:
    """把助手脚本拷到 LOCALAPPDATA，避免替换安装目录时删掉脚本。"""
    dest = staging_root() / "ota_apply_helper.ps1"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for src in helper_ps1_candidates():
        if src.is_file():
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
            return dest
    raise FileNotFoundError("未找到 ota_apply_helper.ps1")


def _guess_kind(url: str, explicit: str = "") -> PackageKind:
    e = (explicit or "").strip().lower()
    if e in ("portable_zip", "portable", "zip"):
        if "share" in (url or "").lower():
            return PackageKind.SHARE_ZIP
        return PackageKind.PORTABLE_ZIP
    if e in ("share_zip", "share"):
        return PackageKind.SHARE_ZIP
    if e in ("inno_setup", "setup", "installer", "exe"):
        return PackageKind.INNO_SETUP
    low = (url or "").lower()
    if low.endswith(".exe") or "setup" in low:
        return PackageKind.INNO_SETUP
    if "share" in low and low.endswith(".zip"):
        return PackageKind.SHARE_ZIP
    if low.endswith(".zip"):
        return PackageKind.PORTABLE_ZIP
    return PackageKind.UNKNOWN


def plan_from_update_info(info: UpdateInfo, *, manifest_extra: Optional[dict] = None) -> OtaManifest | None:
    if not info or not info.has_update or not (info.url or "").strip():
        return None
    extra = dict(manifest_extra or {})
    ota = extra.get("ota") if isinstance(extra.get("ota"), dict) else {}
    kind = _guess_kind(
        info.url,
        str(extra.get("package_kind") or extra.get("kind") or ""),
    )
    mode_raw = str(ota.get("apply_mode") or extra.get("apply_mode") or "manual_replace")
    try:
        mode = ApplyMode(mode_raw)
    except ValueError:
        mode = ApplyMode.MANUAL_REPLACE
    # zip 包默认可走 inplace；exe 默认 inno
    if mode == ApplyMode.MANUAL_REPLACE and kind in (
        PackageKind.PORTABLE_ZIP,
        PackageKind.SHARE_ZIP,
    ):
        # 保留 manifest 显式 manual；UI 可强制 inplace
        pass
    size = 0
    try:
        size = int(extra.get("size_bytes") or extra.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    return OtaManifest(
        remote_version=info.remote_version,
        package_url=info.url.strip(),
        package_kind=kind,
        sha256=str(extra.get("sha256") or extra.get("hash") or info.sha256 or "").strip().lower(),
        size_bytes=size or int(getattr(info, "size_bytes", 0) or 0),
        notes=info.notes or "",
        apply_mode=mode,
        restart_required=bool(ota.get("restart_required", True)),
        channel=str(extra.get("channel") or "stable"),
        raw=extra,
    )


def file_sha256(path: Path, *, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def download_package(
    plan: OtaManifest,
    *,
    progress: Optional[ProgressCb] = None,
    timeout: float = 120.0,
) -> OtaDownloadResult:
    if not plan.package_url:
        return OtaDownloadResult(False, stage=OtaStage.FAILED, message="缺少 package_url")
    root = staging_root() / (plan.remote_version or "unknown")
    root.mkdir(parents=True, exist_ok=True)
    name = plan.package_url.rstrip("/").rsplit("/", 1)[-1] or "update.bin"
    dest = root / name
    try:
        req = urllib.request.Request(
            plan.package_url,
            headers={"User-Agent": "MusicEditing-OTA/0.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = -1
            try:
                total = int(resp.headers.get("Content-Length") or -1)
            except ValueError:
                total = -1
            if plan.size_bytes > 0 and total < 0:
                total = plan.size_bytes
            received = 0
            tmp = dest.with_suffix(dest.suffix + ".part")
            with tmp.open("wb") as out:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    out.write(chunk)
                    received += len(chunk)
                    if progress:
                        progress(received, total)
            tmp.replace(dest)
    except Exception as e:
        return OtaDownloadResult(False, stage=OtaStage.FAILED, message=f"下载失败：{e}")

    sha_ok: bool | None = None
    if plan.sha256:
        try:
            got = file_sha256(dest)
            sha_ok = got.lower() == plan.sha256.lower()
            if not sha_ok:
                return OtaDownloadResult(
                    False,
                    path=dest,
                    stage=OtaStage.FAILED,
                    message=f"SHA256 不匹配\n期望 {plan.sha256}\n实际 {got}",
                    sha256_ok=False,
                )
        except Exception as e:
            return OtaDownloadResult(
                False, path=dest, stage=OtaStage.FAILED, message=f"校验失败：{e}"
            )

    return OtaDownloadResult(
        True,
        path=dest,
        stage=OtaStage.READY,
        message=f"已下载到：\n{dest}",
        sha256_ok=sha_ok,
    )


def find_payload_root(extract_dir: Path) -> Path:
    """zip 解压后定位含 MusicEditing.exe 的目录。"""
    exe = next(extract_dir.rglob("MusicEditing.exe"), None)
    if exe is not None:
        return exe.parent
    # 单顶层目录
    kids = [p for p in extract_dir.iterdir() if p.is_dir()]
    if len(kids) == 1:
        return kids[0]
    return extract_dir


def extract_package(package_path: Path, *, version: str) -> Path:
    """解压 zip 到暂存 extracted/，返回 payload 根。"""
    path = Path(package_path)
    out = staging_root() / (version or "unknown") / "extracted"
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            zf.extractall(out)
        return find_payload_root(out)
    raise ValueError(f"暂不支持解压: {path.suffix}")


def write_pending(
    *,
    install: Path,
    source_dir: Path | None,
    package_zip: Path | None,
    version: str,
    wait_pid: int,
) -> Path:
    pending = pending_path(install)
    relaunch = install / "MusicEditing.exe"
    data = {
        "version": version,
        "install_root": str(install.resolve()),
        "source_dir": str(source_dir.resolve()) if source_dir else "",
        "package_zip": str(package_zip.resolve()) if package_zip else "",
        "relaunch_exe": str(relaunch.resolve()),
        "wait_pid": int(wait_pid),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return pending


def spawn_apply_helper(pending: Path) -> None:
    helper = ensure_helper_in_staging()
    # 独立控制台外隐藏窗口；不随本进程退出
    flags = 0
    if sys.platform == "win32":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
    cmd = [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(helper),
        "-PendingPath",
        str(pending),
    ]
    subprocess.Popen(
        cmd,
        cwd=str(staging_root()),
        creationflags=flags,
        close_fds=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


def schedule_inplace_apply(
    plan: OtaManifest,
    package_path: Path,
    *,
    wait_pid: int | None = None,
    extract_now: bool = True,
) -> OtaApplyResult:
    """解压（可选）+ 写 pending + 拉起助手；调用方随后应退出。"""
    path = Path(package_path)
    if not path.is_file():
        return OtaApplyResult(
            False, OtaStage.FAILED, f"包不存在：{path}", stub=False, package_path=path
        )
    if plan.package_kind not in (PackageKind.PORTABLE_ZIP, PackageKind.SHARE_ZIP, PackageKind.UNKNOWN):
        if path.suffix.lower() != ".zip":
            return OtaApplyResult(
                False,
                OtaStage.FAILED,
                "inplace 仅支持便携 zip；安装包请手动运行 Setup。",
                stub=False,
                package_path=path,
            )

    install = install_root()
    if not (install / "MusicEditing.exe").is_file() and not (install / "runtime").is_dir():
        return OtaApplyResult(
            False,
            OtaStage.FAILED,
            f"未识别便携安装根目录：\n{install}\n"
            "请从打包后的 MusicEditing.exe 启动后再升级。",
            stub=False,
            package_path=path,
        )

    source_dir: Path | None = None
    try:
        if extract_now and path.suffix.lower() == ".zip":
            source_dir = extract_package(path, version=plan.remote_version)
    except Exception as e:
        return OtaApplyResult(
            False, OtaStage.FAILED, f"解压失败：{e}", stub=False, package_path=path
        )

    pid = int(wait_pid if wait_pid is not None else os.getpid())
    try:
        pending = write_pending(
            install=install,
            source_dir=source_dir,
            package_zip=path if source_dir is None else None,
            version=plan.remote_version,
            wait_pid=pid,
        )
        spawn_apply_helper(pending)
    except Exception as e:
        return OtaApplyResult(
            False, OtaStage.FAILED, f"调度助手失败：{e}", stub=False, package_path=path
        )

    return OtaApplyResult(
        True,
        OtaStage.APPLY_SCHEDULED,
        "已调度自动升级：本程序退出后将替换便携目录并重新启动。\n"
        f"安装目录：{install}\n"
        f"版本：{plan.remote_version}\n"
        f"日志：{staging_root() / 'apply_helper.log'}",
        stub=False,
        package_path=path,
        request_exit=True,
        pending_path=pending,
    )


def apply_package(
    plan: OtaManifest,
    package_path: Path,
    *,
    force_inplace: bool = False,
    wait_pid: int | None = None,
) -> OtaApplyResult:
    """应用更新。

    - zip + (force_inplace | apply_mode=inplace | ota_apply_enabled)：调度自动替换
    - inno_setup：提示运行安装包（可 ShellExecute 预留）
    - 其它：手动指引
    """
    path = Path(package_path)
    if not path.is_file():
        return OtaApplyResult(
            False, OtaStage.FAILED, f"包不存在：{path}", stub=True, package_path=path
        )

    # 仅当 UI 明确 force_inplace（用户点了「立即升级」）才调度替换，避免误触
    if force_inplace and path.suffix.lower() == ".zip":
        return schedule_inplace_apply(plan, path, wait_pid=wait_pid)

    if force_inplace and (
        plan.package_kind == PackageKind.INNO_SETUP or path.suffix.lower() == ".exe"
    ):
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
            return OtaApplyResult(
                True,
                OtaStage.APPLY_SCHEDULED,
                "已启动安装包，请按向导完成；完成后重新打开本程序。",
                stub=False,
                package_path=path,
                request_exit=True,
            )
        except Exception as e:
            return OtaApplyResult(
                False,
                OtaStage.FAILED,
                f"无法启动安装包：{e}\n\n{_manual_tip(plan, path)}",
                stub=True,
                package_path=path,
            )

    tip = _manual_tip(plan, path)
    return OtaApplyResult(
        True,
        OtaStage.APPLY_STUB,
        "包已下载。可在对话框选择「立即升级并退出」，或按下列步骤手动覆盖。\n\n" + tip,
        stub=True,
        package_path=path,
    )


def _manual_tip(plan: OtaManifest, path: Path) -> str:
    if plan.package_kind in (PackageKind.PORTABLE_ZIP, PackageKind.SHARE_ZIP) or path.suffix.lower() == ".zip":
        return (
            f"1. 退出 MusicEditing\n"
            f"2. 解压\n   {path}\n"
            f"3. 用新目录覆盖当前便携目录（或换新文件夹打开）\n"
            f"4. 重新双击 MusicEditing.exe"
        )
    if plan.package_kind == PackageKind.INNO_SETUP or path.suffix.lower() == ".exe":
        return (
            f"1. 退出 MusicEditing\n"
            f"2. 运行安装包\n   {path}\n"
            f"3. 按向导完成安装后重新打开"
        )
    return f"包路径：{path}\n请按发布说明手动升级。"


def clear_staging(version: str | None = None) -> None:
    root = staging_root()
    target = root / version if version else root
    if target.is_dir():
        shutil.rmtree(target, ignore_errors=True)


def resume_pending_if_any() -> str | None:
    """启动时：若存在 pending 且助手可能未跑完，提示路径（不自动强行替换）。"""
    p = pending_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return (
            f"检测到未完成的 OTA（{data.get('version', '?')}）。\n"
            f"若升级中断，可删除 {p} 后重试，或查看\n"
            f"{staging_root() / 'apply_helper.log'}"
        )
    except Exception:
        return f"检测到 pending_ota.json：{p}"
