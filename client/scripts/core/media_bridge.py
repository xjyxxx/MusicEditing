"""C++ media_engine 桥接层（子进程方式，兼容 64 位 Python + 32 位引擎）"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import glob
import shutil
import threading
from dataclasses import dataclass, field
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


def _find_yt_dlp() -> Path:
    """查找 yt-dlp（优先 third_party，便于打包）。"""
    root = Path(__file__).resolve().parent.parent.parent.parent
    candidates = [
        root / "third_party" / "yt-dlp" / "yt-dlp.exe",
        root / "build_x64" / "bin" / "Release" / "yt-dlp.exe",
        root / "build" / "bin" / "Release" / "yt-dlp.exe",
        Path(__file__).resolve().parent.parent / "yt-dlp.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    found = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "未找到 yt-dlp.exe。请运行 scripts\\download_yt_dlp.bat "
        "下载到 third_party\\yt-dlp\\"
    )


def _find_exiftool() -> Path:
    """查找 ExifTool（exe 旁须有 exiftool_files/）。"""
    root = Path(__file__).resolve().parent.parent.parent.parent
    candidates = [
        root / "third_party" / "exiftool" / "exiftool.exe",
        root / "build_x64" / "bin" / "Release" / "exiftool.exe",
        root / "build" / "bin" / "Release" / "exiftool.exe",
        Path(__file__).resolve().parent.parent / "exiftool.exe",
    ]
    for p in candidates:
        if p.exists():
            return p
    found = shutil.which("exiftool") or shutil.which("exiftool.exe")
    if found:
        return Path(found)
    raise FileNotFoundError(
        "未找到 exiftool.exe。请运行 scripts\\download_exiftool.bat "
        "下载到 third_party\\exiftool\\"
    )


# 图片页优先展示的标签（按常见摄影信息排序）
_EXIF_HIGHLIGHT_TAGS = (
    "FileName", "FileSize", "MIMEType", "ImageSize", "ImageWidth", "ImageHeight",
    "Make", "Model", "LensModel", "LensID", "LensInfo",
    "DateTimeOriginal", "CreateDate", "ModifyDate",
    "FocalLength", "FNumber", "ExposureTime", "ISO", "ShutterSpeedValue",
    "Flash", "WhiteBalance", "ExposureProgram", "MeteringMode", "Orientation",
    "ColorSpace", "GPSPosition", "GPSLatitude", "GPSLongitude", "GPSAltitude",
    "Software", "Artist", "Copyright", "Description", "UserComment",
)


def _video_encoder_args(*, high_quality: bool = False) -> list[str]:
    """捆绑 FFmpeg 无 libx264 时，Windows 使用 Media Foundation H.264。"""
    if sys.platform == "win32":
        args = ["-c:v", "h264_mf", "-pix_fmt", "yuv420p"]
        if high_quality:
            # 默认码率偏低会明显糊于原片；补帧等重编码场景提高码率
            args.extend(["-b:v", "12M", "-maxrate", "18M", "-bufsize", "24M"])
        return args
    if high_quality:
        return ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium"]
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
            "ANALYZE_SPEECH_ERROR", "WATERMARK_ERROR", "UPSCALE_ERROR",
        )):
            errors.append(text)
        elif "] ERROR " in text:
            errors.append(text.split("] ERROR ", 1)[-1].strip())
    return errors


def _format_cli_failure(stdout: str, stderr: str, returncode: int) -> str:
    if ("WATERMARK_OK" in stdout or "WATERMARK_FRAMES_OK" in stdout
            or "UPSCALE_OK" in stdout or "UPSCALE_FRAMES_OK" in stdout):
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
    if "UPSCALE_BACKEND:realesrgan" in stderr:
        return (
            f"超分推理失败（退出码 {_format_exit_code(returncode)}）。"
            "可改用「快速」模式，或缩短视频时间段后重试。"
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


@dataclass
class UrlListItem:
    """探测列表行：可用格式或播放列表条目。"""
    name: str
    detail: str = ""
    url: str = ""           # 直链媒体 URL，或条目页面 URL
    kind: str = "format"    # format | entry
    format_id: str = ""     # yt-dlp format id
    page_url: str = ""      # 所属页面（用于按 format_id 拉取）
    ext: str = ""
    has_video: bool = False
    has_audio: bool = False


@dataclass
class UrlMediaInfo:
    """yt-dlp -J 探测结果（不下载）。"""
    url: str
    title: str = ""
    duration_sec: float = 0.0
    uploader: str = ""
    webpage_url: str = ""
    thumbnail: str = ""
    ext: str = ""
    playlist_title: str = ""
    preview_hint: str = ""
    items: List[UrlListItem] = field(default_factory=list)


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
        self._upscale_backend = "realesrgan"
        self.set_prefer_cuda(False)
        self.set_prefer_hw_decode(True)
        self.set_watermark_backend("lama")
        self.set_upscale_backend("realesrgan")

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

    def set_upscale_backend(self, backend: str) -> None:
        """超分后端：realesrgan（AI）| opencv（双三次快速）。"""
        b = (backend or "realesrgan").strip().lower()
        if b in ("opencv", "cv", "fast", "bicubic"):
            self._upscale_backend = "opencv"
        else:
            self._upscale_backend = "realesrgan"
        self._env["MUSIC_UPSCALE_BACKEND"] = self._upscale_backend

    @property
    def upscale_backend(self) -> str:
        return self._upscale_backend

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
                                    "THUMBNAIL_ERROR",
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

    def extract_thumbnail(
        self,
        file_path: str,
        timestamp_sec: float,
        *,
        output_path: str = "",
        max_width: int = 160,
        prefer_hw: Optional[bool] = None,
        use_cache: bool = True,
    ) -> str:
        """
        抽取指定时刻缩略图（PPM），经 media_cli thumbnail → extractThumbnail。
        默认写入系统临时目录小图缓存。
        """
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"文件不存在: {file_path}")

        from core.thumbnail_cache import cache_path, is_fresh

        out = Path(output_path) if output_path else cache_path(
            file_path, timestamp_sec, max_width=max_width,
        )
        if use_cache and is_fresh(out, file_path):
            return str(out)

        out.parent.mkdir(parents=True, exist_ok=True)
        args = [
            "thumbnail",
            file_path,
            f"{float(timestamp_sec):.6f}",
            str(out),
            f"--max-w={int(max_width)}",
        ]
        use_hw = self._prefer_hw_decode if prefer_hw is None else bool(prefer_hw)
        if use_hw:
            args.append("--hw")

        text = self._run(args, timeout=120)
        if "THUMBNAIL_OK" not in text:
            raise RuntimeError(f"提取缩略图失败:\n{text}")
        if not out.is_file() or out.stat().st_size < 32:
            raise RuntimeError(f"缩略图未生成: {out}")
        return str(out)

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

    @property
    def upscale_available(self) -> bool:
        return (self._cli.parent / "onnxruntime.dll").exists()

    def upscale_image(
        self,
        model_path: str,
        input_path: str,
        output_path: str,
        scale: int = 4,
        strength: int = 65,
        timeout: Optional[int] = 600,
        backend: str = "realesrgan",
    ) -> str:
        prev = self._upscale_backend
        self.set_upscale_backend(backend)
        try:
            sp = max(0, min(100, int(strength)))
            args = [
                "upscale",
                model_path or "-",
                input_path,
                output_path,
                str(2 if scale == 2 else 4),
                str(sp),
            ]
            out = self._run(args, timeout=timeout)
            if "UPSCALE_OK" not in out:
                raise RuntimeError(f"超分失败: {out}")
            for line in out.splitlines():
                if line.startswith("output="):
                    return line.split("=", 1)[1].strip()
            return output_path
        finally:
            self.set_upscale_backend(prev)

    def upscale_frames(
        self,
        model_path: str,
        frames_in_dir: str,
        frames_out_dir: str,
        scale: int = 4,
        strength: int = 65,
        on_progress: Optional[Callable[[int, int], None]] = None,
        timeout: Optional[int] = 600,
        backend: Optional[str] = None,
    ) -> int:
        """一次加载后端，批量超分目录内 PNG 帧。返回处理帧数。"""
        prev = self._upscale_backend
        if backend:
            self.set_upscale_backend(backend)
        try:
            sp = max(0, min(100, int(strength)))
            args = [
                "upscale-frames",
                model_path or "-",
                frames_in_dir,
                frames_out_dir,
                str(2 if scale == 2 else 4),
                str(sp),
            ]
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
                    elif line.startswith("UPSCALE_FRAMES_OK"):
                        pass
                    elif line.startswith("count="):
                        try:
                            count = int(line.split("=", 1)[1])
                        except ValueError:
                            pass
            finally:
                proc.wait(timeout=timeout)
                t.join(timeout=5)

            stderr = "\n".join(stderr_lines)
            if proc.returncode != 0:
                err = _format_cli_failure("", stderr, proc.returncode)
                raise RuntimeError(err or f"超分帧处理失败: {stderr}")
            return count
        finally:
            self.set_upscale_backend(prev)

    def upscale_video(
        self,
        model_path: str,
        input_path: str,
        output_path: str,
        fps: float,
        scale: int = 2,
        strength: int = 65,
        start_sec: float = 0.0,
        end_sec: float = 0.0,
        max_frames: int = 0,
        on_progress: Optional[Callable[[float, str], None]] = None,
        backend: str = "opencv",
    ) -> str:
        """视频超分。默认 backend=opencv；AI 传 realesrgan。进程内一次加载、多帧复用。"""
        if fps <= 0:
            fps = 25.0
        scale = 2 if scale == 2 else 4
        strength = max(0, min(100, int(strength)))
        use_ai = (backend or "opencv").strip().lower() not in (
            "opencv", "cv", "fast", "bicubic",
        )
        ffmpeg = _find_ffmpeg()
        tmp = tempfile.mkdtemp(prefix="music_sr_")
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
            mode_label = "Real-ESRGAN" if use_ai else "OpenCV 双三次"
            report(8.0, f"共 {total} 帧，{mode_label} {scale}x 强度{strength}%…")

            def on_frame(cur: int, frame_total: int):
                pct = 8.0 + cur / frame_total * 82.0
                report(pct, f"处理帧 {cur}/{frame_total}")

            timeout = max(120, total * 90) if use_ai else max(60, total * 3)
            self.upscale_frames(
                model_path if use_ai else (model_path or "-"),
                frames_in,
                frames_out,
                scale=scale,
                strength=strength,
                on_progress=on_frame,
                timeout=timeout,
                backend="realesrgan" if use_ai else "opencv",
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

    def interpolate_video(
        self,
        input_path: str,
        output_path: str,
        *,
        fps: float = 0.0,
        factor: int = 2,
        start_sec: float = 0.0,
        end_sec: float = 0.0,
        quality: str = "fast",
        on_progress: Optional[Callable[[float, str], None]] = None,
        **_ignored,
    ) -> str:
        """
        视频补帧：FFmpeg minterpolate 提升帧率（默认 2x）。
        quality=fast → blend（快，默认）；quality=quality → MCI 运动补偿（慢、更顺）。
        """
        factor = 2 if int(factor) <= 2 else 4
        q = (quality or "fast").strip().lower()
        if q in ("mci", "hq", "high", "fine", "精细"):
            q = "quality"
        if q not in ("fast", "quality"):
            q = "fast"

        def report(p: float, msg: str):
            if on_progress:
                on_progress(p, msg)

        ffmpeg = _find_ffmpeg()
        if fps <= 0:
            try:
                info = self.probe_video(input_path)
                fps = float(info.fps or 0.0)
            except Exception:
                fps = 0.0
        if fps <= 0:
            fps = 25.0
        out_fps = fps * factor

        duration = 0.0
        if end_sec > start_sec:
            duration = end_sec - start_sec

        if q == "quality":
            # 运动补偿更顺，但极慢；关掉 vsbmc 略快一点
            vf_primary = (
                f"minterpolate=fps={out_fps:.3f}:mi_mode=mci:"
                f"mc_mode=aobmc:me_mode=bidir:vsbmc=0"
            )
            mode_label = "精细(MCI)"
            enc = _video_encoder_args(high_quality=True)
        else:
            # 帧混合，比 MCI 快一个数量级以上
            vf_primary = f"minterpolate=fps={out_fps:.3f}:mi_mode=blend"
            mode_label = "快速(blend)"
            enc = _video_encoder_args(high_quality=False)
            if sys.platform == "win32":
                # 略提高默认 h264_mf 观感，仍比 12M 编码快
                enc = [
                    "-c:v", "h264_mf", "-pix_fmt", "yuv420p",
                    "-b:v", "6M", "-maxrate", "8M", "-bufsize", "12M",
                ]

        report(
            5.0,
            f"FFmpeg 补帧 {mode_label} → {out_fps:.2f} fps"
            + (f"（{duration:.1f}s）" if duration > 0 else "（全程）")
            + "…",
        )

        def _run_with_vf(vf: str) -> subprocess.CompletedProcess:
            cmd = [str(ffmpeg), "-y", "-hide_banner", "-stats"]
            if start_sec > 0:
                cmd.extend(["-ss", f"{start_sec:.3f}"])
            cmd.extend(["-i", input_path])
            if duration > 0:
                cmd.extend(["-t", f"{duration:.3f}"])
            cmd.extend([
                "-vf", vf,
                *enc,
                "-c:a", "aac", "-b:a", "160k",
                "-shortest",
                output_path,
            ])
            return subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=self._env,
            )

        report(15.0, f"正在{mode_label}补帧编码…")
        result = _run_with_vf(vf_primary)
        if result.returncode != 0 or not os.path.isfile(output_path):
            if q == "quality":
                report(30.0, "MCI 失败，回退 blend…")
                result = _run_with_vf(
                    f"minterpolate=fps={out_fps:.3f}:mi_mode=blend"
                )
            if result.returncode != 0 or not os.path.isfile(output_path):
                raise RuntimeError(
                    (result.stderr or "").strip() or "FFmpeg 补帧失败"
                )
        report(100.0, "完成")
        return output_path

    @property
    def yt_dlp_available(self) -> bool:
        try:
            _find_yt_dlp()
            return True
        except FileNotFoundError:
            return False

    @property
    def exiftool_available(self) -> bool:
        try:
            _find_exiftool()
            return True
        except FileNotFoundError:
            return False

    def read_image_exif(self, path: str, *, full: bool = True) -> str:
        """用 ExifTool 读取图片元数据，返回可读文本。"""
        path = (path or "").strip()
        if not path or not os.path.isfile(path):
            raise FileNotFoundError("图片不存在")
        et = _find_exiftool()
        # -G1 分组；-s 短标签名；-a 重复标签；-u 未知
        base = [
            str(et),
            "-charset", "filename=utf8",
            "-charset", "exif=utf8",
            "-G1",
            "-s",
            "-a",
            "-u",
            "-e",
        ]
        highlight_cmd = base + [f"-{t}" for t in _EXIF_HIGHLIGHT_TAGS] + [path]
        full_cmd = base + [path]

        def _run(cmd: list[str]) -> str:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                env=self._env,
            )
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
            if proc.returncode != 0 and not out:
                raise RuntimeError(err or f"exiftool exit {proc.returncode}")
            return out

        highlight = _run(highlight_cmd)
        if not full:
            return highlight or "（无常用 EXIF 字段）"

        full_text = _run(full_cmd)
        if not highlight and not full_text:
            return "（未读到元数据）"
        parts = []
        if highlight:
            parts.append("=== 常用信息 ===\n" + highlight)
        if full_text:
            parts.append("=== 全部标签 ===\n" + full_text)
        return "\n\n".join(parts)

    def probe_url(
        self,
        url: str,
        timeout: int = 90,
        *,
        list_entries: bool = False,
    ) -> UrlMediaInfo:
        """用 yt-dlp -J 探测网页媒体元数据（不下载）。

        list_entries=True 时允许播放列表，并用 --flat-playlist 拉条目名称列表。
        """
        url = (url or "").strip()
        if not url:
            raise ValueError("请输入链接")
        yt = _find_yt_dlp()
        cmd = [
            str(yt),
            "-J",
            "--no-warnings",
            "--socket-timeout", "30",
        ]
        if list_entries:
            cmd.append("--flat-playlist")
        else:
            cmd.append("--no-playlist")
        cmd.append(url)
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            env=self._env, timeout=timeout,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(err[-800:] if err else "链接探测失败")
        import json
        data = json.loads(result.stdout)
        return self._parse_url_media_info(url, data)

    @staticmethod
    def _parse_url_media_info(url: str, data: dict) -> UrlMediaInfo:
        items: List[UrlListItem] = []
        playlist_title = ""
        entry = data

        # 播放列表：标题 + 条目名列表
        if data.get("_type") == "playlist" or data.get("entries"):
            playlist_title = str(data.get("title") or data.get("id") or "播放列表")
            for i, e in enumerate(data.get("entries") or []):
                if not e:
                    continue
                name = str(e.get("title") or e.get("id") or f"条目 {i + 1}")
                dur = e.get("duration")
                detail = f"{float(dur):.0f}s" if dur else (e.get("id") or "")
                page = str(e.get("url") or e.get("webpage_url") or e.get("id") or "")
                # 网易云等：纯数字 id → 拼歌曲页
                if page.isdigit():
                    page = f"https://music.163.com/#/song?id={page}"
                items.append(UrlListItem(
                    name=name, detail=str(detail), url=page,
                    kind="entry", page_url=page, ext=str(e.get("ext") or ""),
                ))
            # 若扁平列表无格式，用第一条作「当前名」展示
            first = next((e for e in (data.get("entries") or []) if e), None)
            if first and not data.get("duration"):
                entry = first

        page_url = str(entry.get("webpage_url") or data.get("webpage_url") or url)

        # 单曲/单视频：可用格式列表
        formats = entry.get("formats") or data.get("formats") or []
        if formats and not items:
            for f in formats:
                if not isinstance(f, dict):
                    continue
                ext = str(f.get("ext") or "?")
                fid = str(f.get("format_id") or "")
                note = str(f.get("format_note") or f.get("resolution") or "")
                abr = f.get("abr") or 0
                vbr = f.get("vbr") or 0
                tbr = f.get("tbr") or 0
                size = int(f.get("filesize") or f.get("filesize_approx") or 0)
                media_url = str(f.get("url") or "")
                vcodec = str(f.get("vcodec") or "none").lower()
                acodec = str(f.get("acodec") or "none").lower()
                has_video = vcodec not in ("", "none", "null")
                has_audio = acodec not in ("", "none", "null")
                parts = []
                if has_video and not has_audio:
                    parts.append("仅画面")
                elif has_audio and not has_video:
                    parts.append("仅音频")
                elif has_video and has_audio:
                    parts.append("音画")
                parts.append(ext)
                if note:
                    parts.append(note)
                if abr:
                    parts.append(f"{abr:.0f}kbps")
                elif vbr:
                    parts.append(f"v{vbr:.0f}k")
                elif tbr:
                    parts.append(f"{tbr:.0f}k")
                if size > 0:
                    parts.append(f"~{size // 1024}KB" if size < 5_000_000 else f"~{size / 1e6:.1f}MB")
                if fid:
                    parts.append(f"id={fid}")
                items.append(UrlListItem(
                    name=" · ".join(parts),
                    detail=note or fid,
                    url=media_url,
                    kind="format",
                    format_id=fid,
                    page_url=page_url,
                    ext=ext if ext != "?" else "mp3",
                    has_video=has_video,
                    has_audio=has_audio,
                ))

        title = str(
            entry.get("title")
            or data.get("title")
            or entry.get("id")
            or data.get("id")
            or "未命名"
        )
        duration = float(entry.get("duration") or data.get("duration") or 0.0)
        filesize = int(
            entry.get("filesize")
            or entry.get("filesize_approx")
            or data.get("filesize")
            or data.get("filesize_approx")
            or 0
        )
        abr = 0.0
        if formats:
            for f in formats:
                if f.get("abr"):
                    abr = float(f["abr"])
                    break
        preview_hint = ""
        if duration > 90 and filesize > 0 and abr > 0:
            est = filesize * 8.0 / (abr * 1000.0)
            if est < duration * 0.55:
                preview_hint = (
                    f"疑似试听片段：元数据时长 {duration:.0f}s，"
                    f"按码率估算实际约 {est:.0f}s（站点未登录/VIP 限制）"
                )
        elif duration > 90 and filesize > 0 and filesize < 1_500_000:
            preview_hint = (
                f"疑似试听片段：元数据时长 {duration:.0f}s，"
                f"文件仅约 {filesize // 1024}KB"
            )

        return UrlMediaInfo(
            url=url,
            title=title,
            duration_sec=duration,
            uploader=str(
                entry.get("uploader")
                or entry.get("channel")
                or data.get("uploader")
                or data.get("channel")
                or ""
            ),
            webpage_url=str(entry.get("webpage_url") or data.get("webpage_url") or url),
            thumbnail=str(entry.get("thumbnail") or data.get("thumbnail") or ""),
            ext=str(entry.get("ext") or data.get("ext") or ""),
            playlist_title=playlist_title,
            preview_hint=preview_hint,
            items=items,
        )

    def download_url(
        self,
        url: str,
        output_dir: str,
        *,
        audio_only: bool = False,
        on_progress: Optional[Callable[[float, str], None]] = None,
        timeout: int = 0,
    ) -> str:
        """
        从网页链接下载视频或音频。
        audio_only=True 时提取为 mp3（需 ffmpeg）。
        返回最终文件路径。
        """
        import re
        import time as _time

        url = (url or "").strip()
        if not url:
            raise ValueError("请输入链接")
        yt = _find_yt_dlp()
        ffmpeg = _find_ffmpeg()
        os.makedirs(output_dir, exist_ok=True)

        stamp = int(_time.time())
        out_tmpl = os.path.join(output_dir, f"dl_{stamp}_%(id)s.%(ext)s")
        cmd = [
            str(yt),
            "--no-playlist",
            "--newline",
            "--no-warnings",
            "--ffmpeg-location", str(ffmpeg.parent),
            "-o", out_tmpl,
        ]
        if audio_only:
            cmd.extend(["-x", "--audio-format", "mp3", "--audio-quality", "0"])
        else:
            cmd.extend([
                "-f", "bv*+ba/b",
                "--merge-output-format", "mp4",
            ])
        cmd.append(url)

        def report(p: float, msg: str):
            if on_progress:
                on_progress(p, msg)

        report(1.0, "开始下载…")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self._env,
        )
        pct_re = re.compile(r"(\d{1,3}(?:\.\d+)?)%")
        assert proc.stdout is not None
        last_msg = ""
        try:
            for line in proc.stdout:
                text = line.strip()
                if not text:
                    continue
                last_msg = text
                m = pct_re.search(text)
                if m:
                    pct = min(99.0, float(m.group(1)))
                    report(pct, text[:120])
                elif "[ExtractAudio]" in text or "[Merger]" in text:
                    report(92.0, text[:120])
                else:
                    report(max(2.0, min(90.0, 40.0)), text[:120])
        finally:
            code = proc.wait(timeout=timeout if timeout > 0 else None)

        prefix = f"dl_{stamp}_"
        files = [
            os.path.join(output_dir, n)
            for n in os.listdir(output_dir)
            if n.startswith(prefix) and os.path.isfile(os.path.join(output_dir, n))
        ]
        if not files:
            hint = last_msg[-400:] if last_msg else f"exit {code}"
            raise RuntimeError(f"下载失败或未找到输出文件：{hint}")
        files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
        final = files[0]
        if code != 0 and not os.path.isfile(final):
            raise RuntimeError(f"下载失败（exit {code}）")

        report(100.0, f"完成: {os.path.basename(final)}")
        return final

    def fetch_for_preview(
        self,
        item_kind: str,
        *,
        page_url: str = "",
        media_url: str = "",
        format_id: str = "",
        ext: str = "mp3",
        referer: str = "",
        has_video: bool = False,
        has_audio: bool = False,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """为列表「播放」拉取到临时文件（不进用户下载目录）。

        B 站等 DASH：仅画面格式会自动 +bestaudio 合并，避免无声。
        """
        import tempfile
        import urllib.request

        def report(p: float, msg: str):
            if on_progress:
                on_progress(p, msg)

        tmp_dir = tempfile.mkdtemp(prefix="music_preview_")
        ext = (ext or "mp3").lstrip(".")
        if ext in ("?", "", "unknown"):
            ext = "mp3"

        video_only = bool(has_video and not has_audio)
        audio_only = bool(has_audio and not has_video)

        # 1) 有直链且非「仅画面」：HTTP 拉取（仅画面必须走 yt-dlp 合并音轨）
        if media_url.startswith("http") and not video_only:
            report(10.0, "正在拉取试听流…")
            out = os.path.join(tmp_dir, f"preview.{ext}")
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            if referer:
                headers["Referer"] = referer
            elif "163.com" in media_url or "126.net" in media_url:
                headers["Referer"] = "https://music.163.com/"
            elif "bilibili.com" in media_url or "bilivideo.com" in media_url:
                headers["Referer"] = "https://www.bilibili.com/"
            req = urllib.request.Request(media_url, headers=headers)
            with urllib.request.urlopen(req, timeout=90) as resp, open(out, "wb") as f:
                f.write(resp.read())
            if not os.path.isfile(out) or os.path.getsize(out) < 1000:
                raise RuntimeError("试听流拉取失败或文件过小")
            report(100.0, "就绪")
            return out

        # 2) 条目 / 指定 format：走 yt-dlp
        target = page_url or media_url
        if not target:
            raise RuntimeError("该列表项没有可播放地址")
        report(5.0, "正在用 yt-dlp 拉取预览…")
        if item_kind == "format" and format_id:
            yt = _find_yt_dlp()
            ffmpeg = _find_ffmpeg()
            out_tmpl = os.path.join(tmp_dir, f"preview_%(id)s.%(ext)s")
            cmd = [
                str(yt), "--no-playlist", "--newline", "--no-warnings",
                "--ffmpeg-location", str(ffmpeg.parent),
                "-o", out_tmpl,
            ]
            if video_only:
                # DASH 仅画面 → 合并最佳音轨
                report(8.0, "合并音轨中（DASH 仅画面）…")
                cmd.extend([
                    "-f", f"{format_id}+bestaudio/{format_id}",
                    "--merge-output-format", "mp4",
                ])
            elif audio_only:
                cmd.extend(["-f", format_id])
            else:
                # 未知是否分离：优先尝试带音频的组合
                cmd.extend([
                    "-f", f"{format_id}+bestaudio/{format_id}/bestaudio/best",
                    "--merge-output-format", "mp4",
                ])
            cmd.append(target)
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=self._env, timeout=300,
            )
            files = [
                os.path.join(tmp_dir, n) for n in os.listdir(tmp_dir)
                if os.path.isfile(os.path.join(tmp_dir, n))
            ]
            if not files:
                raise RuntimeError(proc.stderr[-400:] if proc.stderr else "预览拉取失败")
            files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            report(100.0, "就绪")
            return files[0]

        # 3) 歌单条目：默认下音画合并（B 站等），失败再试仅音频
        report(8.0, "正在拉取音画合并预览…")
        try:
            return self.download_url(
                target, tmp_dir, audio_only=False, on_progress=on_progress,
            )
        except Exception:
            return self.download_url(
                target, tmp_dir, audio_only=True, on_progress=on_progress,
            )

    def probe_duration(self, input_path: str) -> float:
        """尽量用 media_cli probe，失败则回 0。"""
        try:
            info = self.probe_video(input_path)
            return float(getattr(info, "duration_sec", 0.0) or 0.0)
        except Exception:
            return 0.0

    def export_clip(
        self,
        input_path: str,
        start_sec: float,
        end_sec: float,
        output_path: str,
        *,
        reencode: bool = False,
    ) -> str:
        """按时间切一段视频。优先 stream copy，失败再重编码。"""
        if end_sec <= start_sec:
            raise ValueError(f"无效时间段: {start_sec:.3f} → {end_sec:.3f}")
        ffmpeg = _find_ffmpeg()
        duration = end_sec - start_sec
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        def _run(copy: bool) -> subprocess.CompletedProcess:
            cmd = [
                str(ffmpeg), "-y",
                "-ss", f"{max(0.0, start_sec):.3f}",
                "-i", input_path,
                "-t", f"{duration:.3f}",
            ]
            if copy:
                cmd.extend(["-c", "copy", "-avoid_negative_ts", "make_zero"])
            else:
                cmd.extend([*_video_encoder_args(), "-c:a", "aac", "-b:a", "192k"])
            cmd.append(output_path)
            return subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=self._env,
            )

        if not reencode:
            result = _run(True)
            if result.returncode == 0 and os.path.isfile(output_path) and os.path.getsize(output_path) > 0:
                return output_path
        result = _run(False)
        if result.returncode != 0 or not os.path.isfile(output_path):
            raise RuntimeError(result.stderr.strip() or "片段导出失败")
        return output_path

    def concat_clips(self, clip_paths: List[str], output_path: str) -> str:
        """用 concat demuxer 拼接已切片段（优先 copy）。"""
        paths = [p for p in clip_paths if p and os.path.isfile(p)]
        if not paths:
            raise ValueError("没有可拼接的片段")
        if len(paths) == 1:
            shutil.copy2(paths[0], output_path)
            return output_path

        ffmpeg = _find_ffmpeg()
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        list_path = output_path + ".concat.txt"
        try:
            with open(list_path, "w", encoding="utf-8") as f:
                for p in paths:
                    # concat 协议要求正斜杠路径
                    safe = os.path.abspath(p).replace("\\", "/")
                    f.write(f"file '{safe}'\n")

            def _run(copy: bool) -> subprocess.CompletedProcess:
                cmd = [
                    str(ffmpeg), "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", list_path,
                ]
                if copy:
                    cmd.extend(["-c", "copy"])
                else:
                    cmd.extend([*_video_encoder_args(), "-c:a", "aac", "-b:a", "192k"])
                cmd.append(output_path)
                return subprocess.run(
                    cmd, capture_output=True, text=True,
                    encoding="utf-8", errors="replace", env=self._env,
                )

            result = _run(True)
            if result.returncode != 0 or not os.path.isfile(output_path):
                result = _run(False)
            if result.returncode != 0 or not os.path.isfile(output_path):
                raise RuntimeError(result.stderr.strip() or "拼接失败")
            return output_path
        finally:
            try:
                os.remove(list_path)
            except OSError:
                pass

    def export_highlights(
        self,
        input_path: str,
        segments: List[Tuple[float, float]],
        output_dir: str,
        *,
        concat: bool = True,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> Tuple[List[str], str]:
        """
        导出高光片段到目录，并可选拼接成 highlights_merged.mp4。
        返回 (clip_paths, merged_path)；未拼接时 merged_path 为空串。
        """
        if not segments:
            raise ValueError("没有可导出的高光片段")
        os.makedirs(output_dir, exist_ok=True)

        def report(p: float, msg: str):
            if on_progress:
                on_progress(p, msg)

        clips: List[str] = []
        total = len(segments)
        for i, (start, end) in enumerate(segments):
            if end <= start:
                continue
            name = f"highlight_{i + 1:03d}_{start:.1f}-{end:.1f}.mp4"
            out = os.path.join(output_dir, name)
            report(5.0 + i / max(total, 1) * 70.0, f"导出片段 {i + 1}/{total}")
            self.export_clip(input_path, start, end, out)
            clips.append(out)

        if not clips:
            raise RuntimeError("有效片段为空")

        merged = ""
        if concat:
            merged = os.path.join(output_dir, "highlights_merged.mp4")
            report(90.0, "正在拼接成片…")
            self.concat_clips(clips, merged)
        report(100.0, "导出完成")
        return clips, merged

    @staticmethod
    def _parse_silence_intervals(ffmpeg_stderr: str) -> List[Tuple[float, float]]:
        """解析 silencedetect 的 silence_start / silence_end。"""
        import re

        starts: List[float] = []
        ends: List[float] = []
        for line in ffmpeg_stderr.splitlines():
            m = re.search(r"silence_start:\s*([0-9.]+)", line)
            if m:
                starts.append(float(m.group(1)))
                continue
            m = re.search(r"silence_end:\s*([0-9.]+)", line)
            if m:
                ends.append(float(m.group(1)))
        intervals: List[Tuple[float, float]] = []
        for i, s in enumerate(starts):
            e = ends[i] if i < len(ends) else None
            if e is not None and e > s:
                intervals.append((s, e))
        return intervals

    def detect_speech_segments(
        self,
        input_path: str,
        *,
        noise_db: float = -35.0,
        min_silence: float = 0.45,
        min_speech: float = 0.25,
        pad_sec: float = 0.05,
        duration_hint: float = 0.0,
    ) -> List[Tuple[float, float]]:
        """
        用 ffmpeg silencedetect 找静音，反推「有声」区间（紧凑口播用）。
        返回 [(start, end), ...] 秒。
        """
        ffmpeg = _find_ffmpeg()
        duration = duration_hint if duration_hint > 0 else self.probe_duration(input_path)
        af = f"silencedetect=noise={noise_db}dB:d={min_silence:.3f}"
        cmd = [
            str(ffmpeg), "-hide_banner",
            "-i", input_path,
            "-af", af,
            "-f", "null", "-",
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=self._env,
        )
        # silencedetect 写在 stderr；即使 returncode 非 0 也可能有结果
        silences = self._parse_silence_intervals(result.stderr or "")
        if duration <= 0:
            # 兜底：从最后 silence_end 估计
            if silences:
                duration = max(e for _, e in silences)
            else:
                raise RuntimeError("无法探测视频时长，静音检测失败")

        # 静音 → 保留有声段
        keep: List[Tuple[float, float]] = []
        cursor = 0.0
        for s, e in silences:
            if s > cursor + min_speech:
                keep.append((max(0.0, cursor - pad_sec), min(duration, s + pad_sec)))
            cursor = max(cursor, e)
        if duration > cursor + min_speech:
            keep.append((max(0.0, cursor - pad_sec), duration))

        # 合并过近片段
        merged: List[Tuple[float, float]] = []
        for a, b in keep:
            a = max(0.0, a)
            b = min(duration, b)
            if b - a < min_speech:
                continue
            if merged and a - merged[-1][1] < 0.12:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        return merged

    def remove_silence(
        self,
        input_path: str,
        output_path: str,
        *,
        noise_db: float = -35.0,
        min_silence: float = 0.45,
        duration_hint: float = 0.0,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """检测静音并只保留有声段，拼接成紧凑口播 MP4。"""

        def report(p: float, msg: str):
            if on_progress:
                on_progress(p, msg)

        report(5.0, "正在检测静音…")
        segs = self.detect_speech_segments(
            input_path,
            noise_db=noise_db,
            min_silence=min_silence,
            duration_hint=duration_hint,
        )
        if not segs:
            raise RuntimeError("未检测到有效人声段落（可调低静音阈值再试）")

        report(15.0, f"保留 {len(segs)} 段有声内容，开始裁剪…")
        tmp = tempfile.mkdtemp(prefix="music_silence_")
        try:
            clips: List[str] = []
            for i, (s, e) in enumerate(segs):
                clip = os.path.join(tmp, f"keep_{i:04d}.mp4")
                pct = 15.0 + (i / max(len(segs), 1)) * 70.0
                report(pct, f"裁剪 {i + 1}/{len(segs)}")
                self.export_clip(input_path, s, e, clip)
                clips.append(clip)
            report(90.0, "正在拼接紧凑版…")
            self.concat_clips(clips, output_path)
            report(100.0, "完成")
            return output_path
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _escape_subtitles_path(path: str) -> str:
        """FFmpeg subtitles 滤镜路径转义（Windows 盘符冒号等）。"""
        p = os.path.abspath(path).replace("\\", "/")
        p = p.replace("\\", "/")
        p = p.replace(":", r"\:")
        p = p.replace("'", r"\'")
        p = p.replace("[", r"\[")
        p = p.replace("]", r"\]")
        return p

    def export_vertical_short(
        self,
        input_path: str,
        output_path: str,
        *,
        width: int = 1080,
        height: int = 1920,
        crop_bias: str = "center",
        subtitle_path: Optional[str] = None,
        on_progress: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """
        竖屏短视频：缩放到覆盖 9:16 后裁切，可选烧录外挂字幕。
        crop_bias: center | top | bottom（裁切窗在画面上的垂直位置）。
        """
        if not input_path or not os.path.isfile(input_path):
            raise FileNotFoundError(f"输入不存在: {input_path}")
        w = int(width) if int(width) > 0 else 1080
        h = int(height) if int(height) > 0 else 1920
        # 保证偶数（yuv420）
        w -= w % 2
        h -= h % 2
        bias = (crop_bias or "center").strip().lower()
        if bias in ("top", "上", "0"):
            y_expr = "0"
            bias_label = "偏上"
        elif bias in ("bottom", "下", "1"):
            y_expr = "ih-oh"
            bias_label = "偏下"
        else:
            y_expr = "(ih-oh)/2"
            bias_label = "居中"

        def report(p: float, msg: str):
            if on_progress:
                on_progress(p, msg)

        ffmpeg = _find_ffmpeg()
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        # scale 覆盖目标画幅 → crop 到精确 9:16
        vf_parts = [
            f"scale={w}:{h}:force_original_aspect_ratio=increase",
            f"crop={w}:{h}:(iw-ow)/2:{y_expr}",
        ]

        sub_tmp: Optional[str] = None
        if subtitle_path and os.path.isfile(subtitle_path):
            report(8.0, "准备字幕烧录…")
            # 拷到临时 ASCII 名，避免中文路径/空格坑 subtitles 滤镜
            ext = os.path.splitext(subtitle_path)[1].lower() or ".srt"
            if ext not in (".srt", ".ass", ".ssa", ".vtt"):
                ext = ".srt"
            fd, sub_tmp = tempfile.mkstemp(prefix="me_sub_", suffix=ext)
            os.close(fd)
            shutil.copy2(subtitle_path, sub_tmp)
            esc = self._escape_subtitles_path(sub_tmp)
            # 竖屏底部大字号
            style = (
                "FontName=Microsoft YaHei,FontSize=16,"
                "PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,"
                "BorderStyle=1,Outline=2,Shadow=0,"
                "Alignment=2,MarginV=48"
            )
            vf_parts.append(f"subtitles='{esc}':force_style='{style}'")

        vf = ",".join(vf_parts)
        report(12.0, f"竖屏导出 9:16 {w}x{h}（{bias_label}）…")

        cmd = [
            str(ffmpeg), "-y", "-hide_banner", "-stats",
            "-i", input_path,
            "-vf", vf,
            *_video_encoder_args(high_quality=True),
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            output_path,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", env=self._env,
            )
            if result.returncode != 0 or not os.path.isfile(output_path):
                err = (result.stderr or result.stdout or "").strip()
                # 字幕滤镜失败时降级：无字幕再导一次
                if subtitle_path and "subtitles" in vf:
                    report(40.0, "字幕烧录失败，改为无字幕竖屏导出…")
                    vf2 = ",".join(vf_parts[:2])
                    cmd2 = [
                        str(ffmpeg), "-y", "-hide_banner", "-stats",
                        "-i", input_path,
                        "-vf", vf2,
                        *_video_encoder_args(high_quality=True),
                        "-c:a", "aac", "-b:a", "192k",
                        "-movflags", "+faststart",
                        output_path,
                    ]
                    result2 = subprocess.run(
                        cmd2, capture_output=True, text=True,
                        encoding="utf-8", errors="replace", env=self._env,
                    )
                    if result2.returncode != 0 or not os.path.isfile(output_path):
                        raise RuntimeError(
                            (result2.stderr or err or "竖屏导出失败").strip()
                        )
                else:
                    raise RuntimeError(err or "竖屏导出失败")
            report(100.0, "竖屏导出完成")
            return output_path
        finally:
            if sub_tmp:
                try:
                    os.remove(sub_tmp)
                except OSError:
                    pass

    def shutdown(self):
        pass
