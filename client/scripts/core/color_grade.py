"""一键调色 / LUT：与 FrameProcessor 同套预设，导出走 FFmpeg lut3d。"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

ProgressFn = Callable[[float, str], None]

# 与 C++ FrameProcessor Warm/Cool/Vintage 对齐的显示名
PRESETS: Dict[str, str] = {
    "warm": "电影暖调",
    "cool": "冷调",
    "vintage": "复古",
}

# 3x3 矩阵（行主序）+ RGB 偏置；与 frame_processor.cpp 一致
_MATRICES: Dict[str, Tuple[Tuple[float, ...], Tuple[float, float, float], float, float]] = {
    # matrix(9), (addR,addG,addB), contrast, lift
    "warm": (
        (1.12, 0.06, 0.02, 0.04, 1.04, 0.00, 0.00, 0.02, 0.88),
        (6.0, 2.0, -4.0),
        1.06,
        2.0,
    ),
    "cool": (
        (0.90, 0.02, 0.04, 0.02, 1.02, 0.06, 0.04, 0.08, 1.14),
        (-4.0, 0.0, 8.0),
        1.04,
        -2.0,
    ),
    "vintage": (
        (0.55, 0.65, 0.20, 0.35, 0.55, 0.18, 0.20, 0.35, 0.22),
        (12.0, 8.0, 4.0),
        0.88,
        10.0,
    ),
}


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _find_ffmpeg() -> Path:
    root = _project_root()
    for p in (
        root / "third_party" / "ffmpeg" / "x64" / "bin" / "ffmpeg.exe",
        root / "third_party" / "ffmpeg" / "x86" / "bin" / "ffmpeg.exe",
        root / "build_x64" / "bin" / "Release" / "ffmpeg.exe",
    ):
        if p.is_file():
            return p
    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        return Path(found)
    raise FileNotFoundError("未找到 ffmpeg.exe")


def normalize_preset(name: str) -> str:
    k = (name or "").strip().lower()
    aliases = {
        "电影暖调": "warm",
        "cinema_warm": "warm",
        "movie_warm": "warm",
        "冷调": "cool",
        "cinema_cool": "cool",
        "cold": "cool",
        "复古": "vintage",
        "retro": "vintage",
        "fade": "vintage",
    }
    k = aliases.get(k, k)
    if k not in _MATRICES:
        raise ValueError(f"未知调色预设: {name}（可选: warm/cool/vintage）")
    return k


def _transform_rgb01(r: float, g: float, b: float, preset: str) -> Tuple[float, float, float]:
    m, add, contrast, lift = _MATRICES[preset]
    # 0–1 → 应用与 8bit 偏置等价的缩放
    R = r * 255.0
    G = g * 255.0
    B = b * 255.0
    rr = R * m[0] + G * m[1] + B * m[2] + add[0]
    gg = R * m[3] + G * m[4] + B * m[5] + add[1]
    bb = R * m[6] + G * m[7] + B * m[8] + add[2]
    rr = (rr - 128.0) * contrast + 128.0 + lift
    gg = (gg - 128.0) * contrast + 128.0 + lift
    bb = (bb - 128.0) * contrast + 128.0 + lift
    return (
        max(0.0, min(1.0, rr / 255.0)),
        max(0.0, min(1.0, gg / 255.0)),
        max(0.0, min(1.0, bb / 255.0)),
    )


def ensure_cube(preset: str, size: int = 17) -> Path:
    """生成 / 缓存 .cube，供 FFmpeg lut3d 使用。"""
    preset = normalize_preset(preset)
    size = max(5, min(33, int(size)))
    out_dir = _project_root() / ".cache" / "luts"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{preset}_{size}.cube"
    if path.is_file() and path.stat().st_size > 200:
        return path

    lines: List[str] = [
        f'TITLE "{PRESETS.get(preset, preset)}"',
        f"LUT_3D_SIZE {size}",
    ]
    # cube 顺序：R 最快变化，然后 G，然后 B（Adobe/FFmpeg 常见）
    denom = float(size - 1)
    for bi in range(size):
        b = bi / denom
        for gi in range(size):
            g = gi / denom
            for ri in range(size):
                r = ri / denom
                rr, gg, bb = _transform_rgb01(r, g, b, preset)
                lines.append(f"{rr:.6f} {gg:.6f} {bb:.6f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def apply_grade_opencv_bgr(img_bgr, preset: str):
    """就地/返回调色后的 BGR uint8 图（预览用，需 opencv）。"""
    import numpy as np

    preset = normalize_preset(preset)
    m, add, contrast, lift = _MATRICES[preset]
    f = img_bgr.astype(np.float32)
    # OpenCV 是 BGR
    B, G, R = f[:, :, 0], f[:, :, 1], f[:, :, 2]
    rr = R * m[0] + G * m[1] + B * m[2] + add[0]
    gg = R * m[3] + G * m[4] + B * m[5] + add[1]
    bb = R * m[6] + G * m[7] + B * m[8] + add[2]
    rr = (rr - 128.0) * contrast + 128.0 + lift
    gg = (gg - 128.0) * contrast + 128.0 + lift
    bb = (bb - 128.0) * contrast + 128.0 + lift
    out = np.stack([bb, gg, rr], axis=2)
    return np.clip(out, 0, 255).astype(np.uint8)


def grade_image_file(input_path: str, output_path: str, preset: str) -> str:
    """图片调色：优先 OpenCV；失败则 FFmpeg lut3d。"""
    preset = normalize_preset(preset)
    try:
        import cv2
        import numpy as np

        data = np.fromfile(input_path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise RuntimeError("无法解码图片")
        out = apply_grade_opencv_bgr(img, preset)
        ext = os.path.splitext(output_path)[1].lower() or ".png"
        ok, buf = cv2.imencode(ext if ext in (".png", ".jpg", ".jpeg", ".webp") else ".png", out)
        if not ok:
            raise RuntimeError("编码失败")
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        buf.tofile(output_path)
        return output_path
    except Exception:
        return grade_with_ffmpeg(input_path, output_path, preset)


def grade_with_ffmpeg(
    input_path: str,
    output_path: str,
    preset: str,
    *,
    start_sec: float = 0.0,
    end_sec: float = 0.0,
    on_progress: Optional[ProgressFn] = None,
) -> str:
    """
    FFmpeg lut3d 导出（图片或视频）。
    Windows 下 .cube 放在临时目录用相对名，避免盘符冒号坑滤镜语法。
    """
    ffmpeg = _find_ffmpeg()
    preset = normalize_preset(preset)
    report = on_progress or (lambda _p, _m: None)
    cube_src = ensure_cube(preset)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="me_lut_") as td:
        td_path = Path(td)
        cube_name = "grade.cube"
        shutil.copy2(cube_src, td_path / cube_name)
        # 输入也拷到短路径，减少中文路径问题
        in_name = "input" + (Path(input_path).suffix or ".mp4")
        shutil.copy2(input_path, td_path / in_name)
        out_name = "out" + (Path(output_path).suffix or ".mp4")

        is_image = Path(input_path).suffix.lower() in {
            ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff",
        }
        report(8.0, f"lut3d {PRESETS.get(preset, preset)}…")

        cmd: List[str] = [str(ffmpeg), "-hide_banner", "-y"]
        if start_sec > 0 and not is_image:
            cmd.extend(["-ss", f"{start_sec:.3f}"])
        cmd.extend(["-i", in_name])
        if end_sec > start_sec and not is_image:
            cmd.extend(["-t", f"{max(0.1, end_sec - start_sec):.3f}"])

        # lut3d 需要相对路径；插值 tetrahedral
        vf = f"lut3d=file={cube_name}:interp=tetrahedral"
        if is_image:
            cmd.extend(["-vf", vf, "-frames:v", "1", out_name])
        else:
            cmd.extend([
                "-vf", vf,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                out_name,
            ])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(td_path),
            timeout=3600,
        )
        produced = td_path / out_name
        if result.returncode != 0 or not produced.is_file():
            # 回退：无 lut3d 时用 colorbalance（部分精简包）
            report(20.0, "lut3d 失败，尝试 colorbalance 回退…")
            vf2 = {
                "warm": "colorbalance=rs=0.18:gs=0.04:bs=-0.12:rm=0.10:bm=-0.08",
                "cool": "colorbalance=rs=-0.12:bs=0.18:rm=-0.06:bm=0.12",
                "vintage": "colorbalance=rs=0.08:gs=0.04:bs=-0.04,eq=contrast=0.88:brightness=0.04:saturation=0.75",
            }[preset]
            cmd2 = [str(ffmpeg), "-hide_banner", "-y", "-i", in_name, "-vf", vf2]
            if is_image:
                cmd2.extend(["-frames:v", "1", out_name])
            else:
                if start_sec > 0:
                    cmd2 = [str(ffmpeg), "-hide_banner", "-y", "-ss", f"{start_sec:.3f}",
                            "-i", in_name]
                    if end_sec > start_sec:
                        cmd2.extend(["-t", f"{max(0.1, end_sec - start_sec):.3f}"])
                    cmd2.extend(["-vf", vf2, "-c:v", "libx264", "-preset", "veryfast",
                                 "-crf", "18", "-c:a", "aac", "-b:a", "192k", out_name])
                else:
                    cmd2.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                                 "-c:a", "aac", "-b:a", "192k", out_name])
            result2 = subprocess.run(
                cmd2, capture_output=True, text=True, encoding="utf-8",
                errors="replace", cwd=str(td_path), timeout=3600,
            )
            if result2.returncode != 0 or not produced.is_file():
                detail = (result.stderr or result2.stderr or "")[-700:]
                raise RuntimeError(f"调色导出失败: {detail}")

        shutil.copy2(produced, output_path)
    report(100.0, f"调色完成: {os.path.basename(output_path)}")
    return output_path


def list_presets() -> Sequence[Tuple[str, str]]:
    return [(k, PRESETS[k]) for k in ("warm", "cool", "vintage")]
