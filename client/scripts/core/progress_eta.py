"""线性进度 ETA 估算。"""

from __future__ import annotations

import time
from dataclasses import dataclass


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
