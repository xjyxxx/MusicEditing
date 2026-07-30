"""「仅获取信息」本地缓存：页面信息 + 按列表项唯一主键的多条媒体。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from core.media_bridge import UrlListItem, UrlMediaInfo


def default_cache_root() -> str:
    return os.path.join(os.path.expanduser("~"), "MusicEditingInfoCache")


def sanitize_title(name: str, fallback: str = "未命名") -> str:
    """用歌名/片名生成安全目录/文件名。"""
    s = (name or "").strip()
    if not s:
        s = fallback
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", " ", s).strip(" ._")
    if not s:
        s = fallback
    return s[:80]


def display_title(info: UrlMediaInfo) -> str:
    pl = (info.playlist_title or "").strip()
    title = (info.title or "").strip()
    if pl and title and pl != title:
        return f"{pl} - {title}"
    return pl or title or "未命名"


def url_key(url: str) -> str:
    u = (url or "").strip()
    u = re.sub(r"#.*$", "", u)
    u = re.sub(r"[?&](spm_id_from|vd_source|from_spmid)=[^&]*", "", u)
    return hashlib.sha1(u.encode("utf-8", errors="replace")).hexdigest()[:16]


def item_key(item: UrlListItem) -> str:
    raw = "|".join([
        getattr(item, "kind", "") or "",
        getattr(item, "format_id", "") or "",
        getattr(item, "url", "") or "",
        getattr(item, "name", "") or "",
        "1" if getattr(item, "has_video", False) else "0",
        "1" if getattr(item, "has_audio", False) else "0",
    ])
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:12]


def media_pk(page_url: str, item: UrlListItem) -> str:
    """唯一主键：页面 + 列表项。"""
    return f"{url_key(page_url)}:{item_key(item)}"


def short_item_label(item: UrlListItem) -> str:
    name = (getattr(item, "name", "") or "").strip()
    # 去掉过长的 id= 尾巴，右侧更好读
    name = re.sub(r"\s*·\s*id=[^\s·]+", "", name)
    if len(name) > 48:
        name = name[:45] + "…"
    return name or "未命名条目"


@dataclass
class PageCacheEntry:
    """一个链接的元数据缓存（info.json）。"""
    url: str
    title: str
    key: str
    folder: str
    fetched_at: float = 0.0


@dataclass
class MediaCacheItem:
    """一条可播放的媒体缓存（按唯一主键）。"""
    pk: str
    page_key: str
    item_key: str
    page_url: str
    page_title: str
    item_name: str
    media_path: str
    kind: str = "format"
    format_id: str = ""
    ext: str = ""
    has_video: bool = False
    has_audio: bool = False
    cached_at: float = 0.0

    def label(self) -> str:
        ts = time.strftime("%m-%d %H:%M", time.localtime(self.cached_at)) if self.cached_at else ""
        tags = []
        if self.has_video and not self.has_audio:
            tags.append("仅画面→已合并" if "_av." in os.path.basename(self.media_path) else "仅画面")
        elif self.has_audio and not self.has_video:
            tags.append("仅音频")
        elif self.has_video and self.has_audio:
            tags.append("音画")
        tag = f"[{'/'.join(tags)}] " if tags else ""
        base = f"{self.page_title} · {tag}{self.item_name}"
        return f"{base}  ({ts})" if ts else base


@dataclass
class UrlInfoCache:
    root: str = field(default_factory=default_cache_root)

    def __post_init__(self):
        self.root = os.path.abspath(self.root or default_cache_root())
        os.makedirs(self.root, exist_ok=True)
        self._index_path = os.path.join(self.root, "index.json")
        self._migrate_legacy_index()

    def set_root(self, path: str) -> None:
        self.root = os.path.abspath(path)
        os.makedirs(self.root, exist_ok=True)
        self._index_path = os.path.join(self.root, "index.json")
        self._migrate_legacy_index()

    def _load_index(self) -> dict:
        if not os.path.isfile(self._index_path):
            return {"pages": {}, "items": {}}
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"pages": {}, "items": {}}
            data.setdefault("pages", {})
            data.setdefault("items", {})
            return data
        except Exception:
            return {"pages": {}, "items": {}}

    def _save_index(self, data: dict) -> None:
        data.setdefault("pages", {})
        data.setdefault("items", {})
        tmp = self._index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._index_path)

    def _migrate_legacy_index(self) -> None:
        """旧版 entries（一链一条）→ pages + 扫描 media 为 items。"""
        if not os.path.isfile(self._index_path):
            return
        try:
            with open(self._index_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception:
            return
        if not isinstance(raw, dict) or "entries" not in raw:
            return
        if raw.get("pages") or raw.get("items"):
            # 已有新结构则只清掉 entries
            raw.pop("entries", None)
            self._save_index(raw)
            return

        pages = {}
        items = {}
        for key, meta in (raw.get("entries") or {}).items():
            if not isinstance(meta, dict):
                continue
            folder = meta.get("folder") or ""
            abs_folder = folder if os.path.isabs(folder) else os.path.join(self.root, folder)
            page_url = str(meta.get("url") or "")
            title = str(meta.get("title") or "未命名")
            rel = os.path.relpath(abs_folder, self.root) if os.path.isdir(abs_folder) else folder
            pages[key] = {
                "url": page_url,
                "title": title,
                "folder": rel,
                "fetched_at": float(meta.get("fetched_at") or 0),
            }
            media_dir = os.path.join(abs_folder, "media")
            if not os.path.isdir(media_dir):
                continue
            for name in os.listdir(media_dir):
                path = os.path.join(media_dir, name)
                if not os.path.isfile(path) or os.path.getsize(path) < 1000:
                    continue
                # 文件名: {item_key}_{name}[_av].ext
                ik = name.split("_", 1)[0] if "_" in name else hashlib.sha1(name.encode()).hexdigest()[:12]
                pk = f"{key}:{ik}"
                item_name = name
                m = re.match(r"^[a-f0-9]{12}_(.+?)(_av)?\.[^.]+$", name)
                if m:
                    item_name = m.group(1).replace("_", " ")
                items[pk] = {
                    "pk": pk,
                    "page_key": key,
                    "item_key": ik,
                    "page_url": page_url,
                    "page_title": title,
                    "item_name": item_name,
                    "media_path": os.path.relpath(path, self.root),
                    "kind": "format",
                    "format_id": "",
                    "ext": os.path.splitext(name)[1].lstrip("."),
                    "has_video": "_av." in name or name.endswith(".mp4"),
                    "has_audio": True,
                    "cached_at": os.path.getmtime(path),
                }
        self._save_index({"pages": pages, "items": items})

    def _page_dir(self, key: str, title: str) -> str:
        return os.path.join(self.root, f"{sanitize_title(title)}_{key}")

    def _abs(self, rel_or_abs: str) -> str:
        if not rel_or_abs:
            return ""
        if os.path.isabs(rel_or_abs):
            return rel_or_abs
        return os.path.join(self.root, rel_or_abs)

    # —— 页面（链接）级 ——

    def list_pages(self) -> List[PageCacheEntry]:
        data = self._load_index()
        out: List[PageCacheEntry] = []
        for key, meta in (data.get("pages") or {}).items():
            if not isinstance(meta, dict):
                continue
            folder = self._abs(meta.get("folder") or "")
            out.append(PageCacheEntry(
                url=str(meta.get("url") or ""),
                title=str(meta.get("title") or "未命名"),
                key=key,
                folder=folder,
                fetched_at=float(meta.get("fetched_at") or 0),
            ))
        out.sort(key=lambda e: e.fetched_at, reverse=True)
        return out

    def find_page(self, url: str) -> Optional[PageCacheEntry]:
        key = url_key(url)
        data = self._load_index()
        meta = (data.get("pages") or {}).get(key)
        if not meta:
            for k, m in (data.get("pages") or {}).items():
                if isinstance(m, dict) and (m.get("url") or "").strip() == (url or "").strip():
                    key, meta = k, m
                    break
        if not meta:
            return None
        folder = self._abs(meta.get("folder") or "")
        if folder and not os.path.isdir(folder):
            return None
        return PageCacheEntry(
            url=str(meta.get("url") or url),
            title=str(meta.get("title") or "未命名"),
            key=key,
            folder=folder,
            fetched_at=float(meta.get("fetched_at") or 0),
        )

    def load_info(self, url: str) -> Optional[UrlMediaInfo]:
        page = self.find_page(url)
        if not page:
            return None
        path = os.path.join(page.folder, "info.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return self._dict_to_info(json.load(f))
        except Exception:
            return None

    def load_info_by_page(self, page: PageCacheEntry) -> Optional[UrlMediaInfo]:
        path = os.path.join(page.folder, "info.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return self._dict_to_info(json.load(f))
        except Exception:
            return None

    def save_info(self, info: UrlMediaInfo) -> PageCacheEntry:
        url = (info.webpage_url or info.url or "").strip()
        key = url_key(url)
        title = display_title(info)
        folder = self._page_dir(key, title)
        os.makedirs(folder, exist_ok=True)
        os.makedirs(os.path.join(folder, "media"), exist_ok=True)
        with open(os.path.join(folder, "info.json"), "w", encoding="utf-8") as f:
            json.dump(self._info_to_dict(info), f, ensure_ascii=False, indent=2)

        rel = os.path.relpath(folder, self.root)
        data = self._load_index()
        data["pages"][key] = {
            "url": url,
            "title": title,
            "folder": rel,
            "fetched_at": time.time(),
        }
        self._save_index(data)
        return PageCacheEntry(url=url, title=title, key=key, folder=folder, fetched_at=time.time())

    # —— 媒体项（唯一主键）级 ——

    def list_media_items(self) -> List[MediaCacheItem]:
        data = self._load_index()
        out: List[MediaCacheItem] = []
        for pk, meta in (data.get("items") or {}).items():
            if not isinstance(meta, dict):
                continue
            path = self._abs(meta.get("media_path") or "")
            if not path or not os.path.isfile(path):
                continue
            out.append(self._meta_to_media(meta, path))
        out.sort(key=lambda e: e.cached_at, reverse=True)
        return out

    def list_media_for_page(self, page_url: str) -> List[MediaCacheItem]:
        pk_prefix = url_key(page_url) + ":"
        return [m for m in self.list_media_items() if m.pk.startswith(pk_prefix)]

    def get_media_item(self, pk: str) -> Optional[MediaCacheItem]:
        data = self._load_index()
        meta = (data.get("items") or {}).get(pk)
        if not isinstance(meta, dict):
            return None
        path = self._abs(meta.get("media_path") or "")
        if not path or not os.path.isfile(path):
            return None
        return self._meta_to_media(meta, path)

    def find_media(self, page_url: str, item: UrlListItem) -> Optional[str]:
        pk = media_pk(page_url, item)
        hit = self.get_media_item(pk)
        if hit and os.path.getsize(hit.media_path) > 1000:
            # 旧无声仅画面：文件名无 _av 则视为无效
            if (
                getattr(item, "has_video", False)
                and not getattr(item, "has_audio", False)
                and "_av." not in os.path.basename(hit.media_path)
            ):
                return None
            return hit.media_path
        return None

    def save_media(
        self,
        page_url: str,
        info_title: str,
        item: UrlListItem,
        src_path: str,
    ) -> Optional[str]:
        if not src_path or not os.path.isfile(src_path):
            return None
        page = self.find_page(page_url)
        if not page:
            dummy = UrlMediaInfo(url=page_url, title=info_title, webpage_url=page_url)
            page = self.save_info(dummy)

        media_dir = os.path.join(page.folder, "media")
        os.makedirs(media_dir, exist_ok=True)

        ik = item_key(item)
        pk = media_pk(page_url, item)
        ext = os.path.splitext(src_path)[1].lstrip(".") or (getattr(item, "ext", "") or "mp3")
        ext = ext.lstrip(".")
        item_name = sanitize_title(short_item_label(item) or info_title or "preview")
        av_tag = ""
        if getattr(item, "has_video", False) and not getattr(item, "has_audio", False):
            av_tag = "_av"
            if ext in ("m4a", "mp3", "aac"):
                ext = "mp4"
        dest_name = f"{ik}_{item_name}{av_tag}.{ext}"
        dest = os.path.join(media_dir, dest_name)
        shutil.copy2(src_path, dest)

        data = self._load_index()
        data["items"][pk] = {
            "pk": pk,
            "page_key": page.key,
            "item_key": ik,
            "page_url": page_url,
            "page_title": page.title or info_title or "未命名",
            "item_name": short_item_label(item),
            "media_path": os.path.relpath(dest, self.root),
            "kind": getattr(item, "kind", "") or "format",
            "format_id": getattr(item, "format_id", "") or "",
            "ext": ext,
            "has_video": bool(getattr(item, "has_video", False)),
            "has_audio": bool(getattr(item, "has_audio", False)),
            "cached_at": time.time(),
            "item": asdict(item) if hasattr(item, "__dataclass_fields__") else {},
        }
        # 刷新页面时间
        if page.key in (data.get("pages") or {}):
            data["pages"][page.key]["fetched_at"] = time.time()
        self._save_index(data)
        return dest

    def delete_media_item(self, item: MediaCacheItem) -> None:
        data = self._load_index()
        (data.get("items") or {}).pop(item.pk, None)
        self._save_index(data)
        if item.media_path and os.path.isfile(item.media_path):
            try:
                os.remove(item.media_path)
            except OSError:
                pass

    def delete_page(self, page: PageCacheEntry) -> None:
        """删除整个链接缓存（info + 其下所有媒体项）。"""
        data = self._load_index()
        (data.get("pages") or {}).pop(page.key, None)
        items = data.get("items") or {}
        for pk in [k for k, m in items.items() if isinstance(m, dict) and m.get("page_key") == page.key]:
            meta = items.pop(pk)
            path = self._abs((meta or {}).get("media_path") or "")
            if path and os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        self._save_index(data)
        if page.folder and os.path.isdir(page.folder):
            shutil.rmtree(page.folder, ignore_errors=True)

    # 兼容旧 UI 命名
    def list_entries(self) -> List[MediaCacheItem]:
        return self.list_media_items()

    def delete_entry(self, entry) -> None:
        if isinstance(entry, MediaCacheItem):
            self.delete_media_item(entry)
        elif isinstance(entry, PageCacheEntry):
            self.delete_page(entry)

    def clear_all(self) -> None:
        for p in self.list_pages():
            self.delete_page(p)
        data = self._load_index()
        data["items"] = {}
        data["pages"] = {}
        self._save_index(data)

    @staticmethod
    def _meta_to_media(meta: dict, abs_path: str) -> MediaCacheItem:
        return MediaCacheItem(
            pk=str(meta.get("pk") or ""),
            page_key=str(meta.get("page_key") or ""),
            item_key=str(meta.get("item_key") or ""),
            page_url=str(meta.get("page_url") or ""),
            page_title=str(meta.get("page_title") or "未命名"),
            item_name=str(meta.get("item_name") or ""),
            media_path=abs_path,
            kind=str(meta.get("kind") or "format"),
            format_id=str(meta.get("format_id") or ""),
            ext=str(meta.get("ext") or ""),
            has_video=bool(meta.get("has_video")),
            has_audio=bool(meta.get("has_audio")),
            cached_at=float(meta.get("cached_at") or 0),
        )

    @staticmethod
    def _info_to_dict(info: UrlMediaInfo) -> dict:
        return {
            "url": info.url,
            "title": info.title,
            "duration_sec": info.duration_sec,
            "uploader": info.uploader,
            "webpage_url": info.webpage_url,
            "thumbnail": info.thumbnail,
            "ext": info.ext,
            "playlist_title": info.playlist_title,
            "preview_hint": info.preview_hint,
            "items": [asdict(it) for it in (info.items or [])],
        }

    @staticmethod
    def _dict_to_info(raw: dict) -> UrlMediaInfo:
        items = []
        for it in raw.get("items") or []:
            if not isinstance(it, dict):
                continue
            items.append(UrlListItem(
                name=str(it.get("name") or ""),
                detail=str(it.get("detail") or ""),
                url=str(it.get("url") or ""),
                kind=str(it.get("kind") or "format"),
                format_id=str(it.get("format_id") or ""),
                page_url=str(it.get("page_url") or ""),
                ext=str(it.get("ext") or ""),
                has_video=bool(it.get("has_video")),
                has_audio=bool(it.get("has_audio")),
            ))
        return UrlMediaInfo(
            url=str(raw.get("url") or ""),
            title=str(raw.get("title") or ""),
            duration_sec=float(raw.get("duration_sec") or 0),
            uploader=str(raw.get("uploader") or ""),
            webpage_url=str(raw.get("webpage_url") or ""),
            thumbnail=str(raw.get("thumbnail") or ""),
            ext=str(raw.get("ext") or ""),
            playlist_title=str(raw.get("playlist_title") or ""),
            preview_hint=str(raw.get("preview_hint") or ""),
            items=items,
        )
