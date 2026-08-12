"""Folder-native 照片图库的全局 SQLite 索引。索引不保存或移动原始媒体。"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Sequence

from core.media_library import IMAGE_EXTS, VIDEO_EXTS
from core.photo_album import ensure_album, load_album
from core.photo_metadata import PhotoMetadata, read_photo_metadata
from core.photo_sidecar import sidecar_path, sidecar_status

PHOTO_EXTS = IMAGE_EXTS | {".heic", ".heif", ".tif", ".tiff", ".gif"}


@dataclass(frozen=True)
class PhotoAsset:
    path: str
    name: str
    kind: str
    size_bytes: int
    mtime: float
    favorite: bool = False
    captured_at: float = 0.0
    latitude: float | None = None
    longitude: float | None = None
    camera: str = ""
    edited: bool = False
    live_photo: bool = False

    @property
    def date_label(self) -> str:
        return datetime.fromtimestamp(self.captured_at or self.mtime).strftime("%Y年%m月%d日")


def default_photo_library_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    return base / "MusicEditing" / "photo_library.sqlite3"


class PhotoLibraryIndex:
    """每个 API 调用独占 SQLite 连接，允许 GUI 后台任务并发访问。"""

    _ASSET_COLUMNS = {
        "album_root": "TEXT NOT NULL DEFAULT ''",
        "captured_at": "REAL NOT NULL DEFAULT 0",
        "latitude": "REAL",
        "longitude": "REAL",
        "camera": "TEXT NOT NULL DEFAULT ''",
        "edited": "INTEGER NOT NULL DEFAULT 0",
        "sidecar_path": "TEXT NOT NULL DEFAULT ''",
        "sidecar_mtime": "REAL NOT NULL DEFAULT 0",
        "content_identifier": "TEXT NOT NULL DEFAULT ''",
        "live_pair_key": "TEXT NOT NULL DEFAULT ''",
        "live_photo": "INTEGER NOT NULL DEFAULT 0",
    }

    def __init__(self, db_path: str | Path | None = None):
        self.path = Path(db_path) if db_path else default_photo_library_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=20)
        conn.execute("PRAGMA busy_timeout=20000")
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS library_roots (
                    path TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    added_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS assets (
                    path TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    indexed_at REAL NOT NULL
                );
            """)
            root_columns = {row["name"] for row in conn.execute("PRAGMA table_info(library_roots)")}
            if "title" not in root_columns:
                conn.execute("ALTER TABLE library_roots ADD COLUMN title TEXT NOT NULL DEFAULT ''")
            asset_columns = {row["name"] for row in conn.execute("PRAGMA table_info(assets)")}
            for name, definition in self._ASSET_COLUMNS.items():
                if name not in asset_columns:
                    conn.execute(f"ALTER TABLE assets ADD COLUMN {name} {definition}")
            conn.executescript("""
                CREATE INDEX IF NOT EXISTS idx_assets_mtime ON assets(mtime DESC);
                CREATE INDEX IF NOT EXISTS idx_assets_captured ON assets(captured_at DESC);
                CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind, captured_at DESC);
                CREATE INDEX IF NOT EXISTS idx_assets_favorite ON assets(favorite, captured_at DESC);
                CREATE INDEX IF NOT EXISTS idx_assets_edited ON assets(edited, captured_at DESC);
                CREATE INDEX IF NOT EXISTS idx_assets_location ON assets(latitude, longitude);
                CREATE INDEX IF NOT EXISTS idx_assets_live ON assets(live_photo, captured_at DESC);
            """)

    def roots(self) -> list[str]:
        with self._connect() as conn:
            return [str(row["path"]) for row in conn.execute("SELECT path FROM library_roots ORDER BY added_at")]

    def albums(self) -> list[tuple[str, str]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT path, title FROM library_roots ORDER BY added_at").fetchall()
        return [(str(row["path"]), str(row["title"]) or Path(row["path"]).name) for row in rows]

    def add_root(self, root: str) -> str:
        path = str(Path(root).expanduser().resolve())
        album = ensure_album(path)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO library_roots(path, title, added_at) VALUES (?, ?, ?) "
                "ON CONFLICT(path) DO UPDATE SET title=excluded.title",
                (path, album.title, time.time()),
            )
        return path

    def remove_root(self, root: str) -> None:
        path = str(Path(root).expanduser().resolve())
        with self._connect() as conn:
            conn.execute("DELETE FROM library_roots WHERE path = ?", (path,))
            conn.execute("DELETE FROM assets WHERE album_root = ?", (path,))


    @staticmethod
    def _files(root: str) -> Iterator[Path]:
        pending = [Path(root)]
        while pending:
            folder = pending.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                yield Path(entry.path)
                        except OSError:
                            continue
            except OSError:
                continue

    @staticmethod
    def _kind(path: Path) -> str:
        ext = path.suffix.lower()
        if ext in VIDEO_EXTS:
            return "video"
        if ext in PHOTO_EXTS:
            return "photo"
        return ""

    @staticmethod
    def _live_pair_key(path: Path, metadata: PhotoMetadata) -> str:
        identity = (metadata.content_identifier or path.stem).casefold()
        return f"{path.parent.resolve()}|{identity}"

    def scan(
        self, roots: Sequence[str] | None = None,
        *, cancelled: Callable[[], bool] | None = None,
    ) -> tuple[int, int]:
        """幂等增量扫描。仅新增/变更资产才调用 ExifTool，随后更新 Live Photo 配对。"""
        active_roots = [self.add_root(root) for root in roots] if roots else self.roots()
        changed = scanned = 0
        scan_started = time.time()
        for root in active_roots:
            if cancelled and cancelled():
                return changed, scanned
            records: list[tuple[str, Path, str, os.stat_result, sqlite3.Row | None]] = []
            changed_paths: list[str] = []
            with self._connect() as conn:
                for item in self._files(root):
                    if cancelled and cancelled():
                        return changed, scanned
                    kind = self._kind(item)
                    if not kind:
                        continue
                    try:
                        stat = item.stat()
                        path = str(item.resolve())
                    except OSError:
                        continue
                    scanned += 1
                    old = conn.execute(
                        "SELECT size_bytes, mtime, kind, captured_at, latitude, longitude, camera, "
                        "content_identifier, live_pair_key FROM assets WHERE path = ?", (path,)
                    ).fetchone()
                    if old is None or (int(old["size_bytes"]), float(old["mtime"]), str(old["kind"])) != (
                        int(stat.st_size), float(stat.st_mtime), kind,
                    ):
                        changed_paths.append(path)
                        changed += 1
                    records.append((path, item, kind, stat, old))
                if cancelled and cancelled():
                    return changed, scanned
                metadata = read_photo_metadata(changed_paths)
                if cancelled and cancelled():
                    return changed, scanned
                for path, item, kind, stat, old in records:
                    if path in metadata:
                        details = metadata[path]
                    elif old is not None:
                        details = PhotoMetadata(
                            captured_at=float(old["captured_at"] or stat.st_mtime),
                            latitude=old["latitude"], longitude=old["longitude"],
                            camera=str(old["camera"] or ""),
                            content_identifier=str(old["content_identifier"] or ""),
                        )
                    else:
                        details = PhotoMetadata(captured_at=float(stat.st_mtime))
                    # 未变化资产不重复读 ExifTool；保留已索引的 ContentIdentifier 配对键。
                    # 文件变化但外部工具暂时不可用时也不应无故破坏已有 Live Photo 关系。
                    existing_identifier = str(old["content_identifier"] or "") if old is not None else ""
                    content_identifier = details.content_identifier or existing_identifier
                    existing_pair_key = str(old["live_pair_key"] or "") if old is not None else ""
                    live_pair_key = existing_pair_key
                    if content_identifier or not live_pair_key:
                        identity = (content_identifier or item.stem).casefold()
                        live_pair_key = f"{item.parent.resolve()}|{identity}"
                    edited, sidecar_mtime = sidecar_status(path) if kind == "photo" else (False, 0.0)
                    conn.execute("""
                        INSERT INTO assets(
                            path,name,kind,size_bytes,mtime,favorite,indexed_at,album_root,captured_at,
                            latitude,longitude,camera,edited,sidecar_path,sidecar_mtime,content_identifier,
                            live_pair_key,live_photo
                        ) VALUES (?, ?, ?, ?, ?, COALESCE((SELECT favorite FROM assets WHERE path=?), 0), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                        ON CONFLICT(path) DO UPDATE SET
                            name=excluded.name, kind=excluded.kind, size_bytes=excluded.size_bytes,
                            mtime=excluded.mtime, indexed_at=excluded.indexed_at, album_root=excluded.album_root,
                            captured_at=excluded.captured_at, latitude=excluded.latitude, longitude=excluded.longitude,
                            camera=excluded.camera, edited=excluded.edited, sidecar_path=excluded.sidecar_path,
                            sidecar_mtime=excluded.sidecar_mtime,
                            content_identifier=excluded.content_identifier, live_pair_key=excluded.live_pair_key
                    """, (
                        path, item.name, kind, int(stat.st_size), float(stat.st_mtime), path, scan_started, root,
                        float(details.captured_at or stat.st_mtime), details.latitude, details.longitude, details.camera,
                        int(edited), str(sidecar_path(path)) if kind == "photo" else "", sidecar_mtime,
                        content_identifier, live_pair_key,
                    ))
                # 完整遍历后删除该相册内已不在磁盘的资产。
                conn.execute("DELETE FROM assets WHERE album_root = ? AND indexed_at < ?", (root, scan_started))
                self._refresh_live_photo_flags(conn, root)
        return changed, scanned


    @staticmethod
    def _refresh_live_photo_flags(conn: sqlite3.Connection, root: str) -> None:
        """先按 ContentIdentifier/stem 精确匹配，再对无标识资产做同目录时间邻近匹配。"""
        conn.execute("UPDATE assets SET live_photo = 0 WHERE album_root = ?", (root,))
        pairs = conn.execute("""
            SELECT live_pair_key FROM assets WHERE album_root = ? AND live_pair_key <> ''
            GROUP BY live_pair_key
            HAVING SUM(CASE WHEN kind = 'photo' THEN 1 ELSE 0 END) > 0
               AND SUM(CASE WHEN kind = 'video' THEN 1 ELSE 0 END) > 0
        """, (root,)).fetchall()
        if pairs:
            conn.executemany(
                "UPDATE assets SET live_photo = 1 WHERE album_root = ? AND live_pair_key = ?",
                [(root, str(row["live_pair_key"])) for row in pairs],
            )

        # Apple 标识缺失时，使用同目录且时间差不超过 2 秒的一对一最近邻兜底。
        rows = conn.execute("""
            SELECT path, kind, captured_at FROM assets
            WHERE album_root = ? AND live_photo = 0 AND content_identifier = '' AND captured_at > 0
            ORDER BY captured_at
        """, (root,)).fetchall()
        folders: dict[str, dict[str, list[tuple[float, str]]]] = {}
        for row in rows:
            folder = os.path.normcase(str(Path(str(row["path"])).parent))
            group = folders.setdefault(folder, {"photo": [], "video": []})
            group[str(row["kind"])].append((float(row["captured_at"]), str(row["path"])))
        matched: set[str] = set()
        for group in folders.values():
            videos = group["video"]
            used_videos: set[int] = set()
            left = 0
            for photo_time, photo_path in group["photo"]:
                while left < len(videos) and videos[left][0] < photo_time - 2.0:
                    left += 1
                candidates: list[tuple[float, int, str]] = []
                index = left
                while index < len(videos) and videos[index][0] <= photo_time + 2.0:
                    if index not in used_videos:
                        candidates.append((abs(videos[index][0] - photo_time), index, videos[index][1]))
                    index += 1
                if candidates:
                    _, video_index, video_path = min(candidates)
                    used_videos.add(video_index)
                    matched.update((photo_path, video_path))
        if matched:
            conn.executemany("UPDATE assets SET live_photo = 1 WHERE path = ?", [(path,) for path in matched])

    def refresh_sidecar(self, path: str) -> None:
        """编辑器保存/删除 sidecar 后即时同步索引，不需要全盘重新扫描。"""
        if not path or not os.path.isfile(path):
            return
        edited, mtime = sidecar_status(path)
        with self._connect() as conn:
            conn.execute(
                "UPDATE assets SET edited = ?, sidecar_path = ?, sidecar_mtime = ? WHERE path = ?",
                (int(edited), str(sidecar_path(path)), mtime, path),
            )

    def assets(self, section: str = "all", query: str = "", limit: int = 600) -> list[PhotoAsset]:
        where: list[str] = []
        values: list[object] = []
        conditions = {
            "photos": "kind = 'photo'", "videos": "kind = 'video'", "favorites": "favorite = 1",
            "edited": "edited = 1", "locations": "latitude IS NOT NULL AND longitude IS NOT NULL",
            "live": "live_photo = 1",
        }
        if section in conditions:
            where.append(conditions[section])
        clean_query = (query or "").strip()
        if clean_query:
            where.append("name LIKE ? ESCAPE '\\'")
            escaped = clean_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.append(f"%{escaped}%")
        sql = "SELECT path,name,kind,size_bytes,mtime,favorite,captured_at,latitude,longitude,camera,edited,live_photo FROM assets"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY captured_at DESC, name COLLATE NOCASE LIMIT ?"
        values.append(max(1, int(limit)))
        with self._connect() as conn:
            rows = conn.execute(sql, values).fetchall()
        existing: list[PhotoAsset] = []
        stale: list[str] = []
        for row in rows:
            if os.path.isfile(row["path"]):
                existing.append(PhotoAsset(
                    path=str(row["path"]), name=str(row["name"]), kind=str(row["kind"]),
                    size_bytes=int(row["size_bytes"]), mtime=float(row["mtime"]), favorite=bool(row["favorite"]),
                    captured_at=float(row["captured_at"] or row["mtime"]), latitude=row["latitude"],
                    longitude=row["longitude"], camera=str(row["camera"] or ""),
                    edited=bool(row["edited"]), live_photo=bool(row["live_photo"]),
                ))
            else:
                stale.append(str(row["path"]))
        if stale:
            with self._connect() as conn:
                conn.executemany("DELETE FROM assets WHERE path = ?", [(path,) for path in stale])
        return existing

    def set_favorite(self, path: str, favorite: bool) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE assets SET favorite = ? WHERE path = ?", (int(favorite), path))

    def count(self, section: str = "all") -> int:
        conditions = {
            "photos": "kind = 'photo'", "videos": "kind = 'video'", "favorites": "favorite = 1",
            "edited": "edited = 1", "locations": "latitude IS NOT NULL AND longitude IS NOT NULL",
            "live": "live_photo = 1",
        }
        condition = conditions.get(section)
        sql = "SELECT COUNT(*) FROM assets" + (" WHERE " + condition if condition else "")
        with self._connect() as conn:
            return int(conn.execute(sql).fetchone()[0])
