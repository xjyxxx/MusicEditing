"""应用全局逻辑"""

from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Optional


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def load_app_config() -> dict[str, str]:
    """读取 client/resources/config/app.conf"""
    conf_path = _project_root() / "client" / "resources" / "config" / "app.conf"
    alt_paths = [
        _project_root() / "build_x64" / "bin" / "Release" / "resources" / "config" / "app.conf",
        _project_root() / "build" / "bin" / "Release" / "resources" / "config" / "app.conf",
    ]
    path = conf_path
    if not path.exists():
        for alt in alt_paths:
            if alt.exists():
                path = alt
                break
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
        self.opencv_filter = cfg.get("opencv_filter", "clahe")
        gpu_cfg = cfg.get("gpu_enabled", "true").strip().lower()
        want_gpu = gpu_cfg not in ("0", "false", "off", "no")
        self.prefer_hw_decode = want_gpu
        self.use_gpu = self.gpu_info["cuda_available"] and want_gpu
        if not self.vosk_model_dir:
            default_vosk = _project_root() / "models" / "vosk-model-small-cn-0.22"
            if default_vosk.is_dir():
                self.vosk_model_dir = str(default_vosk)
        self.lama_model_path = cfg.get("lama_model_path", "")
        if not self.lama_model_path:
            default_lama = _project_root() / "models" / "lama.onnx"
            if default_lama.is_file():
                self.lama_model_path = str(default_lama)
        # 网易云热评：直连默认；可选 NCM API / 外部脚本
        self.netease_api_base = cfg.get("netease_api_base", "")
        self.netease_hot_comments_script = cfg.get("netease_hot_comments_script", "")
        demo = cfg.get("netease_hot_comments_demo", "true").strip().lower()
        self.netease_hot_comments_demo = demo not in ("0", "false", "off", "no")

    def toggle_gpu(self, enabled: bool):
        if enabled and not self.gpu_info["cuda_available"]:
            return False
        self.use_gpu = enabled
        self.prefer_hw_decode = enabled
        return True
