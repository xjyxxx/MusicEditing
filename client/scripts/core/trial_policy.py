"""试用版商业策略：功能门禁 + 次数配额 + 导出分辨率上限。

正式版（is_licensed）一律不限。配额写入 app.conf，恢复试用不清零次数
（防反复「恢复试用」刷配额）；兑换正式版后不再检查配额。
"""

from __future__ import annotations

from typing import Any

# 试用可用次数（高光成片 / 竖屏导出分别计数）
TRIAL_MAX_HIGHLIGHT_EXPORTS = 20
TRIAL_MAX_VERTICAL_EXPORTS = 10
# 试用导出最长边（低清）；0=不限。正式版不限。
TRIAL_MAX_EXPORT_HEIGHT = 720

FEATURE_TIPS = {
    "enhance_ai_4x": "试用版不可用 AI 超分 4×，请到「个人中心」兑换正式版，或改用 2× / 快速 OpenCV。",
    "pipeline_queue": "试用版不可用批量全流程队列，请到「个人中心」兑换正式版。",
    "watermark_lama": "试用版不可用精修去水印（LaMa），请到「个人中心」兑换正式版，或改用「快速」。",
}


def feature_allowed(is_licensed: bool, feature: str) -> tuple[bool, str]:
    if is_licensed:
        return True, ""
    tip = FEATURE_TIPS.get(feature, "该功能需正式版，请到「个人中心」兑换卡密。")
    return False, tip


def clamp_export_height(is_licensed: bool, max_height: int) -> int:
    """试用强制 ≤ TRIAL_MAX_EXPORT_HEIGHT；正式版原样返回。"""
    h = int(max_height or 0)
    if is_licensed or TRIAL_MAX_EXPORT_HEIGHT <= 0:
        return h
    if h <= 0:
        return TRIAL_MAX_EXPORT_HEIGHT
    return min(h, TRIAL_MAX_EXPORT_HEIGHT)


def clamp_vertical_size(
    is_licensed: bool, width: int, height: int
) -> tuple[int, int]:
    """试用竖屏最长边压到配额上限（保持 9:16）。"""
    w, h = int(width), int(height)
    if is_licensed or TRIAL_MAX_EXPORT_HEIGHT <= 0:
        return w, h
    long_edge = max(w, h)
    if long_edge <= TRIAL_MAX_EXPORT_HEIGHT:
        return w, h
    scale = TRIAL_MAX_EXPORT_HEIGHT / float(long_edge)
    nw = max(2, int(round(w * scale)) // 2 * 2)
    nh = max(2, int(round(h * scale)) // 2 * 2)
    return nw, nh


def _cfg_int(cfg: dict[str, str], key: str) -> int:
    try:
        return max(0, int((cfg.get(key) or "0").strip() or "0"))
    except ValueError:
        return 0


def quota_snapshot(app: Any) -> dict[str, Any]:
    """供个人中心展示。"""
    licensed = bool(getattr(app, "is_licensed", False))
    hl_used = int(getattr(app, "trial_highlight_exports", 0) or 0)
    vt_used = int(getattr(app, "trial_vertical_exports", 0) or 0)
    return {
        "licensed": licensed,
        "highlight_used": hl_used,
        "highlight_max": TRIAL_MAX_HIGHLIGHT_EXPORTS,
        "highlight_left": None if licensed else max(0, TRIAL_MAX_HIGHLIGHT_EXPORTS - hl_used),
        "vertical_used": vt_used,
        "vertical_max": TRIAL_MAX_VERTICAL_EXPORTS,
        "vertical_left": None if licensed else max(0, TRIAL_MAX_VERTICAL_EXPORTS - vt_used),
        "max_export_height": None if licensed else TRIAL_MAX_EXPORT_HEIGHT,
    }


def check_export_quota(app: Any, kind: str) -> tuple[bool, str]:
    """kind: highlight | vertical。正式版直接通过。"""
    if getattr(app, "is_licensed", False):
        return True, ""
    if kind == "highlight":
        used = int(getattr(app, "trial_highlight_exports", 0) or 0)
        left = TRIAL_MAX_HIGHLIGHT_EXPORTS - used
        if left <= 0:
            return (
                False,
                f"试用版高光导出已达上限（{TRIAL_MAX_HIGHLIGHT_EXPORTS} 次），"
                "请到「个人中心」兑换正式版。",
            )
        return True, f"试用剩余高光导出 {left} 次"
    if kind == "vertical":
        used = int(getattr(app, "trial_vertical_exports", 0) or 0)
        left = TRIAL_MAX_VERTICAL_EXPORTS - used
        if left <= 0:
            return (
                False,
                f"试用版竖屏导出已达上限（{TRIAL_MAX_VERTICAL_EXPORTS} 次），"
                "请到「个人中心」兑换正式版。",
            )
        return True, f"试用剩余竖屏导出 {left} 次"
    return True, ""


def consume_export_quota(app: Any, kind: str) -> None:
    """导出成功后调用；正式版无操作。"""
    if getattr(app, "is_licensed", False):
        return
    from core.app_logic import update_app_config_value

    if kind == "highlight":
        n = int(getattr(app, "trial_highlight_exports", 0) or 0) + 1
        app.trial_highlight_exports = n
        try:
            update_app_config_value("trial_highlight_exports", str(n))
        except Exception:
            pass
    elif kind == "vertical":
        n = int(getattr(app, "trial_vertical_exports", 0) or 0) + 1
        app.trial_vertical_exports = n
        try:
            update_app_config_value("trial_vertical_exports", str(n))
        except Exception:
            pass


def load_quota_from_config(app: Any, cfg: dict[str, str]) -> None:
    app.trial_highlight_exports = _cfg_int(cfg, "trial_highlight_exports")
    app.trial_vertical_exports = _cfg_int(cfg, "trial_vertical_exports")
