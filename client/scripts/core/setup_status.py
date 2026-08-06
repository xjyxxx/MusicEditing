"""启动依赖检测：模型 / GPU / yt-dlp / Cookie。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


@dataclass
class DepItem:
    key: str
    title: str
    ok: bool
    detail: str = ""
    action: str = ""  # bat 相对项目根，或 special:cookie / special:gpu
    critical: bool = False


@dataclass
class SetupStatus:
    items: List[DepItem] = field(default_factory=list)
    gpu_name: str = "CPU 模式"
    cuda_available: bool = False

    @property
    def missing_critical(self) -> List[DepItem]:
        return [i for i in self.items if i.critical and not i.ok]

    @property
    def all_ok(self) -> bool:
        return all(i.ok for i in self.items if i.critical)


def collect_setup_status(app=None) -> SetupStatus:
    """汇总依赖状态。app 可为 AppLogic。"""
    root = _project_root()
    st = SetupStatus()

    cuda = False
    gpu_name = "CPU 模式"
    if app is not None:
        info = getattr(app, "gpu_info", None) or {}
        cuda = bool(info.get("cuda_available"))
        gpu_name = str(getattr(app, "use_gpu", False) and info.get("name") or gpu_name)
        if cuda and info.get("name"):
            gpu_name = str(info.get("name"))
        st.cuda_available = cuda
        st.gpu_name = gpu_name if cuda else "未检测到 NVIDIA（将用 CPU）"
    st.items.append(DepItem(
        key="gpu",
        title="GPU / 硬解",
        ok=True,  # 无 GPU 也可运行，不算阻断
        detail=st.gpu_name + (" · 个人中心可开关" if True else ""),
        action="special:gpu",
        critical=False,
    ))

    sr = ""
    lama = ""
    vosk = ""
    cookies = ""
    if app is not None:
        sr = getattr(app, "realesrgan_model_path", "") or ""
        lama = getattr(app, "lama_model_path", "") or ""
        vosk = getattr(app, "vosk_model_dir", "") or ""
        cookies = getattr(app, "yt_dlp_cookies_file", "") or ""
    if not sr:
        p = root / "models" / "realesr-general-x4v3.onnx"
        sr = str(p) if p.is_file() else ""
    if not lama:
        p = root / "models" / "lama.onnx"
        lama = str(p) if p.is_file() else ""
    if not vosk:
        p = root / "models" / "vosk-model-small-cn-0.22"
        vosk = str(p) if p.is_dir() else ""

    st.items.append(DepItem(
        key="realesrgan",
        title="超分模型 Real-ESRGAN",
        ok=bool(sr and os.path.isfile(sr)),
        detail=sr or "缺失 · AI 超分不可用（仍可用 OpenCV 快速）",
        action="scripts/download_realesrgan_model.bat",
        critical=False,
    ))
    st.items.append(DepItem(
        key="lama",
        title="去水印模型 LaMa",
        ok=bool(lama and os.path.isfile(lama)),
        detail=lama or "缺失 · 精修不可用（仍可用快速 OpenCV）",
        action="scripts/download_lama_model.bat",
        critical=False,
    ))
    st.items.append(DepItem(
        key="vosk",
        title="语音识别 Vosk",
        ok=bool(vosk and os.path.isdir(vosk)),
        detail=vosk or "缺失 · 演讲金句用人声段兜底",
        action="scripts/download_vosk_model.bat",
        critical=False,
    ))

    yt_ok = False
    yt_path = ""
    for p in (
        root / "third_party" / "yt-dlp" / "yt-dlp.exe",
        root / "build_x64" / "bin" / "Release" / "yt-dlp.exe",
    ):
        if p.is_file():
            yt_ok = True
            yt_path = str(p)
            break
    st.items.append(DepItem(
        key="ytdlp",
        title="链接下载 yt-dlp",
        ok=yt_ok,
        detail=yt_path or "缺失 · 无法链接下载",
        action="scripts/download_yt_dlp.bat",
        critical=False,
    ))

    cookie_ok = bool(cookies and os.path.isfile(cookies))
    st.items.append(DepItem(
        key="cookie",
        title="下载 Cookie（抖音等）",
        ok=cookie_ok,
        detail=cookies if cookie_ok else "未配置 · 部分站点需在下载页「Cookie…」导入",
        action="special:cookie",
        critical=False,
    ))

    return st


def should_show_setup_wizard(app=None) -> bool:
    from core.app_logic import load_app_config

    cfg = load_app_config()
    if (cfg.get("setup_wizard_done") or "").strip().lower() in ("1", "true", "yes"):
        return False
    return True
