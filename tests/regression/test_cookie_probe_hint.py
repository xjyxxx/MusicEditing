"""回归：Cookie / 探测失败白话提示分类。

不访问网络；只校验 classify_download_error 对典型错误串给出可操作提示。

用法（仓库根）:
  python tests/regression/test_cookie_probe_hint.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ensure_scripts_path, fail, ok

ensure_scripts_path()

from core.download_recover import classify_download_error  # noqa: E402


def _check(name: str, url: str, err: str, *, expect_action: str, must_contain: str) -> None:
    hint = classify_download_error(url, err)
    if hint.action != expect_action:
        raise AssertionError(
            f"{name}: action={hint.action!r} expect={expect_action!r} "
            f"title={hint.title!r}"
        )
    blob = f"{hint.title}\n{hint.message}\n{hint.action_label}"
    if must_contain.lower() not in blob.lower():
        raise AssertionError(f"{name}: 提示未含 {must_contain!r}\n---\n{blob}")
    ok(f"{name} → {hint.title} / {hint.action}")


def main() -> int:
    cases = [
        (
            "douyin_cookie",
            "https://www.douyin.com/video/123",
            "ERROR: Failed to decrypt with DPAPI. Please provide fresh cookies",
            "cookie",
            "Cookie",
        ),
        (
            "netscape_bad",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "does not look like a netscape format cookies file",
            "cookie",
            "Cookie",
        ),
        (
            "rate_limit",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "HTTP Error 429: Too Many Requests",
            "retry",
            "限流",
        ),
        (
            "no_audio",
            "https://www.bilibili.com/video/BV1xx411c7mD",
            "Downloaded video has no audio track",
            "retry",
            "音轨",
        ),
        (
            "probe_login",
            "https://www.douyin.com/video/123",
            "Sign in to confirm you're not a bot (403)",
            "cookie",
            "Cookie",
        ),
    ]
    try:
        for name, url, err, action, needle in cases:
            _check(name, url, err, expect_action=action, must_contain=needle)
        print("PASS  cookie / probe failure hints")
        return 0
    except AssertionError as e:
        fail(str(e))
        return 1
    except Exception as e:
        fail(str(e))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
