"""
网易云热评拉取示例（也可直接被 UI 的内置直连替代）。

用法:
  python netease_hot_comments_example.py <song_id> [limit]

stdout: JSON 数组。实现方式与 ObjTube 晴天评论同类数据源：
  GET https://music.163.com/api/v1/resource/comments/R_SO_4_{id}?limit=&offset=
"""

from __future__ import annotations

import json
import sys
import urllib.request


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: netease_hot_comments_example.py <song_id> [limit]", file=sys.stderr)
        return 2
    song_id = sys.argv[1].strip()
    limit = int(sys.argv[2]) if len(sys.argv) >= 3 else 100
    limit = max(1, min(limit, 100))
    url = (
        f"https://music.163.com/api/v1/resource/comments/R_SO_4_{song_id}"
        f"?limit={limit}&offset=0"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://music.163.com/",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    hot = data.get("hotComments") or []
    comments = data.get("comments") or []
    merged = []
    seen = set()
    for item in hot + comments:
        content = (item.get("content") or "").strip()
        if not content or content in seen:
            continue
        seen.add(content)
        user = item.get("user") or {}
        merged.append({
            "content": content,
            "likedCount": int(item.get("likedCount") or 0),
            "nickname": user.get("nickname") or "",
        })
        if len(merged) >= limit:
            break
    merged.sort(key=lambda x: x["likedCount"], reverse=True)
    print(json.dumps(merged[:limit], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
