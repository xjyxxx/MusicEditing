"""ctypes 直连 media_engine.dll（probe / thumbnail），避免短调用起 media_cli 进程。

加载失败时返回 None，由 MediaBridge 回退 subprocess。
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def find_media_engine_dll() -> Optional[Path]:
    root = _project_root()
    candidates = [
        root / "build_x64" / "bin" / "Release" / "media_engine.dll",
        root / "build_x64" / "bin" / "Debug" / "media_engine.dll",
        root / "build" / "bin" / "Release" / "media_engine.dll",
        root / "build" / "bin" / "Debug" / "media_engine.dll",
    ]
    # 与 media_cli 同目录（run_ui 常把 cwd 设到 bin）
    for p in candidates:
        if p.is_file():
            return p
    env = os.environ.get("MUSIC_ENGINE_DLL", "").strip()
    if env and os.path.isfile(env):
        return Path(env)
    return None


@dataclass
class CtypesProbeResult:
    width: int = 0
    height: int = 0
    duration_sec: float = 0.0
    fps: float = 0.0
    total_frames: int = 0
    codec_name: str = ""
    format_name: str = ""


class MediaEngineCtypes:
    """进程内单例：init 一次，反复 probe/thumbnail。"""

    def __init__(self, dll_path: Path):
        self._dll_path = dll_path
        self._lock = threading.RLock()
        # 先把 DLL 目录加入 DLL 搜索路径，便于找到 FFmpeg/OpenCV 依赖
        dll_dir = str(dll_path.parent)
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(dll_dir)
            except OSError:
                pass
        if dll_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")

        self._lib = ctypes.CDLL(str(dll_path))
        self._bind()
        if int(self._lib.media_engine_init()) != 0:
            err = self.last_error()
            raise RuntimeError(f"media_engine_init 失败: {err}")

    def _bind(self) -> None:
        lib = self._lib
        lib.media_engine_init.restype = ctypes.c_int
        lib.media_engine_shutdown.restype = None
        lib.media_engine_last_error.restype = ctypes.c_char_p
        lib.media_engine_ffmpeg_version.restype = ctypes.c_char_p

        lib.media_probe_video.argtypes = [
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int64),
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
        ]
        lib.media_probe_video.restype = ctypes.c_int

        lib.media_extract_thumbnail.argtypes = [
            ctypes.c_char_p,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.media_extract_thumbnail.restype = ctypes.c_int

        lib.media_decoder_hwaccel_name.restype = ctypes.c_char_p

    def last_error(self) -> str:
        try:
            p = self._lib.media_engine_last_error()
            if not p:
                return ""
            return p.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def ffmpeg_version(self) -> str:
        try:
            p = self._lib.media_engine_ffmpeg_version()
            if not p:
                return ""
            return p.decode("utf-8", errors="replace")
        except Exception:
            return ""

    def probe_video(self, file_path: str) -> CtypesProbeResult:
        path_b = os.fsencode(os.path.abspath(file_path))
        w = ctypes.c_int(0)
        h = ctypes.c_int(0)
        dur = ctypes.c_double(0.0)
        fps = ctypes.c_double(0.0)
        total = ctypes.c_int64(0)
        codec = ctypes.create_string_buffer(64)
        fmt = ctypes.create_string_buffer(64)
        with self._lock:
            ret = int(self._lib.media_probe_video(
                path_b,
                ctypes.byref(w), ctypes.byref(h),
                ctypes.byref(dur), ctypes.byref(fps), ctypes.byref(total),
                codec, 64, fmt, 64,
            ))
        if ret != 0:
            raise RuntimeError(self.last_error() or f"media_probe_video={ret}")
        return CtypesProbeResult(
            width=int(w.value),
            height=int(h.value),
            duration_sec=float(dur.value),
            fps=float(fps.value),
            total_frames=int(total.value),
            codec_name=codec.value.decode("utf-8", errors="replace"),
            format_name=fmt.value.decode("utf-8", errors="replace"),
        )

    def extract_thumbnail_ppm(
        self,
        file_path: str,
        timestamp_sec: float,
        output_ppm: str,
        *,
        max_width: int = 160,
        prefer_hw: bool = True,
    ) -> str:
        """探测 → 抽 RGB → 可选缩放 → 写 PPM。"""
        info = self.probe_video(file_path)
        w, h = int(info.width), int(info.height)
        if w <= 0 or h <= 0:
            raise RuntimeError("缩略图：无效分辨率")
        dur = float(info.duration_sec or 0.0)
        ts = max(0.0, float(timestamp_sec))
        if dur > 0:
            ts = min(ts, dur)

        buf_size = w * h * 3
        buf = (ctypes.c_ubyte * buf_size)()
        path_b = os.fsencode(os.path.abspath(file_path))
        with self._lock:
            ret = int(self._lib.media_extract_thumbnail(
                path_b, ctypes.c_double(ts), buf, buf_size, 1 if prefer_hw else 0,
            ))
        if ret != 0:
            raise RuntimeError(self.last_error() or f"media_extract_thumbnail={ret}")

        rgb = bytes(buf)
        ow, oh = w, h
        if max_width > 0 and w > max_width:
            ow = int(max_width)
            oh = max(1, h * max_width // w)
            rgb = _scale_rgb_nearest(rgb, w, h, ow, oh)

        out = Path(output_ppm)
        out.parent.mkdir(parents=True, exist_ok=True)
        _write_ppm(out, rgb, ow, oh)
        return str(out.resolve())


_ENGINE: Optional[MediaEngineCtypes] = None
_ENGINE_LOCK = threading.Lock()
_ENGINE_FAILED = False


def get_media_engine() -> Optional[MediaEngineCtypes]:
    """懒加载；失败则缓存失败状态，避免反复尝试。"""
    global _ENGINE, _ENGINE_FAILED
    if _ENGINE is not None:
        return _ENGINE
    if _ENGINE_FAILED:
        return None
    # 仅 x64 Python 加载 x64 DLL
    if sys.maxsize <= 2**32:
        _ENGINE_FAILED = True
        return None
    with _ENGINE_LOCK:
        if _ENGINE is not None:
            return _ENGINE
        if _ENGINE_FAILED:
            return None
        dll = find_media_engine_dll()
        if not dll:
            _ENGINE_FAILED = True
            return None
        try:
            _ENGINE = MediaEngineCtypes(dll)
            return _ENGINE
        except Exception:
            _ENGINE_FAILED = True
            return None


def ctypes_available() -> bool:
    return get_media_engine() is not None


def _scale_rgb_nearest(src: bytes, sw: int, sh: int, dw: int, dh: int) -> bytes:
    out = bytearray(dw * dh * 3)
    for y in range(dh):
        sy = min(sh - 1, y * sh // dh)
        for x in range(dw):
            sx = min(sw - 1, x * sw // dw)
            si = (sy * sw + sx) * 3
            di = (y * dw + x) * 3
            out[di:di + 3] = src[si:si + 3]
    return bytes(out)


def _write_ppm(path: Path, rgb: bytes, w: int, h: int) -> None:
    header = f"P6\n{w} {h}\n255\n".encode("ascii")
    expected = w * h * 3
    if len(rgb) < expected:
        raise RuntimeError("PPM 数据长度不足")
    with open(path, "wb") as f:
        f.write(header)
        f.write(rgb[:expected])
