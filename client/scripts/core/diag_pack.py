"""诊断包：收集 player / cli / ORT EP / Python 日志并打 zip。"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _docs() -> Path:
    from core.app_logger import log_dir

    return log_dir()


def collect_ort_ep_report() -> dict:
    """ONNX Runtime EP 与 CUDA 探测摘要。"""
    report: dict = {
        "import_ok": False,
        "providers": [],
        "cuda_ep": False,
        "message": "",
    }
    try:
        import onnxruntime as ort

        report["import_ok"] = True
        report["version"] = getattr(ort, "__version__", "")
        providers = list(ort.get_available_providers() or [])
        report["providers"] = providers
        report["cuda_ep"] = "CUDAExecutionProvider" in providers
        report["message"] = (
            "CUDA EP✓" if report["cuda_ep"] else "无 CUDA EP（超分/LaMa 将用 CPU）"
        )
    except Exception as e:
        report["message"] = f"onnxruntime 不可用: {e}"
    return report


def collect_engine_paths() -> dict:
    root = _project_root()
    bin_dir = root / "build_x64" / "bin" / "Release"
    items = {
        "media_cli": bin_dir / "media_cli.exe",
        "media_player": bin_dir / "media_player.exe",
        "media_engine": bin_dir / "media_engine.dll",
        "onnxruntime": bin_dir / "onnxruntime.dll",
    }
    return {k: {"path": str(p), "exists": p.is_file()} for k, p in items.items()}


def _cli_version() -> str:
    root = _project_root()
    cli = root / "build_x64" / "bin" / "Release" / "media_cli.exe"
    if not cli.is_file():
        return "media_cli.exe 缺失"
    try:
        env = os.environ.copy()
        env["PATH"] = str(cli.parent) + os.pathsep + env.get("PATH", "")
        proc = subprocess.run(
            [str(cli), "version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            cwd=str(cli.parent),
            env=env,
        )
        out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        return out[:500] or f"exit={proc.returncode}"
    except Exception as e:
        return f"version 失败: {e}"


def ensure_cli_log_env(env: Optional[dict] = None) -> dict:
    """给 media_cli 子进程写入 MUSIC_LOG_FILE。"""
    from core.app_logger import log_file_path

    e = env if env is not None else os.environ.copy()
    e.setdefault("MUSIC_LOG_FILE", str(log_file_path("media_cli")))
    e.setdefault("MUSIC_LOG_LEVEL", os.environ.get("MUSIC_LOG_LEVEL", "INFO"))
    return e


def list_diag_sources() -> List[Path]:
    """可能纳入诊断包的日志与快照文件。"""
    docs = _docs()
    names = [
        "log_MusicEditing.txt",
        "log_media_player.txt",
        "log_media_cli.txt",
        "log_VideoPlayer.txt",
        "log_PlayerBackend.txt",
        "log_SceneDetect.txt",
        "log_scenedetect.txt",
        "log_MediaBridge.txt",
        "ort_ep_report.json",
        "diag_snapshot.json",
    ]
    found: List[Path] = []
    for n in names:
        p = docs / n
        if p.is_file():
            found.append(p)
    # 其它 log_*.txt
    for p in sorted(docs.glob("log_*.txt")):
        if p not in found:
            found.append(p)
    return found


def write_snapshot(extra: Optional[dict] = None) -> Path:
    """写一份机器可读快照到 docs/diag_snapshot.json。"""
    docs = _docs()
    ort = collect_ort_ep_report()
    (docs / "ort_ep_report.json").write_text(
        json.dumps(ort, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    snap = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cwd": os.getcwd(),
        "project_root": str(_project_root()),
        "engine": collect_engine_paths(),
        "media_cli_version": _cli_version(),
        "ort": ort,
        "env": {
            "MUSIC_ORT_CUDA": os.environ.get("MUSIC_ORT_CUDA", ""),
            "MUSIC_UPSCALE_BACKEND": os.environ.get("MUSIC_UPSCALE_BACKEND", ""),
            "MUSIC_LOG_LEVEL": os.environ.get("MUSIC_LOG_LEVEL", ""),
        },
    }
    if extra:
        snap["extra"] = extra
    out = docs / "diag_snapshot.json"
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def pack_diagnostics(
    dest_zip: Optional[str] = None,
    *,
    extra: Optional[dict] = None,
) -> Tuple[str, List[str]]:
    """
    打包诊断 zip。返回 (zip路径, 纳入的文件名列表)。
    默认写到用户桌面或 docs/diagnostics/。
    """
    write_snapshot(extra=extra)
    sources = list_diag_sources()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if dest_zip:
        out = Path(dest_zip)
    else:
        desk = Path.home() / "Desktop"
        base = desk if desk.is_dir() else (_docs() / "diagnostics")
        base.mkdir(parents=True, exist_ok=True)
        out = base / f"MusicEditing_diag_{stamp}.zip"

    out.parent.mkdir(parents=True, exist_ok=True)
    names: List[str] = []
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sources:
            arc = p.name
            zf.write(p, arcname=arc)
            names.append(arc)
        # README
        readme = (
            "MusicEditing 诊断包\n"
            f"生成时间: {stamp}\n"
            "含：Python/player/cli 日志、ort_ep_report.json、diag_snapshot.json\n"
            "反馈问题时请附上本 zip。\n"
        )
        zf.writestr("README.txt", readme)
        names.append("README.txt")
    return str(out), names
