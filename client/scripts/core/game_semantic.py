"""游戏高光轻量语义层：切点 + 运动/闪光 + 可选 game_event.onnx / HUD。

优先级：
1. models/game_event.onnx（若存在，ORT 推理抬分；可用 make_game_event_stub_onnx.py 生成 stub）
2. 否则 OpenCV「击杀字/血条感」HUD 启发式（顶栏/角标高对比区域）
3. 始终融合运动能量 + 亮度突变

说明：仓库 stub / HUD **不是**商业击杀检测；真模型请覆盖同名 ONNX。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from core.app_logger import setup_logging

log = setup_logging("GameSemantic")

ProgressCb = Callable[[float, str], None]
Segment = Tuple[float, float, float]  # start, end, score


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def game_event_model_path() -> Optional[str]:
    p = _project_root() / "models" / "game_event.onnx"
    return str(p) if p.is_file() else None


def _sample_motion_flash(
    video_path: str,
    centers: Sequence[float],
    *,
    window: float = 0.35,
) -> List[float]:
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return [0.5] * len(centers)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    scores: List[float] = []
    prev_gray = None
    prev_mean = None

    for t in centers:
        t0 = max(0.0, float(t) - window)
        frame_idx = int(t0 * fps)
        if total > 0:
            frame_idx = min(frame_idx, max(0, total - 3))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        motion = 0.0
        flash = 0.0
        samples = 0
        for _ in range(6):
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            mean = float(np.mean(gray))
            if prev_gray is not None:
                diff = cv2.absdiff(gray, prev_gray)
                motion = max(motion, float(np.mean(diff)) / 255.0)
            if prev_mean is not None:
                flash = max(flash, abs(mean - prev_mean) / 255.0)
            prev_gray = gray
            prev_mean = mean
            samples += 1
        if samples <= 0:
            scores.append(0.4)
            continue
        s = 0.35 * min(1.0, motion * 4.0) + 0.45 * min(1.0, flash * 6.0) + 0.20
        scores.append(min(0.99, max(0.15, s)))

    cap.release()
    return scores


def _hud_kill_scores(
    video_path: str,
    centers: Sequence[float],
) -> List[float]:
    """顶栏/角标高饱和对比 →「击杀字/血条」启发式 0..1。"""
    import cv2
    import numpy as np

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return [0.45] * len(centers)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    out: List[float] = []
    for t in centers:
        idx = int(float(t) * fps)
        if total > 0:
            idx = min(max(0, idx), total - 1)
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            out.append(0.4)
            continue
        h, w = frame.shape[:2]
        # 顶 18% + 右上角 22%×18%（击杀播报常见区）
        top = frame[0: max(8, int(h * 0.18)), :]
        tr = frame[0: max(8, int(h * 0.18)), max(0, int(w * 0.78)):]
        hsv = cv2.cvtColor(top, cv2.COLOR_BGR2HSV)
        sat = float(np.mean(hsv[:, :, 1])) / 255.0
        val = float(np.std(hsv[:, :, 2])) / 128.0
        hsv2 = cv2.cvtColor(tr, cv2.COLOR_BGR2HSV)
        # 偏红/黄（击杀字常见）
        hue = hsv2[:, :, 0]
        redish = float(np.mean(((hue < 12) | (hue > 170)).astype(np.float32)))
        edge = cv2.Canny(cv2.cvtColor(tr, cv2.COLOR_BGR2GRAY), 80, 160)
        edge_d = float(np.mean(edge)) / 255.0
        s = 0.25 * sat + 0.25 * min(1.0, val) + 0.30 * redish + 0.20 * edge_d
        out.append(min(0.99, max(0.12, s)))
    cap.release()
    return out


def _onnx_event_scores(
    video_path: str,
    centers: Sequence[float],
    model_path: str,
) -> Optional[List[float]]:
    """可选 game_event.onnx：输入图像 → 标量/二分类概率。失败返回 None。"""
    try:
        import cv2
        import numpy as np
        import onnxruntime as ort
    except Exception as e:
        log.info("game_event.onnx 跳过（依赖不可用）: %s", e)
        return None

    try:
        sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        inp = sess.get_inputs()[0]
        in_name = inp.name
        shape = list(inp.shape)
        # 期望 NCHW 或 NHWC；缺维用默认
        h = 64
        w = 64
        nchw = True
        if len(shape) == 4:
            if shape[1] == 3 or (isinstance(shape[1], str) or shape[1] is None):
                # maybe NCHW
                try:
                    h = int(shape[2]) if shape[2] not in (None, "height") else 64
                    w = int(shape[3]) if shape[3] not in (None, "width") else 64
                    nchw = True
                except (TypeError, ValueError):
                    h, w, nchw = 64, 64, True
            elif shape[-1] == 3:
                try:
                    h = int(shape[1]) if not isinstance(shape[1], str) else 64
                    w = int(shape[2]) if not isinstance(shape[2], str) else 64
                except (TypeError, ValueError):
                    h, w = 64, 64
                nchw = False
    except Exception as e:
        log.warning("加载 game_event.onnx 失败: %s", e)
        return None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    scores: List[float] = []
    try:
        for t in centers:
            idx = int(float(t) * fps)
            if total > 0:
                idx = min(max(0, idx), total - 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                scores.append(0.45)
                continue
            fh, fw = frame.shape[:2]
            # 顶栏 ROI
            crop = frame[0: max(8, int(fh * 0.22)), :]
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            rgb = cv2.resize(rgb, (w, h), interpolation=cv2.INTER_AREA)
            x = rgb.astype("float32") / 255.0
            if nchw:
                x = np.transpose(x, (2, 0, 1))[None, ...]
            else:
                x = x[None, ...]
            outs = sess.run(None, {in_name: x})
            y = outs[0]
            val = float(np.ravel(y)[0])
            # sigmoid if logits-like
            if val < 0.0 or val > 1.0:
                val = 1.0 / (1.0 + float(np.exp(-val)))
            scores.append(min(0.99, max(0.05, val)))
    except Exception as e:
        log.warning("game_event.onnx 推理失败，回退 HUD: %s", e)
        cap.release()
        try:
            del sess
        except Exception:
            pass
        return None
    cap.release()
    try:
        del sess
    except Exception:
        pass
    log.info("game_event.onnx 打分 n=%d", len(scores))
    return scores


def enrich_game_segments(
    video_path: str,
    segments: List[Segment],
    *,
    on_progress: Optional[ProgressCb] = None,
    top_k: int = 0,
) -> List[Segment]:
    """对场景段做轻量语义重打分并重排。"""
    if not segments or not video_path or not os.path.isfile(video_path):
        return list(segments)

    def report(p: float, msg: str) -> None:
        if on_progress:
            on_progress(p, msg)

    report(5.0, "游戏语义：运动/闪光打分…")
    centers = [(s + e) * 0.5 for s, e, _ in segments]
    cut_pts = [s for s, _e, _ in segments]
    try:
        mid_scores = _sample_motion_flash(video_path, centers)
        cut_scores = _sample_motion_flash(video_path, cut_pts, window=0.2)
    except Exception as e:
        log.warning("语义打分失败，保留原分: %s", e)
        return list(segments)

    report(40.0, "游戏语义：击杀感 / 事件模型…")
    event_scores: Optional[List[float]] = None
    onnx_path = game_event_model_path()
    source = "hud"
    if onnx_path:
        event_scores = _onnx_event_scores(video_path, centers, onnx_path)
        if event_scores is not None:
            source = "onnx"
    if event_scores is None:
        try:
            event_scores = _hud_kill_scores(video_path, centers)
        except Exception as e:
            log.warning("HUD 打分失败: %s", e)
            event_scores = [0.5] * len(centers)

    out: List[Segment] = []
    for i, (s, e, base) in enumerate(segments):
        sem = 0.40 * mid_scores[i] + 0.25 * cut_scores[i] + 0.35 * event_scores[i]
        score = min(0.99, 0.35 * float(base) + 0.65 * sem)
        out.append((s, e, score))

    out.sort(key=lambda x: x[2], reverse=True)
    if top_k > 0 and len(out) > top_k:
        out = out[:top_k]
    out.sort(key=lambda x: x[0])
    report(100.0, f"语义重排完成：{len(out)} 段（{source}）")
    log.info(
        "语义打分 path=%s n=%d source=%s top3=%s",
        video_path,
        len(out),
        source,
        [(round(a, 2), round(b, 2), round(c, 2)) for a, b, c in out[:3]],
    )
    return out
