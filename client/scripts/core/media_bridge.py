"""C++ media_engine 桥接层（子进程方式，兼容 64 位 Python + 32 位引擎）"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import glob
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple


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


def _find_ffmpeg() -> Path:
    root = Path(__file__).resolve().parent.parent.parent.parent
    candidates = [
        root / "third_party" / "ffmpeg" / "x64" / "bin" / "ffmpeg.exe",
        root / "third_party" / "ffmpeg" / "x86" / "bin" / "ffmpeg.exe",
        root / "build_x64" / "bin" / "Release" / "ffmpeg.exe",
        root / "build" / "bin" / "Release" / "ffmpeg.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    raise FileNotFoundError("未找到 ffmpeg.exe")


def _video_encoder_args() -> list[str]:
    """捆绑 FFmpeg 无 libx264 时，Windows 使用 Media Foundation H.264。"""
    if sys.platform == "win32":
        return ["-c:v", "h264_mf", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-pix_fmt", "yuv420p"]


def _format_exit_code(code: int) -> str:
    unsigned = code & 0xFFFFFFFF
    if unsigned >= 0x80000000:
        known = {
            0xC0000005: "访问冲突（推理阶段崩溃）",
            0xC0000409: "堆损坏",
            0xC000001D: "非法指令",
        }
        label = known.get(unsigned, "进程异常退出")
        return f"0x{unsigned:08X} ({label})"
    return str(code)


def _extract_cli_errors(stderr: str) -> list[str]:
    errors: list[str] = []
    for line in stderr.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith((
            "PROBE_ERROR", "ITERATE_ERROR", "EXTRACT_AUDIO_ERROR",
            "ANALYZE_SPEECH_ERROR", "WATERMARK_ERROR",
        )):
            errors.append(text)
        elif "] ERROR " in text:
            errors.append(text.split("] ERROR ", 1)[-1].strip())
    return errors


def _format_cli_failure(stdout: str, stderr: str, returncode: int) -> str:
    if "WATERMARK_OK" in stdout or "WATERMARK_FRAMES_OK" in stdout:
        return ""
    errors = _extract_cli_errors(stderr)
    if errors:
        return errors[-1]
    backend = "lama" if "WATERMARK_BACKEND:lama" in stderr else ""
    if backend and "WATERMARK_BACKEND:lama" in stderr:
        return (
            f"LaMa 推理失败（退出码 {_format_exit_code(returncode)}）。"
            "请缩小水印区域或缩短视频时间段后重试；若仍失败请重启 UI。"
        )
    tail = stderr.strip() or stdout.strip() or f"exit code {returncode}"
    return f"media_cli 失败 ({_format_exit_code(returncode)}): {tail}"


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
        self._prefer_cuda = False
        self._prefer_hw_decode = True
        self._watermark_backend = "lama"
        self.set_prefer_cuda(False)
        self.set_prefer_hw_decode(True)
        self.set_watermark_backend("lama")

        ver = self._run(["version"]).strip()
        self._ffmpeg_version = ver or "unknown"

    def set_prefer_cuda(self, enabled: bool) -> None:
        """LaMa ONNX CUDA EP 开关（默认关闭，项目不再捆绑 cuda_runtime）。"""
        self._prefer_cuda = bool(enabled)
        self._env["MUSIC_ORT_CUDA"] = "1" if self._prefer_cuda else "0"

    def set_prefer_hw_decode(self, enabled: bool) -> None:
        """批处理 iterate / 缩略图是否请求 D3D11VA（CLI --hw）。"""
        self._prefer_hw_decode = bool(enabled)

    @property
    def prefer_hw_decode(self) -> bool:
        return self._prefer_hw_decode

    def set_watermark_backend(self, backend: str) -> None:
        """去水印后端：lama（精修）| opencv（快速，适合视频）。"""
        b = (backend or "lama").strip().lower()
        if b in ("opencv", "cv", "fast"):
            self._watermark_backend = "opencv"
        else:
            self._watermark_backend = "lama"
        self._env["MUSIC_WATERMARK_BACKEND"] = self._watermark_backend

    @property
    def watermark_backend(self) -> str:
        return self._watermark_backend

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
                                    "EXTRACT_AUDIO_ERROR", "ANALYZE_SPEECH_ERROR",
                                    "WATERMARK_ERROR")):
                    raise RuntimeError(line.strip())

        if result.returncode != 0:
            if "WATERMARK_OK" in result.stdout or "WATERMARK_FRAMES_OK" in result.stdout:
                return result.stdout
            raise RuntimeError(_format_cli_failure(
                result.stdout, result.stderr, result.returncode,
            ))

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
        prefer_hw: Optional[bool] = None,
        max_frames: int = 0,
    ) -> None:
        cmd = [str(self._cli), "iterate", file_path]
        if max_frames > 0:
            cmd.append(str(max_frames))
        use_hw = self._prefer_hw_decode if prefer_hw is None else bool(prefer_hw)
        if use_hw:
            cmd.append("--hw")
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

    @property
    def watermark_available(self) -> bool:
        return (self._cli.parent / "onnxruntime.dll").exists()

    def watermark_inpaint_image(
        self,
        model_path: str,
        input_path: str,
        output_path: str,
        regions: List[Tuple[int, int, int, int]],
        timeout: Optional[int] = 600,
        backend: str = "lama",
    ) -> str:
        if not regions:
            raise ValueError("请至少框选一个水印区域")
        prev = self._watermark_backend
        self.set_watermark_backend(backend)
        try:
            args = ["watermark-inpaint", model_path or "-", input_path, output_path]
            for x, y, w, h in regions:
                args.extend([str(x), str(y), str(w), str(h)])
            out = self._run(args, timeout=timeout)
            if "WATERMARK_OK" not in out:
                raise RuntimeError(f"去水印失败: {out}")
            for line in out.splitlines():
                if line.startswith("output="):
                    return line.split("=", 1)[1].strip()
            return output_path
        finally:
            self.set_watermark_backend(prev)

    def watermark_inpaint_frames(
        self,
        model_path: str,
        frames_in_dir: str,
        frames_out_dir: str,
        regions: List[Tuple[int, int, int, int]],
        on_progress: Optional[Callable[[int, int], None]] = None,
        timeout: Optional[int] = 600,
        backend: Optional[str] = None,
    ) -> int:
        """一次加载后端，批量处理目录内 PNG 帧（进程内复用）。返回处理帧数。"""
        if not regions:
            raise ValueError("请至少框选一个水印区域")
        prev = self._watermark_backend
        if backend:
            self.set_watermark_backend(backend)
        try:
            args = [
                "watermark-inpaint-frames",
                model_path or "-",
                frames_in_dir,
                frames_out_dir,
            ]
            for x, y, w, h in regions:
                args.extend([str(x), str(y), str(w), str(h)])

            cmd = [str(self._cli)] + args
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
            count = 0
            stderr_lines: list[str] = []

            def drain_stderr():
                assert proc.stderr is not None
                for line in proc.stderr:
                    stderr_lines.append(line.rstrip("\n"))

            t = threading.Thread(target=drain_stderr, daemon=True)
            t.start()

            try:
                for line in proc.stdout:
                    line = line.strip()
                    if line.startswith("PROGRESS:"):
                        parts = line.split(":")
                        if len(parts) >= 3:
                            cur = int(parts[1])
                            total = int(parts[2])
                            if on_progress:
                                on_progress(cur, total)
                    elif line.startswith("count="):
                        count = int(line.split("=", 1)[1])
            finally:
                try:
                    proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    raise RuntimeError(f"批量去水印超时: {' '.join(cmd)}") from None
                t.join(timeout=5)

            if proc.returncode != 0:
                detail = "\n".join(stderr_lines).strip()
                fail = _format_cli_failure("", detail, proc.returncode or -1)
                for ln in stderr_lines:
                    if ln.startswith("WATERMARK_ERROR"):
                        raise RuntimeError(ln if not fail else fail)
                raise RuntimeError(fail or detail or f"批量去水印失败 exit {proc.returncode}")

            if count <= 0:
                raise RuntimeError("批量去水印未返回帧数")
            return count
        finally:
            self.set_watermark_backend(prev)

    def extract_video_frame(
        self,
        video_path: str,
        timestamp_sec: float,
        output_png: str,
    ) -> None:
        ffmpeg = _find_ffmpeg()
        cmd = [
            str(ffmpeg), "-y",
            "-ss", f"{max(0.0, timestamp_sec):.3f}",
            "-i", video_path,
            "-vframes", "1",
            output_png,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=self._env,
        )
        if result.returncode != 0 or not os.path.isfile(output_png):
            err = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"提取预览帧失败: {err}")

    def watermark_inpaint_video(
        self,
        model_path: str,
        input_path: str,
        output_path: str,
        regions: List[Tuple[int, int, int, int]],
        fps: float,
        start_sec: float = 0.0,
        end_sec: float = 0.0,
        max_frames: int = 0,
        on_progress: Optional[Callable[[float, str], None]] = None,
        backend: str = "opencv",
    ) -> str:
        """视频去水印。默认 backend=opencv（秒级）；精修可传 lama。进程内一次加载、多帧复用。"""
        if not regions:
            raise ValueError("请至少框选一个水印区域")
        if fps <= 0:
            fps = 25.0

        use_lama = (backend or "opencv").strip().lower() not in ("opencv", "cv", "fast")
        ffmpeg = _find_ffmpeg()
        tmp = tempfile.mkdtemp(prefix="music_wm_")
        frames_in = os.path.join(tmp, "in")
        frames_out = os.path.join(tmp, "out")
        os.makedirs(frames_in)
        os.makedirs(frames_out)

        def report(p: float, msg: str):
            if on_progress:
                on_progress(p, msg)

        try:
            report(2.0, "正在提取视频帧…")
            extract_cmd = [str(ffmpeg), "-y"]
            if start_sec > 0:
                extract_cmd.extend(["-ss", f"{start_sec:.3f}"])
            extract_cmd.extend(["-i", input_path])
            # end_sec > start_sec 即可；此前 start_sec==0 时误跳过 -to
            if end_sec > start_sec:
                duration = end_sec - start_sec
                extract_cmd.extend(["-t", f"{duration:.3f}"])
            if max_frames > 0:
                extract_cmd.extend(["-vframes", str(max_frames)])
            extract_cmd.extend([
                "-vsync", "0",
                os.path.join(frames_in, "frame_%06d.png"),
            ])
            result = subprocess.run(
                extract_cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=self._env,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "帧提取失败")

            frame_files = sorted(glob.glob(os.path.join(frames_in, "*.png")))
            if not frame_files:
                raise RuntimeError("未提取到任何视频帧")

            total = len(frame_files)
            mode_label = "LaMa 精修" if use_lama else "OpenCV 快速修复"
            report(8.0, f"共 {total} 帧，{mode_label}中…")

            def on_frame(cur: int, frame_total: int):
                pct = 8.0 + cur / frame_total * 82.0
                report(pct, f"处理帧 {cur}/{frame_total}")

            # OpenCV：约 2s/帧足够；LaMa：120s/帧
            timeout = max(120, total * 120) if use_lama else max(60, total * 3)
            self.watermark_inpaint_frames(
                model_path if use_lama else (model_path or "-"),
                frames_in,
                frames_out,
                regions,
                on_progress=on_frame,
                timeout=timeout,
                backend="lama" if use_lama else "opencv",
            )

            silent_mp4 = os.path.join(tmp, "silent.mp4")
            report(92.0, "正在编码视频…")
            encode_cmd = [
                str(ffmpeg), "-y",
                "-framerate", f"{fps:.3f}",
                "-i", os.path.join(frames_out, "frame_%06d.png"),
                *_video_encoder_args(),
                silent_mp4,
            ]
            result = subprocess.run(
                encode_cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=self._env,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "视频编码失败")

            report(96.0, "正在合并音频…")
            mux_cmd = [
                str(ffmpeg), "-y",
                "-i", silent_mp4,
                "-i", input_path,
                "-map", "0:v:0",
                "-map", "1:a:0?",
                "-c:v", "copy",
                "-c:a", "aac",
                "-shortest",
                output_path,
            ]
            result = subprocess.run(
                mux_cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=self._env,
            )
            if result.returncode != 0 or not os.path.isfile(output_path):
                shutil.copy2(silent_mp4, output_path)
            report(100.0, "完成")
            return output_path
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def shutdown(self):
        pass
