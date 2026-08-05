"""B 站弹幕拉取（XML → HotComment，供首页弹幕层复用）。"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from xml.etree.ElementTree import ParseError

from core.netease_comments import FetchResult, HotComment

_BV_RE = re.compile(r"(BV[\w]+)", re.I)
_AV_RE = re.compile(r"(?:av|/video/av)(\d+)", re.I)
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_SOURCE = "bilibili"


def parse_bvid(text: str) -> str:
    m = _BV_RE.search(text or "")
    return m.group(1) if m else ""


def is_bilibili_url(text: str) -> bool:
    t = (text or "").lower()
    return "bilibili.com" in t or "b23.tv" in t or bool(parse_bvid(text))


def _http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _DEFAULT_UA,
            "Referer": "https://www.bilibili.com/",
            # 部分环境下仍可能拿到 raw deflate，见 _maybe_inflate
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _maybe_inflate(resp.read())


def _maybe_inflate(raw: bytes) -> bytes:
    """B 站弹幕 XML 常以 raw deflate 下发（非 zlib/gzip 头）。"""
    if not raw:
        return raw
    head = raw.lstrip()[:20]
    if head.startswith(b"<?xml") or head.startswith(b"<"):
        return raw
    import zlib
    try:
        return zlib.decompress(raw, -zlib.MAX_WBITS)
    except Exception:
        try:
            return zlib.decompress(raw)
        except Exception:
            return raw


def _resolve_cid_title(bvid: str = "", aid: str = "") -> Tuple[str, str, str]:
    """返回 (cid, title, id_label)。"""
    if bvid:
        api = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        id_label = bvid
    elif aid:
        api = f"https://api.bilibili.com/x/web-interface/view?aid={aid}"
        id_label = f"av{aid}"
    else:
        raise ValueError("缺少 BV/AV 号")

    import json
    raw = _http_get(api)
    data = json.loads(raw.decode("utf-8", errors="replace"))
    if int(data.get("code") or 0) != 0:
        raise RuntimeError(data.get("message") or f"B站接口错误 code={data.get('code')}")
    info = data.get("data") or {}
    title = str(info.get("title") or "")
    pages = info.get("pages") or []
    cid = ""
    if pages and isinstance(pages[0], dict):
        cid = str(pages[0].get("cid") or "")
    if not cid:
        cid = str(info.get("cid") or "")
    if not cid:
        raise RuntimeError("未解析到 cid，无法拉弹幕")
    return cid, title, id_label


def _parse_danmaku_xml(xml_text: str, *, limit: int = 400) -> List[HotComment]:
    """解析 comment.bilibili.com/{cid}.xml。"""
    try:
        root = ET.fromstring(xml_text)
    except ParseError:
        # 偶发声明/编码问题：忽略非法字符再试
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml_text)
        root = ET.fromstring(cleaned)

    rows: List[Tuple[float, HotComment]] = []
    for d in root.iter("d"):
        text = (d.text or "").strip()
        if not text:
            continue
        p = d.get("p") or ""
        parts = p.split(",")
        try:
            t = float(parts[0]) if parts else 0.0
        except ValueError:
            t = 0.0
        # liked_count：用时间戳哈希做弱权重，保证弹幕层有轻重
        weight = 1
        if len(parts) > 4:
            try:
                weight = max(1, int(parts[4]) % 5000)
            except ValueError:
                weight = 1
        rows.append((t, HotComment(content=text, liked_count=weight, nickname="弹幕")))

    if not rows:
        return []
    rows.sort(key=lambda x: x[0])
    if len(rows) <= limit:
        return [c for _, c in rows]

    # 按时轴均匀抽样，避免只取片头
    step = len(rows) / float(limit)
    out: List[HotComment] = []
    for i in range(limit):
        idx = min(len(rows) - 1, int(i * step))
        out.append(rows[idx][1])
    return out


def fetch_bilibili_danmaku(
    url_or_id: str,
    *,
    limit: int = 400,
) -> FetchResult:
    """从 B 站链接或 BV 号拉取弹幕，映射为 HotComment 列表。"""
    text = (url_or_id or "").strip()
    if not text:
        return FetchResult(message="请提供 B 站链接", source=_SOURCE)

    bvid = parse_bvid(text)
    aid = ""
    if not bvid:
        m = _AV_RE.search(text)
        if m:
            aid = m.group(1)
    if not bvid and not aid:
        return FetchResult(message="无法识别 BV/AV 号", source=_SOURCE)

    try:
        cid, title, id_label = _resolve_cid_title(bvid=bvid, aid=aid)
        xml_bytes = _http_get(f"https://comment.bilibili.com/{cid}.xml")
        # B 站 XML 多为 utf-8；个别为 deflate 已由 urlopen 解压
        xml_text = xml_bytes.decode("utf-8", errors="replace")
        comments = _parse_danmaku_xml(xml_text, limit=limit)
        if not comments:
            return FetchResult(
                comments=[],
                song_id=id_label,
                song_name=title,
                source=_SOURCE,
                message=f"已解析 {id_label}，但弹幕为空",
            )
        return FetchResult(
            comments=comments,
            song_id=id_label,
            song_name=title,
            source=_SOURCE,
            message=f"B站弹幕 {len(comments)} 条 · {title or id_label}",
        )
    except Exception as e:
        return FetchResult(
            song_id=bvid or (f"av{aid}" if aid else ""),
            source=_SOURCE,
            message=f"B站弹幕获取失败: {e}",
        )
