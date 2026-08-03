"""Demucs 人声分离（可选）。源码在 third_party/demucs，权重进 .cache/demucs。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

ProgressFn = Callable[[float, str], None]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def demucs_vendor_dir() -> Path:
    return _project_root() / "third_party" / "demucs"


def demucs_cache_dir() -> Path:
    d = _project_root() / ".cache" / "demucs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_demucs_on_path() -> None:
    """未 pip 安装时，把仓库源码加入 sys.path（仍需自行有 torch）。"""
    vendor = demucs_vendor_dir()
    pkg = vendor / "demucs"
    if pkg.is_dir():
        root = str(vendor)
        if root not in sys.path:
            sys.path.insert(0, root)


@dataclass
class DemucsStatus:
    available: bool
    detail: str
    torch_version: str = ""
    cuda: bool = False
    demucs_version: str = ""


def probe_demucs() -> DemucsStatus:
    ensure_demucs_on_path()
    try:
        import torch
    except Exception as e:
        return DemucsStatus(
            False,
            f"未安装 PyTorch。可选运行 scripts\\setup_demucs.bat（体积大）。({e})",
        )
    try:
        import demucs
        from demucs.api import Separator  # noqa: F401
    except Exception as e:
        return DemucsStatus(
            False,
            f"Demucs 不可用：{e}。请运行 scripts\\setup_demucs.bat",
            torch_version=getattr(torch, "__version__", ""),
            cuda=bool(torch.cuda.is_available()),
        )
    return DemucsStatus(
        True,
        "Demucs 已就绪（首次分轨会下载权重到 .cache/demucs）",
        torch_version=torch.__version__,
        cuda=bool(torch.cuda.is_available()),
        demucs_version=getattr(demucs, "__version__", "?"),
    )


@dataclass
class SeparateResult:
    output_dir: str
    stems: Dict[str, str] = field(default_factory=dict)
    vocals_path: str = ""
    instrumental_path: str = ""


def separate_stems(
    input_path: str,
    output_dir: str,
    *,
    model: str = "htdemucs",
    device: str = "",
    two_stems: str = "vocals",
    on_progress: Optional[ProgressFn] = None,
) -> SeparateResult:
    """
    分离音轨。默认导出 vocals + 其余合成伴奏（karaoke）。
    two_stems: 传给 Demucs 的两轨名（vocals → vocals / no_vocals）。
    """
    if not os.path.isfile(input_path):
        raise FileNotFoundError(input_path)
    st = probe_demucs()
    if not st.available:
        raise RuntimeError(st.detail)

    ensure_demucs_on_path()
    import torch
    from demucs.api import Separator, save_audio

    report = on_progress or (lambda _p, _m: None)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # 让 torch hub / demucs 缓存落到项目 .cache，便于打包拷贝
    cache = demucs_cache_dir()
    os.environ.setdefault("TORCH_HOME", str(cache / "torch"))
    # demucs RemoteRepo 仍按自己的路径下；权重会进用户目录或 TORCH_HOME

    dev = device.strip() or ("cuda" if torch.cuda.is_available() else "cpu")
    report(5.0, f"加载模型 {model}（{dev}）…")

    def _cb(info: dict):
        state = info.get("state")
        if state == "start":
            off = float(info.get("segment_offset") or 0)
            total = max(1.0, float(info.get("audio_length") or 1))
            p = 10.0 + 80.0 * min(1.0, off / total)
            report(p, f"分轨中… {p:.0f}%")

    sep = Separator(
        model=model,
        device=dev,
        progress=False,
        callback=_cb,
        shifts=1,
        split=True,
    )
    report(12.0, "读取音频并推理（首次需下载权重）…")
    _origin, stems = sep.separate_audio_file(Path(input_path))

    stem = Path(input_path).stem
    paths: Dict[str, str] = {}
    for name, wav in stems.items():
        dest = out / f"{stem}_{name}.wav"
        save_audio(wav, dest, samplerate=sep.samplerate)
        paths[name] = str(dest.resolve())
        report(90.0, f"已写 {dest.name}")

    vocals = paths.get("vocals", "")
    # 伴奏 = 非人声之和
    instrumental = ""
    others = [k for k in paths if k != "vocals"]
    if others:
        try:
            mix = None
            for k in others:
                t = stems[k]
                mix = t if mix is None else mix + t
            if mix is not None:
                dest = out / f"{stem}_no_vocals.wav"
                save_audio(mix, dest, samplerate=sep.samplerate)
                instrumental = str(dest.resolve())
                paths["no_vocals"] = instrumental
        except Exception:
            instrumental = paths.get("other", "") or (paths[others[0]] if others else "")

    report(100.0, f"分轨完成 → {out}")
    return SeparateResult(
        output_dir=str(out.resolve()),
        stems=paths,
        vocals_path=vocals,
        instrumental_path=instrumental,
    )
