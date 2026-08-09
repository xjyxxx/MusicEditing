"""线性进度 ETA 估算（含分阶段权重）。"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class EtaTracker:
    """根据进度百分比线性外推剩余秒数。"""

    _t0: float = 0.0
    _last_pct: float = 0.0

    def __post_init__(self):
        self.reset()

    def reset(self) -> None:
        self._t0 = time.monotonic()
        self._last_pct = 0.0

    def eta_sec(self, pct: float) -> float:
        p = max(0.0, min(100.0, float(pct)))
        self._last_pct = p
        if p < 1.0:
            return -1.0
        elapsed = time.monotonic() - self._t0
        if elapsed < 0.2:
            return -1.0
        total = elapsed * (100.0 / p)
        remain = total - elapsed
        return max(0.0, remain)


@dataclass
class PhaseEtaTracker:
    """按阶段权重估算整条链路剩余时间。

    weights 之和应为 1.0；阶段内进度 0~100 映射到该段权重。
    """

    weights: Dict[str, float] = field(default_factory=dict)
    _t0: float = 0.0
    _phase: str = ""
    _phase_pct: float = 0.0

    def __post_init__(self):
        self.reset()

    def reset(self) -> None:
        self._t0 = time.monotonic()
        self._phase = ""
        self._phase_pct = 0.0

    def set_phase(self, phase: str, phase_pct: float = 0.0) -> None:
        self._phase = phase or ""
        self._phase_pct = max(0.0, min(100.0, float(phase_pct)))

    def overall_pct(self) -> float:
        if not self.weights:
            return self._phase_pct
        done = 0.0
        hit = False
        for name, w in self.weights.items():
            if name == self._phase:
                done += w * (self._phase_pct / 100.0)
                hit = True
                break
            done += w
        if not hit and self._phase:
            # 未知阶段：用全局线性
            return self._phase_pct
        return max(0.0, min(100.0, done * 100.0))

    def eta_sec(self) -> float:
        p = self.overall_pct()
        if p < 1.0:
            return -1.0
        elapsed = time.monotonic() - self._t0
        if elapsed < 0.2:
            return -1.0
        return max(0.0, elapsed * (100.0 / p) - elapsed)


def format_eta(sec: float) -> str:
    if sec < 0:
        return ""
    s = int(sec + 0.5)
    if s < 60:
        return f"剩余约 {s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"剩余约 {m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"剩余约 {h}h{m:02d}m"


def with_eta(msg: str, pct: float, tracker: EtaTracker) -> str:
    eta = format_eta(tracker.eta_sec(pct))
    base = (msg or "").strip()
    if not eta:
        return base
    if not base:
        return eta
    return f"{base} · {eta}"


def with_phase_eta(msg: str, tracker: PhaseEtaTracker) -> str:
    eta = format_eta(tracker.eta_sec())
    base = (msg or "").strip()
    if not eta:
        return base
    if not base:
        return eta
    return f"{base} · {eta}"
