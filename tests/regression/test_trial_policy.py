"""回归：试用配额 / 分辨率上限 / 本地卡密。

用法（仓库根）:
  python tests/regression/test_trial_policy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ensure_scripts_path, fail, ok

ensure_scripts_path()

from core import network, trial_policy  # noqa: E402


def main() -> int:
    assert trial_policy.feature_allowed(True, "pipeline_queue")[0]
    ok_f, _ = trial_policy.feature_allowed(False, "pipeline_queue")
    if ok_f:
        fail("试用应拦截 pipeline_queue")
        return 1
    ok("feature gate")

    h = trial_policy.clamp_export_height(False, 0)
    if h != trial_policy.TRIAL_MAX_EXPORT_HEIGHT:
        fail(f"试用 max_height 期望 {trial_policy.TRIAL_MAX_EXPORT_HEIGHT} 得 {h}")
        return 1
    if trial_policy.clamp_export_height(True, 2160) != 2160:
        fail("正式版不应压分辨率")
        return 1
    ok("export height clamp")

    w, hh = trial_policy.clamp_vertical_size(False, 1080, 1920)
    if max(w, hh) > trial_policy.TRIAL_MAX_EXPORT_HEIGHT:
        fail(f"竖屏未压到试用上限: {w}x{hh}")
        return 1
    ok(f"vertical clamp -> {w}x{hh}")

    class _App:
        is_licensed = False
        trial_highlight_exports = trial_policy.TRIAL_MAX_HIGHLIGHT_EXPORTS
        trial_vertical_exports = 0

    ok_q, tip = trial_policy.check_export_quota(_App(), "highlight")
    if ok_q:
        fail("配额用尽仍放行")
        return 1
    ok(f"quota block: {tip[:40]}")

    if not network.validate_license_key("ABCD1234EFGH5678"):
        fail("合法卡密应通过")
        return 1
    if network.validate_license_key("short"):
        fail("短卡密应拒绝")
        return 1
    ok_r, msg, mode = network.redeem_license_key("ABCD1234EFGH5678")
    if not ok_r or mode != "local":
        fail(f"本地兑换失败 {ok_r} {mode} {msg}")
        return 1
    ok(f"local redeem mode={mode}")

    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
