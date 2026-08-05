"""网易云热评获取。

借鉴 ObjTube《晴天》评论展示思路（B 站 BV1vC4y1t7Wi /
https://github.com/ObjTube/NeteaseMusic-qingtian-comment）：
通过网易云评论接口取 hotComments，不足再用普通评论补齐至最多 100 条。

默认：直连 music.163.com 公开评论 API（无需 Node 中间层）。
可选：NeteaseCloudMusicApi 兼容地址、或外部脚本。
返回 FetchResult（来源 / 歌名 / 缓存）。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
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


@dataclass
class FetchResult:
    """热评拉取结果（含来源与可选歌名）。"""

    comments: List[HotComment] = field(default_factory=list)
    song_id: str = ""
    song_name: str = ""
    source: str = ""  # live | script | api | demo | cache
    message: str = ""

    @property
    def source_label(self) -> str:
        return {
            "live": "网易云直连",
            "script": "自定义脚本",
            "api": "NCM API",
            "demo": "演示数据",
            "cache": "本地缓存",
            "bilibili": "B站弹幕",
        }.get(self.source, self.source or "未知")


_SONG_ID_RE = re.compile(
    r"(?:song\?id=|/song/|/song\?|/#/song\?id=)(\d+)",
    re.IGNORECASE,
)
_PURE_ID_RE = re.compile(r"^\d{4,}$")

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_SOURCE_LIVE = "live"
_SOURCE_SCRIPT = "script"
_SOURCE_API = "api"
_SOURCE_DEMO = "demo"
_SOURCE_CACHE = "cache"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def cache_dir() -> Path:
    d = _project_root() / ".cache" / "hot_comments"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
        merged = []
        for key in ("hotComments", "comments", "data"):
            part = raw.get(key)
            if isinstance(part, list):
                merged.extend(part)
        raw = merged if merged else []
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


def _fetch_song_name(song_id: str, timeout: int = 8) -> str:
    """尽力取歌名；失败返回空串。"""
    try:
        url = f"https://music.163.com/api/song/detail/?ids=[{song_id}]"
        data = _http_get_json(url, timeout=timeout)
        songs = data.get("songs") or []
        if songs and isinstance(songs[0], dict):
            name = str(songs[0].get("name") or "").strip()
            if name:
                return name
    except Exception:
        pass
    try:
        # 备用：页面 og:title 太重，用 song/detail v2 风格
        url = (
            "https://music.163.com/api/v3/song/detail"
            f"?c=%5B%7B%22id%22%3A{song_id}%7D%5D"
        )
        data = _http_get_json(url, timeout=timeout)
        songs = data.get("songs") or []
        if songs and isinstance(songs[0], dict):
            return str(songs[0].get("name") or "").strip()
    except Exception:
        pass
    return ""


def _cache_path(song_id: str) -> Path:
    return cache_dir() / f"{song_id}.json"


def _save_cache(result: FetchResult) -> None:
    if not result.song_id or not result.comments:
        return
    if result.source == _SOURCE_DEMO:
        return
    payload = {
        "song_id": result.song_id,
        "song_name": result.song_name,
        "source": result.source,
        "saved_at": time.time(),
        "comments": [asdict(c) for c in result.comments],
    }
    try:
        _cache_path(result.song_id).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _load_cache(song_id: str, limit: int) -> Optional[FetchResult]:
    path = _cache_path(song_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = data.get("comments") or []
    comments: List[HotComment] = []
    for item in raw:
        if isinstance(item, dict):
            c = HotComment(
                content=str(item.get("content") or ""),
                liked_count=int(item.get("liked_count") or 0),
                nickname=str(item.get("nickname") or ""),
            )
            if c.content.strip():
                comments.append(c)
    if not comments:
        return None
    return FetchResult(
        comments=comments[:limit],
        song_id=song_id,
        song_name=str(data.get("song_name") or ""),
        source=_SOURCE_CACHE,
        message="已用本地缓存",
    )


def _fetch_via_music163(song_id: str, limit: int, timeout: int) -> List[HotComment]:
    """直连网易云评论 API。"""
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

    seen = {c.content for c in hot}
    merged = list(hot)
    for c in sorted(comments, key=lambda x: x.liked_count, reverse=True):
        if c.content in seen:
            continue
        seen.add(c.content)
        merged.append(c)
        if len(merged) >= limit:
            break

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
        HotComment("耳机一戴，整个世界都安静了。", 5555, "听众E"),
        HotComment("高赞说得对，每句都是故事。", 4444, "听众F"),
    ]
    out: List[HotComment] = []
    i = 0
    while len(out) < limit:
        base = samples[i % len(samples)]
        out.append(HotComment(
            content=f"[演示·{song_id}] {base.content}",
            liked_count=max(0, base.liked_count - i * 11),
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
    use_cache: bool = True,
) -> FetchResult:
    """
    获取热评（最多 limit 条）。
    优先级：自定义脚本 → NCM API → 直连 music.163 → 缓存 → 演示。
    """
    song_id = parse_song_id(song_input)
    if not song_id:
        raise ValueError("请输入网易云歌曲链接或数字歌曲 ID")

    limit = max(1, min(int(limit), 100))
    script = (script_path or "").strip().strip('"')
    api = (api_base or "").strip().rstrip("/")
    errors: List[str] = []

    def _pack(comments: List[HotComment], source: str, message: str = "") -> FetchResult:
        name = ""
        if source != _SOURCE_DEMO:
            name = _fetch_song_name(song_id, timeout=min(8, timeout))
        result = FetchResult(
            comments=comments,
            song_id=song_id,
            song_name=name,
            source=source,
            message=message or f"已加载 {len(comments)} 条 · 来源：{FetchResult(source=source).source_label}",
        )
        # 修正 message 用真实 label
        result.message = message or (
            f"已加载 {len(comments)} 条 · 来源：{result.source_label}"
            + (f" · {name}" if name else "")
        )
        if source not in (_SOURCE_DEMO, _SOURCE_CACHE):
            _save_cache(result)
        return result

    if script:
        try:
            comments = _fetch_via_script(script, song_id, limit, timeout)
            if comments:
                return _pack(comments, _SOURCE_SCRIPT)
            errors.append("脚本: empty")
        except Exception as e:
            errors.append(f"脚本: {e}")

    if api:
        try:
            comments = _fetch_via_ncm_api(api, song_id, limit, timeout)
            if comments:
                return _pack(comments, _SOURCE_API)
            errors.append("NCM-API: empty")
        except Exception as e:
            errors.append(f"NCM-API: {e}")

    try:
        comments = _fetch_via_music163(song_id, limit, timeout)
        if comments:
            return _pack(comments, _SOURCE_LIVE)
        errors.append("直连接口返回空列表")
    except urllib.error.HTTPError as e:
        errors.append(f"直连 HTTP {e.code}")
    except Exception as e:
        errors.append(f"直连: {e}")

    if use_cache:
        cached = _load_cache(song_id, limit)
        if cached:
            if not cached.song_name:
                cached.song_name = _fetch_song_name(song_id, timeout=min(5, timeout))
            cached.message = (
                f"已加载 {len(cached.comments)} 条 · 来源：本地缓存"
                + (f" · {cached.song_name}" if cached.song_name else "")
                + "（网络失败回退）"
            )
            return cached

    if allow_demo:
        comments = _demo_comments(song_id, min(limit, 24))
        return FetchResult(
            comments=comments,
            song_id=song_id,
            song_name="",
            source=_SOURCE_DEMO,
            message=(
                f"已加载 {len(comments)} 条演示热评（网络不可用，可稍后重试）"
                + ((" · " + " | ".join(errors[:2])) if errors else "")
            ),
        )

    kind = "network"
    if any("空" in e for e in errors):
        kind = "empty"
    raise RuntimeError(
        f"获取热评失败 [{kind}]：" + (" | ".join(errors) if errors else "未知错误")
    )
