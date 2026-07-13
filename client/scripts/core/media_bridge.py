"""C++ media_engine 桥接层（子进程方式，兼容 64 位 Python + 32 位引擎）"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional


def _find_cli() -> Path:
    """查找 media_cli.exe（优先 x64，其次 Win32）"""
    root = Path(__file__).resolve().parent.parent.parent.parent
    candidates = [
        root / "build_x64" / "bin" / "Release" / "media_cli.exe",
        root / "build_x64" / "bin" / "Debug" / "media_cli.exe",
        root / "build" / "bin" / "Release" / "media_cli.exe",
        root / "build" / "bin" / "Debug" / "media_cli.exe",
        Path.cwd() / "build_x64" / "bin" / "Release" / "media_cli.exe",
        Path.cwd() / "build" / "bin" / "Release" / "media_cli.exe",
        Path.cwd() / "media_cli.exe",
        Path(__file__).resolve().parent.parent / "media_cli.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "未找到 media_cli.exe，请先运行 .\\build_x64.bat 或 .\\build.bat 编译 C++ 核心库"
    )


@dataclass
class VideoInfo:
    file_path: str
    width: int = 0
    height: int = 0
    duration_sec: float = 0.0
    fps: float = 0.0
    total_frames: int = 0
    codec_name: str = ""
    format_name: str = ""


@dataclass
class HighlightResult:
    start_sec: float
    end_sec: float
    score: float = 0.0
    llm_used: bool = False


class MediaBridge:
    """通过子进程调用 32 位 media_cli.exe，避免 Python 位数不匹配"""

    def __init__(self, cli_path: Optional[str] = None):
        self._cli = Path(cli_path) if cli_path else _find_cli()
        if not self._cli.exists():
            raise FileNotFoundError(f"找不到: {self._cli}")

        cli_dir = str(self._cli.parent)
        env = os.environ.copy()
        if cli_dir not in env.get("PATH", ""):
            env["PATH"] = cli_dir + os.pathsep + env.get("PATH", "")
        self._env = env

        ver = self._run(["version"]).strip()
        self._ffmpeg_version = ver or "unknown"

    def _run(self, args: list[str], timeout: Optional[int] = None) -> str:
        cmd = [str(self._cli)] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._env,
                timeout=timeout,
                cwd=str(self._cli.parent),
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"命令超时: {' '.join(cmd)}") from e

        if result.stderr:
            for line in result.stderr.splitlines():
                if line.startswith(("PROBE_ERROR", "ITERATE_ERROR",
                                    "EXTRACT_AUDIO_ERROR", "ANALYZE_SPEECH_ERROR")):
                    raise RuntimeError(line)

        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            raise RuntimeError(f"media_cli 失败: {err}")

        return result.stdout

    @property
    def ffmpeg_version(self) -> str:
        return self._ffmpeg_version

    def probe_video(self, file_path: str) -> VideoInfo:
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        out = self._run(["probe", file_path])
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if not any(ln == "PROBE_OK" for ln in lines):
            raise RuntimeError(f"探测视频失败: {file_path}\n{out}")

        data: dict[str, str] = {}
        for line in lines[1:]:
            if "=" in line:
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()

        return VideoInfo(
            file_path=file_path,
            width=int(data.get("width", 0)),
            height=int(data.get("height", 0)),
            duration_sec=float(data.get("duration", 0)),
            fps=float(data.get("fps", 0)),
            total_frames=int(data.get("total_frames", 0)),
            codec_name=data.get("codec", ""),
            format_name=data.get("format", ""),
        )

    def iterate_frames(
        self,
        file_path: str,
        on_progress: Callable[[int, int, float], bool],
    ) -> None:
        cmd = [str(self._cli), "iterate", file_path]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self._env,
            cwd=str(self._cli.parent),
        )

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("PROGRESS:"):
                parts = line.split(":")
                if len(parts) >= 4:
                    idx = int(parts[1])
                    total = int(parts[2])
                    ts = float(parts[3])
                    if not on_progress(idx, total, ts):
                        proc.terminate()
                        break

        proc.wait()
        if proc.returncode not in (0, 1):
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"帧遍历失败 (code={proc.returncode}): {err}")

    def extract_audio(self, video_path: str, wav_path: str) -> None:
        out = self._run(["extract-audio", video_path, wav_path], timeout=600)
        if "EXTRACT_AUDIO_OK" not in out:
            raise RuntimeError(f"音频提取失败: {out}")

    def analyze_speech(
        self,
        transcript_json: str,
        model_path: str,
        scene: str,
        min_duration: float,
        max_duration: float,
        sensitivity: float,
        timeout: Optional[int] = 600,
    ) -> List[HighlightResult]:
        args = [
            "analyze-speech", transcript_json, model_path, scene,
            str(min_duration), str(max_duration), str(sensitivity),
        ]
        out = self._run(args, timeout=timeout)
        if "HIGHLIGHTS_OK" not in out:
            raise RuntimeError(f"高光分析失败: {out}")

        llm_used = False
        results: List[HighlightResult] = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("llm_used="):
                llm_used = line.split("=", 1)[1].strip() == "1"
            elif line.startswith("HIGHLIGHT|"):
                parts = line.split("|")
                if len(parts) >= 4:
                    results.append(HighlightResult(
                        start_sec=float(parts[1]),
                        end_sec=float(parts[2]),
                        score=float(parts[3]),
                        llm_used=llm_used,
                    ))
        return results

    def shutdown(self):
        pass
