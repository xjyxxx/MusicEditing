"""下载/热评失败原因白话化与可恢复动作。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class RecoverHint:
    """失败提示 + 建议动作。"""

    title: str
    message: str
    # cookie | retry | none
    action: str = "none"
    action_label: str = ""


def classify_download_error(url: str, err: str) -> RecoverHint:
    """把 yt-dlp / 下载异常翻译成可操作提示。"""
    text = (err or "").strip()
    low = text.lower()
    u = (url or "").lower()
    is_douyin = "douyin" in u or "douyin" in low
    is_bili = "bilibili" in u or "b23.tv" in u or "bilivideo" in low or "bilibili" in low

    if "429" in low or "too many requests" in low or "rate limit" in low:
        return RecoverHint(
            title="请求过于频繁",
            message=(
                "站点限流（类似 429）。请稍等 1～2 分钟再点「重试」。\n"
                "若频繁出现，可换网络或更新 yt-dlp。\n\n"
                f"原始：{text[-350:]}"
            ),
            action="retry",
            action_label="稍后重试",
        )

    if "ssl" in low and ("eof" in low or "syscall" in low or "wrong version" in low):
        return RecoverHint(
            title="网络中断",
            message=(
                "下载链路 SSL/断流。本工具已自动加重试；仍失败请点「重试」。\n"
                "B 站可勾「音画合并」；抖音请确认 Cookie 有效。\n\n"
                f"原始：{text[-350:]}"
            ),
            action="retry",
            action_label="重试下载",
        )

    if "no audio" in low or "audio track" in low or "没有音轨" in text or "仍无音轨" in text:
        return RecoverHint(
            title="没有完整音画",
            message=(
                "拿到了画面但缺音轨。\n"
                "请勾选列表里的「音画合并」项再下；B 站普通画质一般无需 Cookie。\n\n"
                f"原始：{text[-350:]}"
            ),
            action="retry",
            action_label="重试（请勾音画合并）",
        )

    cookie_hit = (
        "cookie" in low
        or "fresh cookies" in low
        or "login" in low
        or "sign in" in low
        or "dpapi" in low
        or "netscape" in low
    )
    if cookie_hit or (is_douyin and ("403" in low or "login" in low)):
        return RecoverHint(
            title="需要更新 Cookie",
            message=(
                ("抖音" if is_douyin else "该站点")
                + "需要有效的 Netscape cookies.txt。\n"
                "1) 浏览器打开并登录对应站点\n"
                "2) 用扩展导出 cookies.txt（勿选 app.conf）\n"
                "3) 点下方「换 Cookie」后重新「获取」/「重试」\n\n"
                f"原始：{text[-350:]}"
            ),
            action="cookie",
            action_label="换 Cookie…",
        )

    if is_bili and ("dash" in low or "format" in low or "requested format" in low):
        return RecoverHint(
            title="B 站格式失败",
            message=(
                "画质/音轨格式组合失败。请勾「音画合并」重试；\n"
                "大会员高画质需配置 Cookie。\n\n"
                f"原始：{text[-350:]}"
            ),
            action="retry",
            action_label="重试",
        )

    if "unsupported url" in low:
        return RecoverHint(
            title="链接不被支持",
            message=(
                "链接格式不被 yt-dlp 识别。抖音精选页请带 modal_id，"
                "或改用 /video/<作品ID>。\n\n"
                f"原始：{text[-350:]}"
            ),
            action="none",
        )

    # 回落到已有友好串或原文
    from core.media_bridge import _friendly_yt_dlp_error

    friendly = _friendly_yt_dlp_error(url, text)
    act = "cookie" if ("cookie" in friendly.lower() or "Cookie" in friendly) else "retry"
    return RecoverHint(
        title="获取/下载失败",
        message=friendly or (text[-800:] or "未知错误"),
        action=act if act == "cookie" else "retry",
        action_label="换 Cookie…" if act == "cookie" else "重试",
    )


def classify_comment_export_error(err: str) -> RecoverHint:
    """热评短视频 / 评论导出失败。"""
    text = (err or "").strip()
    low = text.lower()
    if "media" in low or "没有媒体" in text or "先有媒体" in text:
        return RecoverHint(
            title="缺少媒体文件",
            message="导出热评短视频前，请先「获取」并播放/下载一条到本地媒体槽。\n\n"
            f"原始：{text[-300:]}",
            action="retry",
            action_label="知道了",
        )
    if "ffmpeg" in low or "encode" in low:
        return RecoverHint(
            title="成片编码失败",
            message="FFmpeg 生成短视频失败。请确认引擎已编译，或换一条更短的媒体重试。\n\n"
            f"原始：{text[-300:]}",
            action="retry",
            action_label="重试导出",
        )
    return RecoverHint(
        title="导出失败",
        message=text[-800:] or "未知错误",
        action="retry",
        action_label="重试",
    )
