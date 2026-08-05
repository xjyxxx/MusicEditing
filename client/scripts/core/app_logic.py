"""应用全局逻辑"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Optional


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def app_config_path() -> Path:
    """解析实际使用的 app.conf 路径（与 load_app_config 一致）。"""
    conf_path = _project_root() / "client" / "resources" / "config" / "app.conf"
    alt_paths = [
        _project_root() / "build_x64" / "bin" / "Release" / "resources" / "config" / "app.conf",
        _project_root() / "build" / "bin" / "Release" / "resources" / "config" / "app.conf",
    ]
    if conf_path.exists():
        return conf_path
    for alt in alt_paths:
        if alt.exists():
            return alt
    return conf_path


def load_app_config() -> dict[str, str]:
    """读取 client/resources/config/app.conf"""
    path = app_config_path()
    cfg: dict[str, str] = {}
    if not path.exists():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def update_app_config_value(key: str, value: str) -> Path:
    """更新 app.conf 中单个键，保留注释与其它行；文件不存在则创建。"""
    key = (key or "").strip()
    if not key:
        raise ValueError("配置键为空")
    path = app_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    new_line = f"{key}={value}"
    found = False
    out: list[str] = []
    for line in lines:
        raw = line.strip()
        if raw and not raw.startswith("#") and not raw.startswith(";") and "=" in raw:
            k, _ = raw.split("=", 1)
            if k.strip() == key:
                out.append(new_line)
                found = True
                continue
        out.append(line)
    if not found:
        if out and out[-1].strip():
            out.append("")
        out.append(new_line)
    text = "\n".join(out)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
    return path


def looks_like_netscape_cookies(path: str) -> tuple[bool, str]:
    """粗检是否为 Netscape cookies.txt（避免误选 app.conf / 空文件）。"""
    p = Path(path or "")
    if not p.is_file():
        return False, "文件不存在"
    # 禁止把本应用配置当成 Cookie
    try:
        if p.resolve() == app_config_path().resolve():
            return False, "不能选择 app.conf；请选择扩展导出的 cookies.txt"
    except OSError:
        pass
    name = p.name.lower()
    if name in {"app.conf", "app.config", "settings.ini", "config.ini"}:
        return False, f"「{p.name}」不是 Cookie 文件，请选择 cookies.txt"
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")[:65536]
    except OSError as e:
        return False, f"无法读取：{e}"
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return False, "文件为空"
    # Netscape 数据行：domain \\t flag \\t path \\t secure \\t expiry \\t name \\t value
    data_rows = 0
    douyin_rows = 0
    for ln in lines:
        if ln.startswith("#"):
            continue
        parts = ln.split("\t")
        if len(parts) >= 7 and ("." in parts[0] or parts[0].startswith("#HttpOnly_")):
            data_rows += 1
            dom = parts[0].lower()
            if "douyin" in dom or "iesdouyin" in dom:
                douyin_rows += 1
    if data_rows < 1:
        return False, (
            "Cookie 文件里没有有效条目（只有文件头也算无效）。\n"
            "请先在浏览器打开 douyin.com，再用扩展 Export 导出后选择该文件。"
        )
    # 抖音建议有站点 Cookie；没有也不拦死（可能用于其它站）
    if douyin_rows == 0 and data_rows > 0:
        return True, "warn_no_douyin"
    return True, ""


def detect_gpu_info() -> dict:
    """检测 GPU 信息，优先尝试 nvidia-smi"""
    info = {
        "available": False,
        "name": "CPU 模式",
        "cuda_available": False,
        "message": "未检测到 NVIDIA GPU，当前为 CPU 模式",
    }

    if platform.system() != "Windows":
        return info

    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            info["available"] = True
            info["name"] = result.stdout.strip().split("\n")[0]
            info["cuda_available"] = True
            info["message"] = f"已检测到 GPU: {info['name']}"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return info


class AppLogic:
    """应用级业务逻辑单例"""

    _instance: Optional["AppLogic"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.gpu_info = detect_gpu_info()
        self.prefer_hw_decode = True
        self.use_gpu = self.gpu_info["cuda_available"]
        self.auth_type = "试用版"
        self.version = "0.1.0"
        self.output_dir = ""

        cfg = load_app_config()
        self.llm_model_path = cfg.get("llm_model_path", "")
        self.vosk_model_dir = cfg.get("vosk_model_dir", "")
        from core.live_subtitle import LiveSubtitleConfig
        self.live_subtitle_config = LiveSubtitleConfig.from_mapping(cfg)
        self.opencv_filter = cfg.get("opencv_filter", "clahe")
        self.opencv_filter_device = cfg.get("opencv_filter_device", "auto")
        gpu_cfg = cfg.get("gpu_enabled", "true").strip().lower()
        want_gpu = gpu_cfg not in ("0", "false", "off", "no")
        self.prefer_hw_decode = want_gpu
        self.use_gpu = self.gpu_info["cuda_available"] and want_gpu
        # 解析并校验 Vosk 目录（避免空串/「.」被当成模型路径）
        try:
            from core.asr_engine import resolve_vosk_model_dir, is_vosk_model_dir
            resolved = resolve_vosk_model_dir(self.vosk_model_dir or None)
            self.vosk_model_dir = str(resolved) if is_vosk_model_dir(resolved) else ""
        except Exception:
            if not self.vosk_model_dir:
                default_vosk = _project_root() / "models" / "vosk-model-small-cn-0.22"
                self.vosk_model_dir = str(default_vosk) if default_vosk.is_dir() else ""
        self.lama_model_path = cfg.get("lama_model_path", "")
        if not self.lama_model_path:
            default_lama = _project_root() / "models" / "lama.onnx"
            if default_lama.is_file():
                self.lama_model_path = str(default_lama)
        self.realesrgan_model_path = cfg.get("realesrgan_model_path", "")
        if not self.realesrgan_model_path:
            default_sr = _project_root() / "models" / "realesr-general-x4v3.onnx"
            if default_sr.is_file():
                self.realesrgan_model_path = str(default_sr)
        # 网易云热评：直连默认；可选 NCM API / 外部脚本
        self.netease_api_base = cfg.get("netease_api_base", "")
        self.netease_hot_comments_script = cfg.get("netease_hot_comments_script", "")
        demo = cfg.get("netease_hot_comments_demo", "true").strip().lower()
        self.netease_hot_comments_demo = demo not in ("0", "false", "off", "no")
        self.yt_dlp_cookies_from_browser = (
            cfg.get("yt_dlp_cookies_from_browser", "") or ""
        ).strip()
        self.yt_dlp_cookies_file = (cfg.get("yt_dlp_cookies_file", "") or "").strip()
        self._yt_cookies_warn = ""
        # 启动时清掉误选的配置文件路径，避免一直探测失败
        if self.yt_dlp_cookies_file:
            ok, reason = looks_like_netscape_cookies(self.yt_dlp_cookies_file)
            if not ok:
                self.yt_dlp_cookies_file = ""
                try:
                    update_app_config_value("yt_dlp_cookies_file", "")
                except Exception:
                    pass
            else:
                self._yt_cookies_warn = reason if reason.startswith("warn_") else ""

    def set_yt_dlp_cookies_file(self, path: str) -> str:
        """设置 Netscape cookies.txt 路径并写入 app.conf；空串表示清除。"""
        p = (path or "").strip()
        if p:
            if not Path(p).is_file():
                raise FileNotFoundError(f"Cookie 文件不存在：{p}")
            ok, reason = looks_like_netscape_cookies(p)
            if not ok:
                raise ValueError(reason or "不是有效的 Netscape cookies.txt")
            self._yt_cookies_warn = reason if reason.startswith("warn_") else ""
        else:
            self._yt_cookies_warn = ""
        self.yt_dlp_cookies_file = p
        update_app_config_value("yt_dlp_cookies_file", p)
        return p

    def toggle_gpu(self, enabled: bool):
        if enabled and not self.gpu_info["cuda_available"]:
            return False
        self.use_gpu = enabled
        self.prefer_hw_decode = enabled
        return True
