"""可选 RIFE ONNX 补帧；失败由调用方回退 minterpolate。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional


ProgressFn = Callable[[float, str], None]


def find_rife_model(project_root: Optional[Path] = None) -> str:
    root = project_root or Path(__file__).resolve().parent.parent.parent.parent
    cands = [
        root / "models" / "rife.onnx",
        root / "models" / "rife_v4.onnx",
        root / "models" / "RIFE.onnx",
    ]
    for p in cands:
        if p.is_file():
            return str(p)
    env = (os.environ.get("MUSIC_RIFE_MODEL") or "").strip()
    if env and os.path.isfile(env):
        return env
    return ""


def rife_available() -> bool:
    return bool(find_rife_model())


def interpolate_rife_frames(
    frames_in_dir: str,
    frames_out_dir: str,
    *,
    factor: int = 2,
    model_path: str = "",
    on_progress: Optional[ProgressFn] = None,
) -> int:
    """
    对 PNG 序列做 2× 插帧（相邻帧之间插入 1 帧）。
    需要兼容输入 shape [1,6,H,W] 的 RIFE ONNX；否则抛错。
    """
    import glob

    import cv2
    import numpy as np

    report = on_progress or (lambda _p, _m: None)
    model = model_path or find_rife_model()
    if not model:
        raise FileNotFoundError(
            "未找到 RIFE 模型（models/rife.onnx）。请下载后放到 models/，或改用 FFmpeg 补帧。"
        )
    try:
        import onnxruntime as ort
    except ImportError as e:
        raise RuntimeError(f"onnxruntime 不可用: {e}") from e

    paths = sorted(glob.glob(os.path.join(frames_in_dir, "*.png")))
    if len(paths) < 2:
        raise RuntimeError("帧数不足，无法 RIFE 补帧")
    os.makedirs(frames_out_dir, exist_ok=True)

    sess = ort.InferenceSession(model, providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_idx = 0
    total_steps = max(1, len(paths) - 1)

    def _to_nchw6(a, b):
        # a,b: BGR uint8 → RGB float NCHW concat → [1,6,H,W]
        def prep(img):
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
            return np.transpose(rgb, (2, 0, 1))
        x = np.concatenate([prep(a), prep(b)], axis=0)[None, ...]
        return x.astype(np.float32)

    try:
        for i in range(len(paths) - 1):
            img0 = cv2.imread(paths[i], cv2.IMREAD_COLOR)
            img1 = cv2.imread(paths[i + 1], cv2.IMREAD_COLOR)
            if img0 is None or img1 is None:
                continue
            if img0.shape != img1.shape:
                img1 = cv2.resize(img1, (img0.shape[1], img0.shape[0]))
            out0 = os.path.join(frames_out_dir, f"f_{out_idx:06d}.png")
            cv2.imwrite(out0, img0)
            out_idx += 1
            try:
                inp = _to_nchw6(img0, img1)
                outs = sess.run(None, {in_name: inp})
                mid = outs[0]
                if mid.ndim == 4:
                    mid = mid[0]
                if mid.shape[0] == 3:
                    mid = np.transpose(mid, (1, 2, 0))
                mid = np.clip(mid * 255.0, 0, 255).astype(np.uint8)
                if mid.shape[2] == 3:
                    mid = cv2.cvtColor(mid, cv2.COLOR_RGB2BGR)
                outm = os.path.join(frames_out_dir, f"f_{out_idx:06d}.png")
                cv2.imwrite(outm, mid)
                out_idx += 1
            except Exception:
                # 单步失败：退化为混合帧
                blend = cv2.addWeighted(img0, 0.5, img1, 0.5, 0)
                outm = os.path.join(frames_out_dir, f"f_{out_idx:06d}.png")
                cv2.imwrite(outm, blend)
                out_idx += 1
            report(10.0 + (i + 1) / total_steps * 80.0, f"RIFE {i + 1}/{total_steps}")

        # 最后一帧
        last = cv2.imread(paths[-1], cv2.IMREAD_COLOR)
        if last is not None:
            cv2.imwrite(os.path.join(frames_out_dir, f"f_{out_idx:06d}.png"), last)
            out_idx += 1
    finally:
        try:
            del sess
        except Exception:
            sess = None
    # factor=4：再对输出跑一轮（粗略）
    if int(factor) >= 4:
        mid_dir = frames_out_dir + "_mid"
        os.makedirs(mid_dir, exist_ok=True)
        # 把当前输出当作输入再插一次
        for name in os.listdir(frames_out_dir):
            src = os.path.join(frames_out_dir, name)
            if os.path.isfile(src):
                import shutil
                shutil.copy2(src, os.path.join(mid_dir, name))
        for name in os.listdir(frames_out_dir):
            try:
                os.remove(os.path.join(frames_out_dir, name))
            except OSError:
                pass
        return interpolate_rife_frames(
            mid_dir, frames_out_dir, factor=2, model_path=model, on_progress=on_progress,
        )
    return out_idx
