"""C++ media_player.exe 子进程后端（FFmpeg 解码，共享内存拉帧）"""

from __future__ import annotations

import mmap
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from core.app_logger import media_player_log_path, setup_logging

log = setup_logging("PlayerBackend", os.environ.get("MUSIC_LOG_LEVEL", "INFO"))

# 预览帧上限（4K RGB24）；SCALE 后通常远小于此
_SHM_CAPACITY = 3840 * 2160 * 3


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


@dataclass
class _PrefetchSlot:
    ts: float
    data: bytes
    w: int
    h: int
    stats: FrameStats


class PlayerBackend:
    """与 media_player.exe  stdin/stdout 通信；帧经命名共享内存，避免写盘。"""

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
        self._frame_path = os.path.join(self._temp_dir, "frame.rgb")  # 回退路径
        self._use_shm = False
        self._shm_dual = False
        base = f"MusicEditing_rgb_{os.getpid()}_{id(self) & 0xFFFFFFFF:x}"
        self._shm_names = [f"{base}_0", f"{base}_1"]
        self._shm: list[Optional[mmap.mmap]] = [None, None]
        self._shm_capacity = _SHM_CAPACITY
        self._prefetch: Optional[_PrefetchSlot] = None
        self._prefetch_gen = 0
        self._prefetch_busy = False
        log.info("PlayerBackend 初始化 exe=%s shm=%s/%s", self._exe, *self._shm_names)

    def _ensure_shm(self) -> bool:
        if self._shm[0] is not None and self._shm[1] is not None:
            return True
        try:
            for i, name in enumerate(self._shm_names):
                if self._shm[i] is None:
                    self._shm[i] = mmap.mmap(-1, self._shm_capacity, tagname=name)
            return True
        except OSError as e:
            log.warning("创建共享内存失败，将回退写盘: %s", e)
            self._close_shm()
            return False

    def _close_shm(self) -> None:
        for i in range(2):
            m = self._shm[i]
            if m is not None:
                try:
                    m.close()
                except Exception:
                    pass
                self._shm[i] = None
        self._use_shm = False
        self._shm_dual = False

    def _drain_stderr(self, proc: subprocess.Popen):
        if not proc.stderr:
            return
        for line in proc.stderr:
            line = line.rstrip()
            if line:
                log.debug("[media_player] %s", line)

    def _read_rgb_shm(self, w: int, h: int, slot: int = 0) -> bytes:
        expected = w * h * 3
        if expected <= 0:
            raise RuntimeError("共享内存未就绪")
        if expected > self._shm_capacity:
            raise RuntimeError(f"帧过大 {expected}/{self._shm_capacity}")
        idx = 0 if slot <= 0 else (1 if slot >= 1 else 0)
        if not self._shm_dual:
            idx = 0
        m = self._shm[idx]
        if m is None:
            raise RuntimeError("共享内存未就绪")
        m.seek(0)
        data = m.read(expected)
        if len(data) != expected:
            raise RuntimeError(f"SHM 帧数据不足 {len(data)}/{expected}")
        return data

    def _read_rgb_file(self, w: int, h: int) -> bytes:
        expected = w * h * 3
        with open(self._frame_path, "rb") as fp:
            data = fp.read(expected)
        if len(data) != expected:
            raise RuntimeError(f"帧数据不足 {len(data)}/{expected}")
        return data

    def _bind_shm(self) -> None:
        """子进程启动后绑定共享内存（优先双缓冲 A/B）。"""
        self._use_shm = False
        self._shm_dual = False
        if not self._ensure_shm():
            return
        try:
            # SHM <name0> <capacity> <name1>
            resp = self._send_unlocked(
                f"SHM {self._shm_names[0]} {self._shm_capacity} {self._shm_names[1]}"
            )
            if resp.startswith("SHM_OK"):
                self._use_shm = True
                self._shm_dual = "dual=1" in resp
                log.info(
                    "帧传输: 共享内存 dual=%s %s",
                    self._shm_dual,
                    "/".join(self._shm_names) if self._shm_dual else self._shm_names[0],
                )
            else:
                log.warning("SHM 协议失败: %s，回退写盘", resp)
        except RuntimeError as e:
            log.warning("SHM 绑定失败: %s，回退写盘", e)

    def _ensure_running(self):
        if self._proc and self._proc.poll() is None:
            return
        env = os.environ.copy()
        exe_dir = str(self._exe.parent)
        env["PATH"] = exe_dir + os.pathsep + env.get("PATH", "")
        env["MUSIC_LOG_FILE"] = media_player_log_path()
        env.setdefault("MUSIC_LOG_LEVEL", os.environ.get("MUSIC_LOG_LEVEL", "INFO"))
        from core.win_subprocess import hide_console_kwargs

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
            **hide_console_kwargs(),
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, args=(self._proc,), daemon=True
        )
        self._stderr_thread.start()
        log.info("media_player 已启动 pid=%s", self._proc.pid)
        self._bind_shm()

    def _invalidate_prefetch(self) -> None:
        self._prefetch_gen += 1
        self._prefetch = None

    def _restart(self):
        with self._lock:
            self._invalidate_prefetch()
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
            self._use_shm = False
            self._shm_dual = False

    def _send_unlocked(self, cmd: str) -> str:
        self._ensure_running()
        assert self._proc and self._proc.stdin and self._proc.stdout
        log.debug("IPC >> %s", cmd)
        self._proc.stdin.write(cmd + "\n")
        self._proc.stdin.flush()
        line = self._proc.stdout.readline()
        if not line:
            self._proc = None
            self._use_shm = False
            self._shm_dual = False
            log.error("media_player 无响应 cmd=%s", cmd)
            raise RuntimeError("media_player 无响应，请关闭 UI 后重新运行 run_ui.bat")
        resp = line.strip()
        log.debug("IPC << %s", resp)
        return resp

    def _send(self, cmd: str) -> str:
        with self._lock:
            return self._send_unlocked(cmd)

    def _parse_frame_ok(self, resp: str) -> tuple[float, int, int, FrameStats, bool, int]:
        ts = 0.0
        w = self._info.width
        h = self._info.height
        stats = FrameStats()
        used_shm = False
        slot = 0
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
            elif token.startswith("shm="):
                used_shm = int(token.split("=", 1)[1]) != 0
            elif token.startswith("slot="):
                slot = int(token.split("=", 1)[1])
        return ts, w, h, stats, used_shm, slot

    def _decode_frame_unlocked(
        self,
        min_ts: float,
        apply_filter: bool,
    ) -> Optional[tuple[float, bytes, int, int, FrameStats]]:
        min_arg = min_ts if min_ts >= 0 else -1
        if self._use_shm:
            target = "shm"
        else:
            target = self._frame_path
        resp = self._send_unlocked(
            f"NEXT {target} {min_arg} {1 if apply_filter else 0}"
        )
        if resp == "FRAME_EOF":
            return None
        if resp.startswith("ERROR"):
            raise RuntimeError(resp)
        if not resp.startswith("FRAME_OK"):
            return None

        ts, w, h, stats, used_shm, slot = self._parse_frame_ok(resp)
        if stats.decode_ms > 35 or stats.skipped > 2:
            log.debug(
                "FRAME ts=%.3f ms=%d skipped=%d hw=%s shm=%s slot=%d filter=%s",
                ts, stats.decode_ms, stats.skipped, stats.hw_xfer, used_shm, slot, apply_filter,
            )
        if used_shm or self._use_shm:
            data = self._read_rgb_shm(w, h, slot)
        else:
            data = self._read_rgb_file(w, h)
        return ts, data, w, h, stats

    def _kick_prefetch_unlocked(self, apply_filter: bool) -> None:
        """解码下一帧到预取槽（调用方已持锁或不需要锁时由工作线程再取锁）。"""
        if self._prefetch_busy or self._prefetch is not None:
            return
        gen = self._prefetch_gen
        self._prefetch_busy = True

        def work():
            try:
                with self._lock:
                    if gen != self._prefetch_gen:
                        return
                    if self._prefetch is not None:
                        return
                    # 预取不带 min_ts，交给下次 next_frame 校验
                    got = self._decode_frame_unlocked(-1.0, apply_filter)
                    if gen != self._prefetch_gen:
                        return
                    if got is None:
                        return
                    ts, data, w, h, stats = got
                    stats.from_prefetch = True
                    self._prefetch = _PrefetchSlot(ts, data, w, h, stats)
            except Exception as e:
                log.debug("预取失败: %s", e)
            finally:
                self._prefetch_busy = False

        threading.Thread(target=work, daemon=True, name="player-prefetch").start()

    def set_hwaccel(self, enabled: bool):
        """只记偏好；进程未起时不发 IPC（避免首页一打开就拉起 media_player）。"""
        self._hwaccel_preferred = enabled
        if not (self._proc and self._proc.poll() is None):
            return
        try:
            self._send(f"HWACCEL {'on' if enabled else 'off'}")
        except RuntimeError as e:
            log.warning("HWACCEL 失败: %s", e)

    def set_filter(self, mode: str):
        self._invalidate_prefetch()
        resp = self._send(f"FILTER {mode}")
        if resp.startswith("ERROR"):
            raise RuntimeError(resp)
        return resp

    def set_filter_device(self, device: str):
        """auto | cpu | opencl"""
        resp = self._send(f"FILTER_DEVICE {device}")
        if resp.startswith("ERROR"):
            raise RuntimeError(resp)
        return resp

    def filter_status(self) -> str:
        resp = self._send("FILTER_STATUS")
        if resp.startswith("ERROR"):
            raise RuntimeError(resp)
        return resp

    def set_playback_filter(self, enabled: bool):
        self._apply_filter_on_next = enabled

    def set_playback_scale(self, width: int, height: int):
        self._invalidate_prefetch()
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
        with self._lock:
            if self._hwaccel_preferred:
                try:
                    self._send_unlocked("HWACCEL on")
                except RuntimeError:
                    pass
            path = os.path.abspath(video_path)
            log.info("OPEN %s hw=%s", path, self._hwaccel_preferred)
            resp = self._send_unlocked(f"OPEN {path}")
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
                "OPEN_OK %dx%d fps=%.2f hw=%s(%s) shm=%s dual=%s",
                info.width, info.height, info.fps, info.hw_decode, info.hw_name,
                self._use_shm, self._shm_dual,
            )
            return info

    def _wait_prefetch_idle_unlocked(self, timeout_sec: float = 0.5) -> None:
        """持锁时等待预取线程结束（短暂放锁轮询）。"""
        deadline = time.monotonic() + timeout_sec
        while self._prefetch_busy and time.monotonic() < deadline:
            self._lock.release()
            time.sleep(0.01)
            self._lock.acquire()
        self._prefetch = None

    def seek(self, sec: float):
        with self._lock:
            self._invalidate_prefetch()
            self._wait_prefetch_idle_unlocked()
            log.info("SEEK %.3f", sec)
            resp = self._send_unlocked(f"SEEK {sec}")
            if resp.startswith("ERROR"):
                raise RuntimeError(resp)

    def seek_and_frame(
        self,
        sec: float,
        min_ts: float | None = None,
        apply_filter: bool | None = None,
    ) -> Optional[tuple[float, bytes, int, int]]:
        """原子 SEEK + 同步拉首帧（清预取，避免 Seek 后空一拍用旧帧）。"""
        use_filter = self._apply_filter_on_next if apply_filter is None else apply_filter
        min_arg = float(sec) if min_ts is None else float(min_ts)
        with self._lock:
            self._invalidate_prefetch()
            self._wait_prefetch_idle_unlocked()
            log.info("SEEK+FRAME %.3f", sec)
            resp = self._send_unlocked(f"SEEK {sec}")
            if resp.startswith("ERROR"):
                raise RuntimeError(resp)
            got = self._decode_frame_unlocked(min_arg, use_filter)
            if got is None:
                return None
            ts, data, w, h, stats = got
            stats.from_prefetch = False
            self._last_stats = stats
            self._kick_prefetch_unlocked(use_filter)
            return ts, data, w, h

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

        with self._lock:
            # 命中预取：时间戳满足 min_ts
            slot = self._prefetch
            if slot is not None:
                self._prefetch = None
                ok = min_arg < 0 or slot.ts + 1e-3 >= min_arg
                if ok:
                    self._last_stats = slot.stats
                    self._last_stats.from_prefetch = True
                    self._kick_prefetch_unlocked(use_filter)
                    return slot.ts, slot.data, slot.w, slot.h
                # 过旧则丢弃，继续同步解码

            got = self._decode_frame_unlocked(min_arg, use_filter)
            if got is None:
                return None
            ts, data, w, h, stats = got
            stats.from_prefetch = False
            self._last_stats = stats
            self._kick_prefetch_unlocked(use_filter)
            return ts, data, w, h

    @property
    def last_frame_stats(self) -> FrameStats:
        return self._last_stats

    @property
    def use_shm(self) -> bool:
        return bool(self._use_shm)

    @property
    def shm_dual(self) -> bool:
        return bool(getattr(self, "_shm_dual", False))

    def close(self):
        self.shutdown()

    def shutdown(self):
        log.info("PlayerBackend shutdown")
        self._restart()
        self._close_shm()

    @property
    def info(self) -> PlayerInfo:
        return self._info

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
