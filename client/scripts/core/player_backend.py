"""C++ media_player.exe 子进程后端（FFmpeg 解码，Python 拉帧显示）"""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.app_logger import media_player_log_path, setup_logging

log = setup_logging("PlayerBackend", os.environ.get("MUSIC_LOG_LEVEL", "INFO"))


def _find_player_exe() -> Path:
    root = Path(__file__).resolve().parent.parent.parent.parent
    candidates = [
        root / "build_x64" / "bin" / "Release" / "media_player.exe",
        root / "build_x64" / "bin" / "Debug" / "media_player.exe",
        root / "build" / "bin" / "Release" / "media_player.exe",
        root / "build" / "bin" / "Debug" / "media_player.exe",
        Path.cwd() / "build_x64" / "bin" / "Release" / "media_player.exe",
        Path.cwd() / "build" / "bin" / "Release" / "media_player.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "未找到 media_player.exe，请先运行 .\\build_x64.bat 或 .\\build.bat 编译"
    )


@dataclass
class PlayerInfo:
    duration_sec: float = 0.0
    fps: float = 25.0
    width: int = 0
    height: int = 0
    has_audio: bool = False
    hw_decode: bool = False
    hw_name: str = "cpu"


@dataclass
class FrameStats:
    skipped: int = 0
    decode_ms: int = 0
    hw_xfer: bool = False
    from_prefetch: bool = False


class PlayerBackend:
    """与 media_player.exe  stdin/stdout 通信"""

    def __init__(self):
        self._exe = _find_player_exe()
        self._proc: Optional[subprocess.Popen] = None
        self._stderr_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._info = PlayerInfo()
        self._hwaccel_preferred = False
        self._apply_filter_on_next = True
        self._last_stats = FrameStats()
        self._temp_dir = tempfile.mkdtemp(prefix="me_player_")
        self._frame_path = os.path.join(self._temp_dir, "frame.rgb")
        log.info("PlayerBackend 初始化 exe=%s frame=%s", self._exe, self._frame_path)

    def _drain_stderr(self, proc: subprocess.Popen):
        if not proc.stderr:
            return
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                log.debug("[media_player] %s", line)

    def _read_rgb_file(self, w: int, h: int) -> bytes:
        expected = w * h * 3
        with open(self._frame_path, "rb") as fp:
            data = fp.read(expected)
        if len(data) != expected:
            raise RuntimeError(f"帧数据不足 {len(data)}/{expected}")
        return data

    def _ensure_running(self):
        if self._proc and self._proc.poll() is None:
            return
        env = os.environ.copy()
        exe_dir = str(self._exe.parent)
        env["PATH"] = exe_dir + os.pathsep + env.get("PATH", "")
        env["MUSIC_LOG_FILE"] = media_player_log_path()
        env.setdefault("MUSIC_LOG_LEVEL", os.environ.get("MUSIC_LOG_LEVEL", "INFO"))
        self._proc = subprocess.Popen(
            [str(self._exe)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=exe_dir,
            bufsize=1,
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, args=(self._proc,), daemon=True
        )
        self._stderr_thread.start()
        log.info("media_player 已启动 pid=%s", self._proc.pid)

    def _restart(self):
        with self._lock:
            if self._proc and self._proc.poll() is None:
                try:
                    if self._proc.stdin:
                        self._proc.stdin.write("QUIT\n")
                        self._proc.stdin.flush()
                    self._proc.wait(timeout=1)
                except Exception:
                    pass
                try:
                    self._proc.terminate()
                    self._proc.wait(timeout=1)
                except Exception:
                    pass
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def _send(self, cmd: str) -> str:
        with self._lock:
            self._ensure_running()
            assert self._proc and self._proc.stdin and self._proc.stdout
            log.debug("IPC >> %s", cmd)
            self._proc.stdin.write(cmd + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
            if not line:
                self._proc = None
                log.error("media_player 无响应 cmd=%s", cmd)
                raise RuntimeError("media_player 无响应，请关闭 UI 后重新运行 run_ui.bat")
            resp = line.strip()
            log.debug("IPC << %s", resp)
            return resp

    def _decode_frame(
        self,
        min_ts: float,
        apply_filter: bool,
    ) -> Optional[tuple[float, bytes, int, int]]:
        min_arg = min_ts if min_ts >= 0 else -1
        resp = self._send(
            f"NEXT {self._frame_path} {min_arg} {1 if apply_filter else 0}"
        )
        if resp == "FRAME_EOF":
            return None
        if resp.startswith("ERROR"):
            raise RuntimeError(resp)
        if not resp.startswith("FRAME_OK"):
            return None

        ts = 0.0
        w = self._info.width
        h = self._info.height
        stats = FrameStats()
        for token in resp.split():
            if token.startswith("timestamp="):
                ts = float(token.split("=", 1)[1])
            elif token.startswith("width="):
                w = int(token.split("=", 1)[1])
            elif token.startswith("height="):
                h = int(token.split("=", 1)[1])
            elif token.startswith("skipped="):
                stats.skipped = int(token.split("=", 1)[1])
            elif token.startswith("decode_ms="):
                stats.decode_ms = int(token.split("=", 1)[1])
            elif token.startswith("hw_xfer="):
                stats.hw_xfer = int(token.split("=", 1)[1]) != 0
        stats.from_prefetch = False
        self._last_stats = stats

        if stats.decode_ms > 35 or stats.skipped > 2:
            log.debug(
                "FRAME ts=%.3f ms=%d skipped=%d hw=%s filter=%s",
                ts, stats.decode_ms, stats.skipped, stats.hw_xfer, apply_filter,
            )

        data = self._read_rgb_file(w, h)
        return ts, data, w, h

    def set_hwaccel(self, enabled: bool):
        self._hwaccel_preferred = enabled
        try:
            self._send(f"HWACCEL {'on' if enabled else 'off'}")
        except RuntimeError as e:
            log.warning("HWACCEL 失败: %s", e)

    def set_filter(self, mode: str):
        resp = self._send(f"FILTER {mode}")
        if resp.startswith("ERROR"):
            raise RuntimeError(resp)

    def set_playback_filter(self, enabled: bool):
        self._apply_filter_on_next = enabled

    def set_playback_scale(self, width: int, height: int):
        try:
            resp = self._send(f"SCALE {width} {height}")
            if resp.startswith("ERROR"):
                log.warning("SCALE 失败: %s", resp)
            else:
                log.info("播放缩放 %dx%d", width, height)
        except RuntimeError as e:
            log.warning("SCALE 失败: %s", e)

    def open(self, video_path: str) -> PlayerInfo:
        self._restart()
        if self._hwaccel_preferred:
            try:
                self._send("HWACCEL on")
            except RuntimeError:
                pass
        path = os.path.abspath(video_path)
        log.info("OPEN %s hw=%s", path, self._hwaccel_preferred)
        resp = self._send(f"OPEN {path}")
        if resp.startswith("ERROR"):
            log.error("OPEN 失败: %s", resp)
            raise RuntimeError(resp)
        if not resp.startswith("OPEN_OK"):
            raise RuntimeError(f"打开失败: {resp}")

        info = PlayerInfo()
        for part in resp.split():
            if "=" in part:
                k, v = part.split("=", 1)
                if k == "duration":
                    info.duration_sec = float(v)
                elif k == "fps":
                    info.fps = float(v)
                elif k == "width":
                    info.width = int(v)
                elif k == "height":
                    info.height = int(v)
                elif k == "audio":
                    info.has_audio = int(v) != 0
                elif k == "hw":
                    info.hw_decode = int(v) != 0
                elif k == "hw_name":
                    info.hw_name = v
        self._info = info
        log.info(
            "OPEN_OK %dx%d fps=%.2f hw=%s(%s)",
            info.width, info.height, info.fps, info.hw_decode, info.hw_name,
        )
        return info

    def seek(self, sec: float):
        log.info("SEEK %.3f", sec)
        resp = self._send(f"SEEK {sec}")
        if resp.startswith("ERROR"):
            raise RuntimeError(resp)

    def pause(self):
        self._send("PAUSE")

    def resume(self):
        self._send("RESUME")

    def next_frame(
        self,
        min_ts: float | None = None,
        apply_filter: bool | None = None,
    ) -> Optional[tuple[float, bytes, int, int]]:
        use_filter = self._apply_filter_on_next if apply_filter is None else apply_filter
        min_arg = -1.0 if min_ts is None else float(min_ts)
        return self._decode_frame(min_arg, use_filter)

    @property
    def last_frame_stats(self) -> FrameStats:
        return self._last_stats

    def close(self):
        self.shutdown()

    def shutdown(self):
        log.info("PlayerBackend shutdown")
        self._restart()

    @property
    def info(self) -> PlayerInfo:
        return self._info

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
