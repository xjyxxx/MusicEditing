"""启动依赖检测：模型 / GPU / yt-dlp / Cookie / 引擎 / 场景检测。"""

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
    action: str = ""  # bat 相对项目根，或 special:*
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
    def missing_any(self) -> List[DepItem]:
        return [i for i in self.items if not i.ok]

    @property
    def all_ok(self) -> bool:
        return all(i.ok for i in self.items if i.critical)

    def next_actions_summary(self) -> str:
        miss = self.missing_any
        if not miss:
            return "依赖看起来齐全，可以开始用了。"
        lines = ["建议优先处理："]
        for i, it in enumerate(miss[:5], 1):
            hint = it.detail.split("·")[0].strip() if it.detail else it.title
            lines.append(f"{i}. {it.title} — {hint}")
        return "\n".join(lines)


def _cookie_file_hint(path: str) -> tuple[bool, str]:
    """粗查 Netscape cookie 是否像可用文件。"""
    if not path or not os.path.isfile(path):
        return False, "未配置 · 抖音等站点请到下载页「Cookie…」导入 Netscape txt"
    try:
        raw = Path(path).read_text(encoding="utf-8", errors="replace")[:8000]
    except OSError:
        return False, f"无法读取：{path}"
    low = raw.lower()
    if "yt_dlp_cookies" in low or "[app]" in low or path.lower().endswith("app.conf"):
        return False, "选错了文件（像 app.conf）· 请用扩展导出的 cookies.txt"
    has_header = "# netscape" in low or "http" in low
    domains = []
    for d in ("douyin.com", "bilibili.com", "bilivideo.com", "kuaishou.com"):
        if d in low:
            domains.append(d.split(".")[0])
    if not has_header and "\t" not in raw:
        return False, "格式不像 Netscape Cookie · 请用 Get cookies.txt LOCALLY 重导"
    if domains:
        return True, f"{path} · 含 {'/'.join(domains)}"
    return True, f"{path} · 已配置（未识别到抖音/B站域名，部分站点仍可能失败）"


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
    use_gpu = bool(getattr(app, "use_gpu", False)) if app is not None else False
    gpu_detail = st.gpu_name
    if cuda and use_gpu:
        gpu_detail += " · 已开 GPU（超分/LaMa 试 CUDA EP；llama 需 Vulkan/CUDA 源码构建）"
    elif cuda and not use_gpu:
        gpu_detail += " · 已检测到卡但未开 GPU（个人中心打开）"
    else:
        gpu_detail += " · 无独显也能用（更慢）"
    st.items.append(DepItem(
        key="gpu",
        title="GPU / 硬解",
        ok=True,
        detail=gpu_detail,
        action="special:gpu",
        critical=False,
    ))

    # 引擎可执行文件（点了没反应常见原因）
    cli = root / "build_x64" / "bin" / "Release" / "media_cli.exe"
    player = root / "build_x64" / "bin" / "Release" / "media_player.exe"
    eng_ok = cli.is_file() and player.is_file()
    st.items.append(DepItem(
        key="engine",
        title="本地引擎 media_cli",
        ok=eng_ok,
        detail=(
            str(cli) if eng_ok
            else "缺失 · 请先运行 build_x64.bat / run_ui_x64.bat 编译，否则切片/超分会无响应"
        ),
        action="special:build",
        critical=True,
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
        detail=sr or "缺失 · AI 超分点了会提示；仍可用 OpenCV 快速",
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
        detail=vosk or "缺失 · 演讲金句会用人声段兜底（可下模型更准）",
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
        detail=yt_path or "缺失 · 「获取」会没反应/报错，请一键下载",
        action="scripts/download_yt_dlp.bat",
        critical=False,
    ))

    cookie_ok, cookie_detail = _cookie_file_hint(cookies)
    st.items.append(DepItem(
        key="cookie",
        title="下载 Cookie（抖音等）",
        ok=cookie_ok,
        detail=cookie_detail,
        action="special:cookie",
        critical=False,
    ))

    # 游戏高光场景库
    try:
        from core.scene_detect import scenedetect_available
        sd_ok = scenedetect_available()
    except Exception:
        sd_ok = False
    st.items.append(DepItem(
        key="scenedetect",
        title="游戏高光 PySceneDetect",
        ok=sd_ok,
        detail=(
            "已就绪 · 场景切点 + 语义打分"
            if sd_ok
            else "未安装 · 游戏高光会退回时间规则；可运行 install_scenedetect.bat"
        ),
        action="scripts/install_scenedetect.bat",
        critical=False,
    ))

    # LLM / gguf（可选）
    gguf = list((root / "models").glob("*.gguf")) if (root / "models").is_dir() else []
    st.items.append(DepItem(
        key="llm",
        title="本地 LLM（.gguf）",
        ok=bool(gguf),
        detail=(
            str(gguf[0]) if gguf
            else "未配置 · 演讲金句高级分析需 gguf；GPU 推荐 setup_llama_gpu.py vulkan"
        ),
        action="special:llm",
        critical=False,
    ))

    ge = root / "models" / "game_event.onnx"
    st.items.append(DepItem(
        key="game_event",
        title="游戏事件模型 game_event.onnx",
        ok=ge.is_file(),
        detail=(
            str(ge) if ge.is_file()
            else "可选 · 无模型时用 HUD 启发式；可运行 scripts/make_game_event_stub_onnx.py"
        ),
        action="special:llm",
        critical=False,
    ))

    # 照片图库可选依赖 / 地图资源（不阻塞开箱完成）
    heic_ok = False
    try:
        import pillow_heif  # noqa: F401

        heic_ok = True
    except ImportError:
        heic_ok = False
    st.items.append(DepItem(
        key="iphoto_heic",
        title="照片 HEIC（pillow-heif）",
        ok=heic_ok,
        detail=(
            "已就绪 · 可预览/导入 HEIC"
            if heic_ok
            else "可选 · 未装时 HEIC 可能无法预览：pip install -r client/scripts/requirements-iphoto.txt"
        ),
        action="",
        critical=False,
    ))
    maps_font = root / "third_party" / "iphoto" / "src" / "maps" / "font"
    font_ok = False
    if maps_font.is_dir():
        try:
            font_ok = any(maps_font.iterdir())
        except OSError:
            font_ok = False
    st.items.append(DepItem(
        key="iphoto_maps_font",
        title="地点地图字体 maps/font",
        ok=font_ok,
        detail=(
            str(maps_font) if font_ok
            else "可选 · 未补齐时地点地图仍可用，地名可能异常；见 third_party/iphoto/src/maps/ASSETS.md"
        ),
        action="",
        critical=False,
    ))

    return st


def should_show_setup_wizard(app=None) -> bool:
    from core.app_logic import load_app_config

    st = collect_setup_status(app)
    # media_cli 等关键缺失时强制再弹（即使用户点过完成）
    if st.missing_critical:
        return True
    cfg = load_app_config()
    if (cfg.get("setup_wizard_done") or "").strip().lower() in ("1", "true", "yes"):
        return False
    return True
