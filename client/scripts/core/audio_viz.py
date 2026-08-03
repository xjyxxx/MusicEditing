"""波形 / 响度可视化与「响度高潮」检测 — 纯 FFmpeg showwavespic + ebur128。"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

ProgressFn = Callable[[float, str], None]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _find_ffmpeg() -> Path:
    root = _project_root()
    for p in (
        root / "third_party" / "ffmpeg" / "x64" / "bin" / "ffmpeg.exe",
        root / "third_party" / "ffmpeg" / "x86" / "bin" / "ffmpeg.exe",
        root / "build_x64" / "bin" / "Release" / "ffmpeg.exe",
        root / "build" / "bin" / "Release" / "ffmpeg.exe",
    ):
        if p.is_file():
            return p
    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        return Path(found)
    raise FileNotFoundError("未找到 ffmpeg.exe")


def _cache_dir() -> Path:
    d = _project_root() / ".cache" / "audio_viz"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _media_cache_key(media_path: str) -> str:
    p = Path(media_path)
    st = p.stat()
    raw = f"{p.resolve()}|{st.st_mtime_ns}|{st.st_size}"
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:20]


@dataclass
class LoudnessSample:
    """瞬时响度采样（约 100ms 一帧）。"""

    t: float
    momentary_lufs: float  # M
    shortterm_lufs: float = -70.0  # S
    integrated_lufs: float = -70.0  # I


@dataclass
class AudioVizResult:
    media_path: str
    duration_hint: float = 0.0
    waveform_png: str = ""
    samples: List[LoudnessSample] = field(default_factory=list)
    integrated_lufs: float = -70.0
    lra: float = 0.0
    true_peak_dbfs: Optional[float] = None

    @property
    def ok(self) -> bool:
        return bool(self.waveform_png and os.path.isfile(self.waveform_png)) or bool(self.samples)


_RE_FRAME = re.compile(r"pts_time:\s*([0-9.+-eE]+)")
_RE_M = re.compile(r"lavfi\.r128\.M=\s*([0-9.+-eE]+)")
_RE_S = re.compile(r"lavfi\.r128\.S=\s*([0-9.+-eE]+)")
_RE_I = re.compile(r"lavfi\.r128\.I=\s*([0-9.+-eE]+)")
_RE_LRA = re.compile(r"LRA:\s*([0-9.+-eE]+)\s*LU", re.I)
_RE_I_SUM = re.compile(r"I:\s*([0-9.+-eE]+)\s*LUFS", re.I)
_RE_PEAK = re.compile(r"Peak:\s*([0-9.+-eE]+)\s*dBFS", re.I)


def parse_ebur128_metadata(text: str) -> Tuple[List[LoudnessSample], float, float]:
    """解析 ametadata=print 输出 → (samples, last_I, LRA)。"""
    samples: List[LoudnessSample] = []
    cur_t: Optional[float] = None
    cur_m = cur_s = cur_i = None
    integrated = -70.0
    lra = 0.0

    def flush():
        nonlocal cur_t, cur_m, cur_s, cur_i, integrated
        if cur_t is None or cur_m is None:
            cur_t = cur_m = cur_s = cur_i = None
            return
        m_val = float(cur_m)
        if m_val < -69.0:
            cur_t = cur_m = cur_s = cur_i = None
            return
        s_val = float(cur_s) if cur_s is not None else m_val
        i_val = float(cur_i) if cur_i is not None else integrated
        integrated = i_val
        samples.append(
            LoudnessSample(
                t=float(cur_t),
                momentary_lufs=m_val,
                shortterm_lufs=s_val if s_val > -69.0 else m_val,
                integrated_lufs=i_val,
            )
        )
        cur_t = cur_m = cur_s = cur_i = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "pts_time:" in line or line.startswith("frame:"):
            flush()
            mt = _RE_FRAME.search(line)
            if mt:
                cur_t = float(mt.group(1))
            continue
        mm = _RE_M.search(line)
        if mm:
            cur_m = mm.group(1)
            continue
        ms = _RE_S.search(line)
        if ms:
            cur_s = ms.group(1)
            continue
        mi = _RE_I.search(line)
        if mi:
            cur_i = mi.group(1)
            continue
        m = _RE_LRA.search(line)
        if m:
            try:
                lra = float(m.group(1))
            except ValueError:
                pass
        m = _RE_I_SUM.search(line)
        if m and "lavfi" not in line:
            try:
                integrated = float(m.group(1))
            except ValueError:
                pass
    flush()
    if samples:
        integrated = samples[-1].integrated_lufs
    return samples, integrated, lra


def generate_waveform_png(
    media_path: str,
    out_png: str,
    *,
    width: int = 1280,
    height: int = 72,
    color: str = "E8A45C",
) -> str:
    """FFmpeg showwavespic → 单张 PNG（相对路径写盘，避免 Windows 盘符冒号坑）。"""
    ffmpeg = _find_ffmpeg()
    out_path = Path(out_png)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    w = max(200, int(width))
    h = max(32, int(height))
    # 在输出目录下用短相对名，cwd=该目录
    work = out_path.parent
    tmp_name = "_wave_tmp.png"
    color = (color or "E8A45C").lstrip("#")
    fc = (
        f"aformat=channel_layouts=mono,"
        f"showwavespic=s={w}x{h}:colors={color}:scale=sqrt:filter=peak"
    )
    cmd = [
        str(ffmpeg), "-hide_banner", "-y",
        "-i", str(Path(media_path).resolve()),
        "-filter_complex", fc,
        "-frames:v", "1",
        "-update", "1",
        tmp_name,
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(work),
        timeout=600,
    )
    tmp_path = work / tmp_name
    if result.returncode != 0 or not tmp_path.is_file() or tmp_path.stat().st_size < 64:
        detail = (result.stderr or result.stdout or "")[-500:]
        raise RuntimeError(f"showwavespic 失败: {detail}")
    if tmp_path.resolve() != out_path.resolve():
        if out_path.exists():
            out_path.unlink()
        tmp_path.replace(out_path)
    return str(out_path.resolve())


def analyze_ebur128(
    media_path: str,
    *,
    on_progress: Optional[ProgressFn] = None,
) -> Tuple[List[LoudnessSample], float, float, Optional[float]]:
    """
    ebur128 + ametadata=print → 时间轴瞬时响度。
    返回 (samples, integrated_lufs, lra, true_peak_dbfs)。
    """
    ffmpeg = _find_ffmpeg()
    report = on_progress or (lambda _p, _m: None)
    report(10.0, "EBU R128 响度分析…")
    with tempfile.TemporaryDirectory(prefix="me_ebur_") as td:
        meta_name = "ebur_meta.txt"
        # peak=true 以便 Summary 含 True peak
        af = "ebur128=metadata=1:peak=true,ametadata=mode=print:file=" + meta_name
        cmd = [
            str(ffmpeg), "-hide_banner",
            "-i", str(Path(media_path).resolve()),
            "-af", af,
            "-f", "null", "-",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=td,
            timeout=3600,
        )
        meta_path = Path(td) / meta_name
        meta_text = meta_path.read_text(encoding="utf-8", errors="replace") if meta_path.is_file() else ""
        # Summary 在 stderr
        combined = meta_text + "\n" + (result.stderr or "")
        samples, integrated, lra = parse_ebur128_metadata(combined)
        peak = None
        m = _RE_PEAK.search(result.stderr or "")
        if m:
            try:
                peak = float(m.group(1))
            except ValueError:
                peak = None
        if not samples and result.returncode != 0:
            raise RuntimeError(
                f"ebur128 失败: {(result.stderr or '')[-600:]}"
            )
        report(90.0, f"响度采样 {len(samples)} 点，I={integrated:.1f} LUFS")
        return samples, integrated, lra, peak


def analyze_media_audio(
    media_path: str,
    *,
    wave_width: int = 1280,
    wave_height: int = 72,
    force: bool = False,
    on_progress: Optional[ProgressFn] = None,
) -> AudioVizResult:
    """生成波形图 + ebur128 曲线（带磁盘缓存）。"""
    if not os.path.isfile(media_path):
        raise FileNotFoundError(media_path)
    report = on_progress or (lambda _p, _m: None)
    key = _media_cache_key(media_path)
    cache = _cache_dir()
    wave_path = cache / f"{key}_wave.png"
    meta_cache = cache / f"{key}_ebur.txt"

    result = AudioVizResult(media_path=media_path)

    if force or not wave_path.is_file():
        report(5.0, "生成波形 showwavespic…")
        generate_waveform_png(
            media_path, str(wave_path), width=wave_width, height=wave_height
        )
    result.waveform_png = str(wave_path.resolve())

    samples: List[LoudnessSample] = []
    integrated = -70.0
    lra = 0.0
    peak = None
    if not force and meta_cache.is_file():
        text = meta_cache.read_text(encoding="utf-8", errors="replace")
        samples, integrated, lra = parse_ebur128_metadata(text)
        # 缓存文件不含 Summary 时仍可用 samples
    if force or not samples:
        report(20.0, "分析响度 ebur128…")
        samples, integrated, lra, peak = analyze_ebur128(media_path, on_progress=report)
        # 写回简化缓存
        lines = []
        for s in samples:
            lines.append(f"pts_time:{s.t:.3f}")
            lines.append(f"lavfi.r128.M={s.momentary_lufs:.3f}")
            lines.append(f"lavfi.r128.S={s.shortterm_lufs:.3f}")
            lines.append(f"lavfi.r128.I={s.integrated_lufs:.3f}")
        lines.append(f"I:         {integrated:.3f} LUFS")
        lines.append(f"LRA:         {lra:.3f} LU")
        if peak is not None:
            lines.append(f"Peak:      {peak:.3f} dBFS")
        meta_cache.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result.samples = samples
    result.integrated_lufs = integrated
    result.lra = lra
    result.true_peak_dbfs = peak
    if samples:
        result.duration_hint = max(s.t for s in samples)
    report(100.0, "音频可视化就绪")
    return result


def find_loudness_climaxes(
    samples: Sequence[LoudnessSample],
    *,
    duration_sec: float = 0.0,
    min_duration: float = 3.0,
    max_duration: float = 60.0,
    sensitivity: float = 0.5,
    max_segments: int = 24,
) -> List[Tuple[float, float, float]]:
    """
    按瞬时响度 M 找「高潮」区间。
    返回 [(start, end, score), ...]，score 约 0～1。
    sensitivity: 0=少而严，1=多而松。
    """
    if not samples:
        return []
    vals = [s.momentary_lufs for s in samples]
    times = [s.t for s in samples]
    # 有效动态范围
    lo = sorted(vals)[max(0, int(len(vals) * 0.1))]
    hi = sorted(vals)[min(len(vals) - 1, int(len(vals) * 0.95))]
    if hi - lo < 1.0:
        hi = lo + 6.0
    # 敏感度 → 分位数阈值（高敏感=更低阈值=更多段）
    sens = max(0.0, min(1.0, float(sensitivity)))
    pct = 0.92 - sens * 0.35  # 0.92 … 0.57
    thr = sorted(vals)[min(len(vals) - 1, int(len(vals) * pct))]
    thr = max(thr, lo + (hi - lo) * (0.55 - sens * 0.25))

    # 二值掩码
    mask = [v >= thr for v in vals]
    # 合并邻近 True
    regions: List[Tuple[int, int]] = []
    i = 0
    n = len(mask)
    while i < n:
        if not mask[i]:
            i += 1
            continue
        j = i
        while j < n and mask[j]:
            j += 1
        regions.append((i, j - 1))
        i = j

    # 扩展到 min_duration，裁到 max_duration，按峰评分
    dur = duration_sec if duration_sec > 0 else (times[-1] + 0.1)
    out: List[Tuple[float, float, float]] = []
    for a, b in regions:
        t0 = times[a]
        t1 = times[b]
        # 向两侧扩一点
        pad = 0.35
        t0 = max(0.0, t0 - pad)
        t1 = min(dur, t1 + pad)
        length = t1 - t0
        if length < min_duration:
            mid = 0.5 * (t0 + t1)
            t0 = max(0.0, mid - min_duration * 0.5)
            t1 = min(dur, t0 + min_duration)
            if t1 - t0 < min_duration * 0.8:
                continue
        if t1 - t0 > max_duration:
            # 取峰值附近窗口
            peak_i = max(range(a, b + 1), key=lambda k: vals[k])
            mid = times[peak_i]
            t0 = max(0.0, mid - max_duration * 0.45)
            t1 = min(dur, t0 + max_duration)
        peak_m = max(vals[a: b + 1])
        score = max(0.05, min(1.0, (peak_m - lo) / max(1e-3, hi - lo)))
        out.append((t0, t1, score))

    # 按分数排序，去重叠，截断
    out.sort(key=lambda x: x[2], reverse=True)
    kept: List[Tuple[float, float, float]] = []
    for seg in out:
        if any(not (seg[1] <= k[0] or seg[0] >= k[1]) for k in kept):
            # 重叠则跳过较低分
            overlap = False
            for k in kept:
                inter = min(seg[1], k[1]) - max(seg[0], k[0])
                if inter > 0.5 * min(seg[1] - seg[0], k[1] - k[0]):
                    overlap = True
                    break
            if overlap:
                continue
        kept.append(seg)
        if len(kept) >= max_segments:
            break
    kept.sort(key=lambda x: x[0])
    return kept
