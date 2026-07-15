"""网易云热评获取。

借鉴 ObjTube《晴天》评论展示思路（B 站 BV1vC4y1t7Wi /
https://github.com/ObjTube/NeteaseMusic-qingtian-comment）：
通过网易云评论接口取 hotComments，不足再用普通评论补齐至最多 100 条。

默认：直连 music.163.com 公开评论 API（无需 Node 中间层）。
可选：NeteaseCloudMusicApi 兼容地址、或外部脚本。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class HotComment:
    content: str
    liked_count: int = 0
    nickname: str = ""

    def display_text(self) -> str:
        text = (self.content or "").strip().replace("\n", " ")
        if self.nickname:
            return f"{self.nickname}：{text}"
        return text


_SONG_ID_RE = re.compile(
    r"(?:song\?id=|/song/|/song\?|/#/song\?id=)(\d+)",
    re.IGNORECASE,
)
_PURE_ID_RE = re.compile(r"^\d{4,}$")

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def parse_song_id(text: str) -> Optional[str]:
    """从网易云链接或纯数字 ID 解析歌曲 ID。"""
    s = (text or "").strip()
    if not s:
        return None
    m = _SONG_ID_RE.search(s)
    if m:
        return m.group(1)
    if _PURE_ID_RE.match(s):
        return s
    m2 = re.search(r"[?&]id=(\d+)", s)
    if m2:
        return m2.group(1)
    return None


def _item_to_comment(item) -> Optional[HotComment]:
    if isinstance(item, str):
        content = item.strip()
        return HotComment(content=content) if content else None
    if not isinstance(item, dict):
        return None
    content = (
        item.get("content")
        or item.get("comment")
        or item.get("text")
        or ""
    )
    content = str(content).strip()
    if not content:
        return None
    liked = item.get("likedCount", item.get("likeCount", item.get("liked", 0)))
    try:
        liked_i = int(liked)
    except (TypeError, ValueError):
        liked_i = 0
    user = item.get("user") or {}
    nick = (
        item.get("nickname")
        or item.get("nickName")
        or (user.get("nickname") if isinstance(user, dict) else "")
        or ""
    )
    return HotComment(content=content, liked_count=liked_i, nickname=str(nick or ""))


def _normalize_items(raw) -> List[HotComment]:
    if isinstance(raw, dict):
        # 合并 hot + comments（API / 脚本均可）
        merged = []
        for key in ("hotComments", "comments", "data"):
            part = raw.get(key)
            if isinstance(part, list):
                merged.extend(part)
        if merged:
            raw = merged
        else:
            raw = []
    if not isinstance(raw, list):
        return []
    out: List[HotComment] = []
    seen = set()
    for item in raw:
        c = _item_to_comment(item)
        if not c:
            continue
        key = c.content
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    out.sort(key=lambda x: x.liked_count, reverse=True)
    return out


def _http_get_json(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _DEFAULT_UA,
            "Referer": "https://music.163.com/",
            "Accept": "application/json, text/plain, */*",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError("评论接口返回格式异常")
    return data


def _fetch_via_music163(song_id: str, limit: int, timeout: int) -> List[HotComment]:
    """直连网易云评论 API（与社区展示站同类数据源思路）。"""
    page_size = min(100, max(limit, 20))
    url = (
        f"https://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}"
        f"?limit={page_size}&offset=0"
    )
    data = _http_get_json(url, timeout=timeout)
    code = data.get("code", 200)
    if code not in (200, None):
        raise RuntimeError(f"网易云评论接口错误 code={code}")

    hot = [_item_to_comment(x) for x in (data.get("hotComments") or [])]
    hot = [c for c in hot if c]
    comments = [_item_to_comment(x) for x in (data.get("comments") or [])]
    comments = [c for c in comments if c]

    # 热评优先，不足再用最新评论按点赞补齐到 limit
    seen = {c.content for c in hot}
    merged = list(hot)
    for c in sorted(comments, key=lambda x: x.liked_count, reverse=True):
        if c.content in seen:
            continue
        seen.add(c.content)
        merged.append(c)
        if len(merged) >= limit:
            break

    # 若仍不足，翻页 offset 再取
    offset = page_size
    while len(merged) < limit and offset < 500:
        more_url = (
            f"https://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}"
            f"?limit={page_size}&offset={offset}"
        )
        try:
            more = _http_get_json(more_url, timeout=timeout)
        except Exception:
            break
        batch = more.get("comments") or []
        if not batch:
            break
        for item in batch:
            c = _item_to_comment(item)
            if not c or c.content in seen:
                continue
            seen.add(c.content)
            merged.append(c)
            if len(merged) >= limit:
                break
        offset += page_size
        if not more.get("more"):
            break

    merged.sort(key=lambda x: x.liked_count, reverse=True)
    return merged[:limit]


def _fetch_via_ncm_api(api_base: str, song_id: str, limit: int, timeout: int) -> List[HotComment]:
    """兼容 Binaryify/NeteaseCloudMusicApi：/comment/music?id=&limit="""
    base = api_base.rstrip("/")
    qs = urllib.parse.urlencode({"id": song_id, "limit": str(limit)})
    url = f"{base}/comment/music?{qs}"
    data = _http_get_json(url, timeout=timeout)
    comments = _normalize_items(data)
    if not comments:
        raise RuntimeError("NeteaseCloudMusicApi 返回空评论")
    return comments[:limit]


def _fetch_via_script(script: str, song_id: str, limit: int, timeout: int) -> List[HotComment]:
    path = Path(script)
    if not path.is_file():
        raise FileNotFoundError(f"热评爬虫脚本不存在: {path}")
    cmd = [sys.executable, str(path), song_id, str(limit)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(path.parent),
        env=env,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"爬虫失败 (exit {result.returncode}): {err or '无输出'}")
    raw_text = (result.stdout or "").strip()
    if not raw_text:
        raise RuntimeError("爬虫无返回内容")
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        start = raw_text.find("[")
        start_obj = raw_text.find("{")
        if start_obj >= 0 and (start < 0 or start_obj < start):
            start = start_obj
        if start < 0:
            raise RuntimeError(f"爬虫输出不是 JSON: {raw_text[:200]}") from e
        data = json.loads(raw_text[start:])
    comments = _normalize_items(data)[:limit]
    if not comments:
        raise RuntimeError("爬虫返回了空评论列表")
    return comments


def _demo_comments(song_id: str, limit: int) -> List[HotComment]:
    samples = [
        HotComment("这首歌陪我走过了很多日子。", 9999, "听众A"),
        HotComment("开口跪，单曲循环到天亮。", 8888, "听众B"),
        HotComment("评论区比歌词还催泪。", 7777, "听众C"),
        HotComment("多年以后再听，依然会想起某个人。", 6666, "听众D"),
    ]
    out: List[HotComment] = []
    i = 0
    while len(out) < limit:
        base = samples[i % len(samples)]
        out.append(HotComment(
            content=f"[演示·{song_id}] {base.content}",
            liked_count=base.liked_count - i,
            nickname=base.nickname,
        ))
        i += 1
    return out


def fetch_hot_comments(
    song_input: str,
    *,
    script_path: str = "",
    api_base: str = "",
    limit: int = 100,
    allow_demo: bool = True,
    timeout: int = 30,
) -> List[HotComment]:
    """获取热评（最多 limit 条）。优先级：自定义脚本 → NCM API → 直连 music.163 → 演示。"""
    song_id = parse_song_id(song_input)
    if not song_id:
        raise ValueError("请输入网易云歌曲链接或数字歌曲 ID")

    limit = max(1, min(int(limit), 100))
    script = (script_path or "").strip().strip('"')
    api = (api_base or "").strip().rstrip("/")

    errors: List[str] = []

    if script:
        try:
            return _fetch_via_script(script, song_id, limit, timeout)
        except Exception as e:
            errors.append(f"脚本: {e}")

    if api:
        try:
            return _fetch_via_ncm_api(api, song_id, limit, timeout)
        except Exception as e:
            errors.append(f"NCM-API: {e}")

    try:
        comments = _fetch_via_music163(song_id, limit, timeout)
        if comments:
            return comments
        errors.append("直连接口返回空列表")
    except urllib.error.HTTPError as e:
        errors.append(f"直连 HTTP {e.code}")
    except Exception as e:
        errors.append(f"直连: {e}")

    if allow_demo:
        return _demo_comments(song_id, limit)

    raise RuntimeError("获取热评失败：" + " | ".join(errors) if errors else "未知错误")
