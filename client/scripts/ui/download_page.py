"""下载与热评三合一：获取探测 → 勾选进列表 → 点选播放 / 送首页叠播。"""

from __future__ import annotations

import os
import time
from typing import List, Optional, Set

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QRadioButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from core.app_logic import AppLogic
from core.bilibili_danmaku import fetch_bilibili_danmaku, is_bilibili_url
from core.media_bridge import UrlListItem, UrlMediaInfo, normalize_webpage_url
from core.netease_comments import (
    FetchResult, HotComment, fetch_hot_comments, parse_song_id,
)
from core.url_info_cache import MediaCacheItem, UrlInfoCache, display_title, media_pk
from ui.theme import hot_comments_stylesheet
from viewmodels.main_vm import MainViewModel

_ROLE_ITEM = Qt.UserRole
_ROLE_PAGE = Qt.UserRole + 1
_ROLE_AUDIO = Qt.UserRole + 2
_ROLE_LOCAL = Qt.UserRole + 3
_ROLE_PK = Qt.UserRole + 4
_TRIAL_ID = "186016"
_TRIAL_LABEL = "晴天 186016"
_AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".flac", ".aac", ".ogg", ".opus"}
_HISTORY_LIMIT = 40
_LIST_LABEL_MAX = 64


class _BoundedListWidget(QListWidget):
    """列表自带滚动，不因长文本撑开整页宽度。"""

    def minimumSizeHint(self) -> QSize:
        s = super().minimumSizeHint()
        s.setWidth(80)
        return s

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        # 宽度交给布局/视口，避免按最长 item 撑窗
        s.setWidth(240)
        return s


def _elide_list_label(text: str, max_chars: int = _LIST_LABEL_MAX) -> str:
    t = (text or "").replace("\n", " ").strip()
    if len(t) <= max_chars:
        return t
    keep = max(8, max_chars - 1)
    head = keep // 2
    tail = keep - head
    return f"{t[:head]}…{t[-tail:]}"


class MediaSelectDialog(QDialog):
    """获取成功后弹出：勾选要加入结果列表的格式/条目。"""

    def __init__(self, info: UrlMediaInfo, *, prefer_audio: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("选择要加入列表的内容")
        self.setMinimumWidth(520)
        self.setMinimumHeight(420)
        self._info = info

        root = QVBoxLayout(self)
        title = QLabel(info.title or "未命名")
        title.setObjectName("HotSongTitle")
        title.setWordWrap(True)
        root.addWidget(title)
        meta = QLabel(
            f"{info.uploader or '—'} · {info.duration_sec:.0f}s · {info.webpage_url or info.url}"
        )
        meta.setObjectName("HotSongMeta")
        meta.setWordWrap(True)
        root.addWidget(meta)
        if info.preview_hint:
            hint = QLabel(info.preview_hint)
            hint.setObjectName("WarnText")
            hint.setWordWrap(True)
            root.addWidget(hint)

        tip = QLabel(
            "勾选后点「加入列表」。B 站等请选「音画合并」以便有声播放。"
        )
        tip.setObjectName("HotPathMuted")
        tip.setWordWrap(True)
        root.addWidget(tip)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.NoSelection)
        root.addWidget(self._list, 1)

        items = list(info.items or [])
        if not items:
            dummy = UrlListItem(
                name="默认最佳（由 yt-dlp 自动选择）",
                detail="best",
                url=info.webpage_url or info.url,
                kind="default",
                page_url=info.webpage_url or info.url,
                has_video=True,
                has_audio=True,
            )
            items = [dummy]

        default_idx = 0
        for i, it in enumerate(items):
            label = it.name
            if it.detail and it.detail not in it.name:
                label = f"{it.name}    ({it.detail})"
            row = QListWidgetItem(label)
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Unchecked)
            row.setData(Qt.UserRole, it)
            self._list.addItem(row)
            if prefer_audio:
                if getattr(it, "has_audio", False) and not getattr(it, "has_video", False):
                    if default_idx == 0 or i < default_idx:
                        default_idx = i
            else:
                name = (it.name or "")
                if name.startswith("音画合并") or (
                    getattr(it, "has_video", False) and getattr(it, "has_audio", False)
                ):
                    if default_idx == 0 and i == 0:
                        default_idx = i
                    elif name.startswith("音画合并") and default_idx == 0:
                        default_idx = i

        # 默认勾选：音画合并第一项（或仅音频）
        if prefer_audio:
            for i in range(self._list.count()):
                it = self._list.item(i).data(Qt.UserRole)
                if (
                    isinstance(it, UrlListItem)
                    and getattr(it, "has_audio", False)
                    and not getattr(it, "has_video", False)
                ):
                    default_idx = i
                    break
        else:
            for i in range(self._list.count()):
                it = self._list.item(i).data(Qt.UserRole)
                if isinstance(it, UrlListItem) and (it.name or "").startswith("音画合并"):
                    default_idx = i
                    break

        if self._list.count():
            self._list.item(min(default_idx, self._list.count() - 1)).setCheckState(
                Qt.Checked
            )

        row_btns = QHBoxLayout()
        btn_all = QPushButton("全选")
        btn_all.clicked.connect(self._check_all)
        btn_none = QPushButton("全不选")
        btn_none.clicked.connect(self._check_none)
        row_btns.addWidget(btn_all)
        row_btns.addWidget(btn_none)
        row_btns.addStretch()
        root.addLayout(row_btns)

        self._audio_only = QCheckBox("只要音频（MP3，不下载画面）")
        self._audio_only.setChecked(prefer_audio)
        self._audio_only.setToolTip(
            "勾选后仅抽取音频。若勾选「音画合并」项，仍会按视频+音轨下载。"
        )
        root.addWidget(self._audio_only)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Ok).setText("加入列表")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _check_all(self):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.Checked)

    def _check_none(self):
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(Qt.Unchecked)

    def _on_accept(self):
        if not self.checked_items():
            QMessageBox.warning(self, "提示", "请至少勾选一项")
            return
        self.accept()

    def checked_items(self) -> List[UrlListItem]:
        out: List[UrlListItem] = []
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.checkState() == Qt.Checked:
                data = it.data(Qt.UserRole)
                if isinstance(data, UrlListItem):
                    out.append(data)
        return out

    def want_audio(self) -> bool:
        return self._audio_only.isChecked()


class _CommentFetchWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        song_input: str,
        script: str,
        api_base: str,
        allow_demo: bool,
        *,
        mode: str = "netease",
    ):
        super().__init__()
        self._song_input = song_input
        self._script = script
        self._api_base = api_base
        self._allow_demo = allow_demo
        self._mode = mode

    @Slot()
    def run(self):
        try:
            if self._mode == "bilibili":
                result = fetch_bilibili_danmaku(self._song_input, limit=400)
                if not result.comments and "失败" in (result.message or ""):
                    self.failed.emit(result.message or "B站弹幕获取失败")
                    return
                self.finished.emit(result)
                return
            result = fetch_hot_comments(
                self._song_input,
                script_path=self._script,
                api_base=self._api_base,
                limit=100,
                allow_demo=self._allow_demo,
            )
            self.finished.emit(result)
        except Exception as e:
            self.failed.emit(str(e))


class DownloadPage(QWidget):
    """一步获取评论 + 媒体列表；点选播放 / 送首页叠弹幕。"""

    previewPlayRequested = Signal(str)
    playWithCommentsRequested = Signal(str, object)  # path, comments

    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self.setObjectName("HotCommentsPage")
        self.setStyleSheet(hot_comments_stylesheet())
        self._vm = vm
        self._busy = False
        self._probe_for_select = False
        self._awaiting_fetch = False
        self._play_after_download = False
        self._manual_download = False
        self._page_url = ""
        self._info_title = ""
        self._pending_cache_item = None
        self._pending_list_row = -1
        self._last_probe_info: Optional[UrlMediaInfo] = None
        self._cache = UrlInfoCache()
        self._out_dir = os.path.join(
            os.path.expanduser("~"), "MusicEditingDownloads"
        )
        self._comments: List[HotComment] = []
        self._media_path = ""
        self._media_kind = ""  # audio | video
        self._song_id = ""
        self._song_name = ""
        self._comment_source = ""
        self._comments_done = True
        self._thread: QThread | None = None
        self._worker: _CommentFetchWorker | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setObjectName("HotScroll")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("HotPage")
        body.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        root = QVBoxLayout(body)
        root.setContentsMargins(4, 4, 4, 12)
        root.setSpacing(14)

        tip = QLabel(
            "获取探测后勾选加入列表 · B站自动拉弹幕 · 播过的会留在历史中 · 首页可叠弹幕"
        )
        tip.setObjectName("HotHint")
        tip.setWordWrap(True)
        tip.setToolTip(
            "「获取」只拉元数据/热评或 B 站弹幕，不自动下载。"
            "B 站 DASH 会列出「音画合并」项（画面+音轨），请勿只选仅画面。"
            "已播放/下载的媒体会写入本地历史。"
            "请仅处理自有或已获授权内容。"
        )
        root.addWidget(tip)

        root.addWidget(self._build_fetch_box())
        root.addWidget(self._build_result_box(), 1)

        scroll.setWidget(body)
        outer.addWidget(scroll)
        self._scroll = scroll

        yt_ok = bool(vm.bridge and getattr(vm.bridge, "yt_dlp_available", False))
        if not yt_ok:
            self._status.setText(
                "未找到 yt-dlp.exe。请运行 scripts\\download_yt_dlp.bat"
            )
            self._btn_fetch.setEnabled(False)

        vm.downloadProgress.connect(self._on_progress)
        vm.downloadFinished.connect(self._on_finished)
        vm.downloadProbeReady.connect(self._on_probe_ready)
        vm.errorOccurred.connect(self._on_error)

        self._reload_history_list()
        self._update_result_ui()

    # —— 构建 UI ——

    def _build_fetch_box(self) -> QWidget:
        box = QFrame()
        box.setObjectName("HotFetchPanel")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)

        song_bar = QFrame()
        song_bar.setObjectName("HotSongBar")
        sb = QHBoxLayout(song_bar)
        sb.setContentsMargins(18, 14, 18, 14)
        sb.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(4)
        self._song_title = QLabel("下载与热评")
        self._song_title.setObjectName("HotSongTitle")
        self._song_meta = QLabel("粘贴链接或网易云歌曲 ID，点「获取」")
        self._song_meta.setObjectName("HotSongMeta")
        left.addWidget(self._song_title)
        left.addWidget(self._song_meta)
        sb.addLayout(left, 1)
        self._btn_trial = QPushButton(_TRIAL_LABEL)
        self._btn_trial.setObjectName("HotChip")
        self._btn_trial.setToolTip("一键试例：周杰伦《晴天》")
        self._btn_trial.clicked.connect(self._on_trial)
        sb.addWidget(self._btn_trial, 0, Qt.AlignVCenter)
        lay.addWidget(song_bar)

        fetch_row = QFrame()
        fetch_row.setObjectName("HotFetchRow")
        fr = QHBoxLayout(fetch_row)
        fr.setContentsMargins(12, 10, 12, 10)
        fr.setSpacing(8)
        self._url_edit = QLineEdit()
        self._url_edit.setObjectName("HotUrlEdit")
        self._url_edit.setMinimumHeight(36)
        self._url_edit.setPlaceholderText(
            "网易云链接 / 歌曲 ID / 其它 yt-dlp 链接"
        )
        self._url_edit.returnPressed.connect(self._on_fetch)
        self._btn_fetch = QPushButton("获取")
        self._btn_fetch.setObjectName("primaryButton")
        self._btn_fetch.setMinimumHeight(36)
        self._btn_fetch.setMinimumWidth(88)
        self._btn_fetch.clicked.connect(self._on_fetch)
        fr.addWidget(self._url_edit, 1)
        fr.addWidget(self._btn_fetch)
        lay.addWidget(fetch_row)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_cap = QLabel("偏好")
        mode_cap.setObjectName("HotSongMeta")
        mode_row.addWidget(mode_cap)
        seg = QFrame()
        seg.setObjectName("HotSegment")
        seg_lay = QHBoxLayout(seg)
        seg_lay.setContentsMargins(4, 4, 4, 4)
        seg_lay.setSpacing(0)
        self._mode_audio = QRadioButton("音频")
        self._mode_video = QRadioButton("视频")
        self._mode_audio.setObjectName("HotSegmentBtn")
        self._mode_video.setObjectName("HotSegmentBtn")
        self._mode_audio.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self._mode_audio)
        grp.addButton(self._mode_video)
        seg_lay.addWidget(self._mode_audio)
        seg_lay.addWidget(self._mode_video)
        mode_row.addWidget(seg)
        mode_row.addStretch()
        lay.addLayout(mode_row)

        out_row = QHBoxLayout()
        out_row.setSpacing(8)
        out_cap = QLabel("保存到")
        out_cap.setObjectName("HotSongMeta")
        self._out_label = QLabel(self._out_dir)
        self._out_label.setObjectName("HotPathMuted")
        self._out_label.setWordWrap(True)
        btn_out = QPushButton("更改…")
        btn_out.setObjectName("HotGhostBtn")
        btn_out.clicked.connect(self._on_pick_dir)
        out_row.addWidget(out_cap)
        out_row.addWidget(self._out_label, 1)
        out_row.addWidget(btn_out)
        lay.addLayout(out_row)

        cookie_row = QHBoxLayout()
        cookie_row.setSpacing(8)
        cookie_cap = QLabel("Cookie")
        cookie_cap.setObjectName("HotSongMeta")
        self._cookie_label = QLabel("未设置（抖音等站点需要）")
        self._cookie_label.setObjectName("HotPathMuted")
        self._cookie_label.setWordWrap(True)
        self._cookie_label.setToolTip(
            "Netscape 格式 cookies.txt。抖音必须；B 站大会员高画质可选。\n"
            "用浏览器扩展「Get cookies.txt LOCALLY」导出后在此选择。"
        )
        btn_cookie = QPushButton("Cookie…")
        btn_cookie.setObjectName("HotGhostBtn")
        btn_cookie.setToolTip("选择 Netscape cookies.txt（优先于从浏览器读取）")
        btn_cookie.clicked.connect(self._on_pick_cookies)
        btn_cookie_clear = QPushButton("清除")
        btn_cookie_clear.setObjectName("HotGhostBtn")
        btn_cookie_clear.clicked.connect(self._on_clear_cookies)
        cookie_row.addWidget(cookie_cap)
        cookie_row.addWidget(self._cookie_label, 1)
        cookie_row.addWidget(btn_cookie)
        cookie_row.addWidget(btn_cookie_clear)
        lay.addLayout(cookie_row)
        cookie_hint = QLabel(
            "抖音须含 douyin 域名条目的 Netscape cookies.txt（勿选 app.conf / 空文件）"
        )
        cookie_hint.setObjectName("HotPathMuted")
        cookie_hint.setWordWrap(True)
        lay.addWidget(cookie_hint)
        self._refresh_cookie_label()

        self._progress = QProgressBar()
        self._progress.setObjectName("HotProgress")
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        lay.addWidget(self._progress)

        self._status = QLabel("")
        self._status.setObjectName("HotStatus")
        self._status.setWordWrap(True)
        lay.addWidget(self._status)
        return box

    def _build_result_box(self) -> QWidget:
        box = QFrame()
        box.setObjectName("HotResultPanel")
        self._result_box = box
        lay = QVBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        media = QFrame()
        media.setObjectName("HotMediaCard")
        ml = QHBoxLayout(media)
        ml.setContentsMargins(16, 14, 14, 14)
        ml.setSpacing(14)

        self._kind_badge = QLabel("—")
        self._kind_badge.setObjectName("HotKindBadge")
        self._kind_badge.setAlignment(Qt.AlignCenter)
        self._kind_badge.setFixedWidth(48)
        ml.addWidget(self._kind_badge, 0, Qt.AlignTop)

        mid = QVBoxLayout()
        mid.setSpacing(4)
        self._media_name = QLabel("尚未获取媒体")
        self._media_name.setObjectName("HotMediaName")
        self._media_name.setWordWrap(True)
        self._media_name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._media_path_label = QLabel("从下方列表点选播放，或更换本地文件")
        self._media_path_label.setObjectName("HotMediaPath")
        self._media_path_label.setWordWrap(False)
        self._media_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._media_path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        mid.addWidget(self._media_name)
        mid.addWidget(self._media_path_label)
        mid.addStretch()
        ml.addLayout(mid, 1)

        actions = QVBoxLayout()
        actions.setSpacing(6)
        self._btn_pick = QPushButton("更换本地…")
        self._btn_pick.setObjectName("HotGhostBtn")
        self._btn_pick.clicked.connect(self._on_pick_media)
        self._btn_export = QPushButton("导出评论…")
        self._btn_export.setObjectName("HotGhostBtn")
        self._btn_export.setToolTip(
            "导出 JSON（完整包）或 ASS（顺序字幕，可供竖屏烧录）；"
            "弹幕风短视频成片接口已预留"
        )
        self._btn_export.setEnabled(False)
        self._btn_export.clicked.connect(self._on_export_comments)
        self._btn_home = QPushButton("送首页播放")
        self._btn_home.setObjectName("primaryButton")
        self._btn_home.setEnabled(False)
        self._btn_home.clicked.connect(self._on_send_home)
        actions.addWidget(self._btn_home)
        actions.addWidget(self._btn_export)
        actions.addWidget(self._btn_pick)
        actions.addStretch()
        ml.addLayout(actions)
        lay.addWidget(media)

        list_head = QHBoxLayout()
        list_title = QLabel("媒体列表")
        list_title.setObjectName("HotSectionTitle")
        list_head.addWidget(list_title)
        self._media_list_badge = QLabel("0 项")
        self._media_list_badge.setObjectName("HotCountBadge")
        list_head.addWidget(self._media_list_badge)
        list_head.addStretch()
        lay.addLayout(list_head)

        hint = QLabel(
            "历史：已播过/下载的会自动保留。双击播放；「恢复历史」重载缓存列表"
        )
        hint.setObjectName("HotPathMuted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._media_list = _BoundedListWidget()
        self._media_list.setObjectName("HotMediaList")
        self._media_list.setMinimumHeight(140)
        self._media_list.setMaximumHeight(220)
        self._media_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._media_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._media_list.setTextElideMode(Qt.ElideMiddle)
        self._media_list.setWordWrap(False)
        self._media_list.setUniformItemSizes(True)
        self._media_list.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self._media_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        sp = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        sp.setHorizontalStretch(1)
        self._media_list.setSizePolicy(sp)
        self._media_list.itemDoubleClicked.connect(self._on_media_item_activate)
        self._media_list.currentItemChanged.connect(self._on_media_current_changed)
        lay.addWidget(self._media_list)

        list_act = QHBoxLayout()
        self._btn_play_item = QPushButton("播放选中")
        self._btn_play_item.setObjectName("primaryButton")
        self._btn_play_item.clicked.connect(self._on_play_selected)
        self._btn_dl_item = QPushButton("下载到媒体槽")
        self._btn_dl_item.setObjectName("HotGhostBtn")
        self._btn_dl_item.clicked.connect(self._on_download_selected)
        self._btn_del_item = QPushButton("移除选中")
        self._btn_del_item.setObjectName("HotGhostBtn")
        self._btn_del_item.setToolTip("从列表移除；若已缓存可一并删除本地历史文件")
        self._btn_del_item.clicked.connect(self._on_remove_selected)
        self._btn_clear_list = QPushButton("恢复历史")
        self._btn_clear_list.setObjectName("HotGhostBtn")
        self._btn_clear_list.setToolTip("丢弃未下载的临时项，重新载入本地历史")
        self._btn_clear_list.clicked.connect(self._on_clear_media_list)
        list_act.addWidget(self._btn_play_item)
        list_act.addWidget(self._btn_dl_item)
        list_act.addWidget(self._btn_del_item)
        list_act.addWidget(self._btn_clear_list)
        list_act.addStretch()
        lay.addLayout(list_act)

        head = QHBoxLayout()
        title = QLabel("评论 / 弹幕")
        title.setObjectName("HotSectionTitle")
        head.addWidget(title)
        self._count_badge = QLabel("0 条")
        self._count_badge.setObjectName("HotCountBadge")
        head.addWidget(self._count_badge)
        head.addStretch()
        lay.addLayout(head)

        self._comment_list = QListWidget()
        self._comment_list.setObjectName("HotCommentList")
        self._comment_list.setMinimumHeight(220)
        self._comment_list.setSpacing(6)
        self._comment_list.setUniformItemSizes(False)
        self._comment_list.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding,
        )
        lay.addWidget(self._comment_list, 1)
        return box

    # —— 一步获取 ——

    @Slot()
    def _on_trial(self):
        self._url_edit.setText(_TRIAL_ID)
        self._mode_audio.setChecked(True)
        self._on_fetch()

    @Slot()
    def _on_pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存目录", self._out_dir)
        if d:
            self._out_dir = d
            self._out_label.setText(d)

    def _refresh_cookie_label(self):
        path = ""
        try:
            path = getattr(self._vm._app, "yt_dlp_cookies_file", "") or ""
        except Exception:
            path = ""
        if path and os.path.isfile(path):
            self._cookie_label.setText(_elide_list_label(path, 56))
            self._cookie_label.setToolTip(
                f"{path}\n已启用：yt-dlp 优先用此文件（抖音/大会员等）。"
            )
            self._cookie_label.setProperty("tone", "ok")
        elif path:
            self._cookie_label.setText(f"文件不存在：{_elide_list_label(path, 40)}")
            self._cookie_label.setToolTip(path)
            self._cookie_label.setProperty("tone", "danger")
        else:
            self._cookie_label.setText("未设置（抖音等站点需要）")
            self._cookie_label.setToolTip(
                "Netscape 格式 cookies.txt。抖音必须；B 站大会员高画质可选。\n"
                "用浏览器扩展「Get cookies.txt LOCALLY」导出后点「Cookie…」选择。"
            )
            self._cookie_label.setProperty("tone", "")
        self._cookie_label.style().unpolish(self._cookie_label)
        self._cookie_label.style().polish(self._cookie_label)

    @Slot()
    def _on_pick_cookies(self):
        start = ""
        try:
            start = getattr(self._vm._app, "yt_dlp_cookies_file", "") or ""
        except Exception:
            start = ""
        if not start or not os.path.isdir(os.path.dirname(start)):
            start = self._out_dir
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Netscape cookies.txt（不要选 app.conf）",
            os.path.dirname(start) if start else os.path.expanduser("~\\Downloads"),
            "Cookie 文本 (cookies.txt *.txt);;所有文件 (*.*)",
        )
        if not path:
            return
        # 启动对话框默认过滤提示：禁止误选配置文件
        base = os.path.basename(path).lower()
        if base in {"app.conf", "app.config", "settings.ini", "config.ini"}:
            QMessageBox.warning(
                self,
                "选错文件了",
                "请不要选择 app.conf。\n\n"
                "正确步骤：\n"
                "1) 浏览器打开 douyin.com\n"
                "2) 用扩展「Get cookies.txt LOCALLY」导出\n"
                "3) 这里选择导出的 cookies.txt",
            )
            return
        try:
            self._vm.set_yt_dlp_cookies_file(path)
        except Exception as e:
            QMessageBox.warning(self, "Cookie 设置失败", str(e))
            return
        self._refresh_cookie_label()
        warn = getattr(getattr(self._vm, "_app", None), "_yt_cookies_warn", "") or ""
        tip = f"已设置 Cookie：{os.path.basename(path)} · 请重新「获取」"
        if warn == "warn_no_douyin":
            tip += "（文件里没有 douyin 域名，抖音可能仍失败）"
            QMessageBox.warning(
                self,
                "Cookie 可能无效",
                "已保存，但文件中没有 douyin.com 相关 Cookie。\n\n"
                "请先打开 https://www.douyin.com 再 Export 导出，"
                "确保文件里有多行（不是只有两行注释）。",
            )
        self._status.setText(tip)
        self._status.setProperty("tone", "ok" if warn != "warn_no_douyin" else "danger")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        if warn != "warn_no_douyin":
            QMessageBox.information(
                self,
                "Cookie 已设置",
                "已写入配置并立即生效。\n"
                "请重新点「获取」打开抖音链接。\n\n"
                "提示：Cookie 过期后需重新导出。",
            )

    @Slot()
    def _on_clear_cookies(self):
        try:
            self._vm.set_yt_dlp_cookies_file("")
        except Exception as e:
            QMessageBox.warning(self, "清除失败", str(e))
            return
        self._refresh_cookie_label()
        self._status.setText("已清除 Cookie 文件")
        self._status.setProperty("tone", "ok")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    @Slot()
    def _on_fetch(self):
        text = self._url_edit.text().strip()
        if not text:
            QMessageBox.warning(self, "提示", "请先粘贴链接或歌曲 ID")
            return
        if self._busy:
            QMessageBox.information(self, "提示", "正在获取，请稍候…")
            return

        song_id = parse_song_id(text)
        bili = False
        if song_id:
            probe_url = f"https://music.163.com/#/song?id={song_id}"
            comment_input = song_id
            comment_mode = "netease"
        else:
            if not (text.startswith("http://") or text.startswith("https://")):
                QMessageBox.warning(
                    self, "提示",
                    "无法识别为网易云歌曲 ID，请填写完整 http(s) 链接。",
                )
                return
            probe_url = normalize_webpage_url(text)
            bili = is_bilibili_url(probe_url) or is_bilibili_url(text)
            comment_input = probe_url if bili else ""
            comment_mode = "bilibili" if bili else ""
            if probe_url != text:
                self._url_edit.setText(probe_url)
                self._status.setText(f"已规范化链接：{probe_url}")

        self._manual_download = False
        self._awaiting_fetch = False
        self._play_after_download = False
        self._pending_cache_item = None
        self._pending_list_row = -1
        self._probe_for_select = True
        self._comments = []
        self._song_id = ""
        self._song_name = ""
        self._comment_source = ""
        self._comment_list.clear()
        # 保留媒体历史列表，新勾选项稍后插入顶部
        self._media_path = ""
        self._update_result_ui()

        self._comments_done = not bool(comment_input)
        self._set_busy(True)
        self._progress.setVisible(True)
        self._progress.setValue(15)

        if comment_input and comment_mode == "netease":
            self._status.setText("正在拉取热评并探测媒体信息（不下载）…")
            self._song_meta.setText(f"ID {comment_input} · 获取中…")
            self._start_comment_fetch(comment_input, mode="netease")
        elif comment_input and comment_mode == "bilibili":
            self._status.setText("正在拉取 B 站弹幕并探测媒体信息（不下载）…")
            self._song_meta.setText("B站 · 弹幕获取中…")
            # B 站默认要视频+音轨，避免「音频」偏好抽成 MP3
            self._mode_video.setChecked(True)
            self._start_comment_fetch(comment_input, mode="bilibili")
        else:
            self._status.setText("正在探测媒体信息（不下载）…")
            self._song_title.setText("下载与热评")
            self._song_meta.setText("探测中…")

        self._vm.probe_download_url(probe_url, True)

    def _open_select_dialog(self, info: UrlMediaInfo):
        self._last_probe_info = info
        self._info_title = display_title(info)
        self._song_title.setText(info.title or self._song_title.text() or "媒体")
        self._song_meta.setText(
            f"{info.uploader or '—'} · {info.duration_sec:.0f}s · 已探测，请勾选加入列表"
        )
        if info.webpage_url:
            self._page_url = info.webpage_url
        elif info.url:
            self._page_url = info.url

        dlg = MediaSelectDialog(
            info,
            prefer_audio=self._mode_audio.isChecked(),
            parent=self,
        )
        if dlg.exec() != QDialog.Accepted:
            self._status.setText("已获取信息；未加入列表。可再次点「获取」重新勾选。")
            self._status.setProperty("tone", "ok")
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)
            return

        items = dlg.checked_items()
        want_audio = dlg.want_audio()
        # 勾选了音画合并时，不按「优先音频」抽成 MP3
        if any(
            (it.name or "").startswith("音画合并")
            or (getattr(it, "has_video", False) and getattr(it, "has_audio", False))
            for it in items
        ):
            want_audio = False
            self._mode_video.setChecked(True)
        self._media_kind = "audio" if want_audio else "video"
        self._add_items_to_list(info, items, want_audio)
        self._status.setText(
            f"已加入列表 {len(items)} 项 · 双击或「播放选中」即可拉取播放"
        )
        self._status.setProperty("tone", "ok")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    def _add_items_to_list(
        self,
        info: UrlMediaInfo,
        items: List[UrlListItem],
        audio_only: bool,
    ):
        page = info.webpage_url or info.url or self._page_url
        page = normalize_webpage_url(page) if page else ""
        existing = self._existing_list_keys()
        inserted = 0
        for it in reversed(items):
            if not getattr(it, "page_url", ""):
                it.page_url = page
            # 音画合并项始终按视频+音轨拉取，不受「优先音频」影响
            item_audio = bool(audio_only) and not self._item_wants_av(it)
            pk = media_pk(page, it) if page else ""
            cached = self._cache.find_media(page, it) if page else None
            local = cached if cached and os.path.isfile(cached) else ""
            # 缓存声称音画却是无声/纯 mp3：丢弃，强制重下
            if local and not item_audio:
                local = self._invalidate_bad_av_local(local)
            if pk and pk in existing:
                continue
            if local and local in existing:
                continue
            row = self._make_list_row(
                it,
                page=page,
                audio_only=item_audio,
                local=local,
                pk=pk,
                page_title=info.title or "",
            )
            self._media_list.insertItem(0, row)
            if pk:
                existing.add(pk)
            if local:
                existing.add(local)
            inserted += 1
        self._trim_media_list()
        self._media_list_badge.setText(f"{self._media_list.count()} 项")
        if inserted and self._media_list.count():
            self._media_list.setCurrentRow(0)

    @staticmethod
    def _item_wants_av(data: UrlListItem) -> bool:
        """是否应按音画合并（画面+音轨）处理。"""
        name = getattr(data, "name", "") or ""
        if name.startswith("音画合并"):
            return True
        return bool(
            getattr(data, "has_video", False) and getattr(data, "has_audio", False)
        )

    def _local_has_av(self, path: str) -> bool:
        """本地成片是否含音轨（音画项用）。"""
        try:
            from core.media_bridge import _file_has_audio_stream
            return _file_has_audio_stream(path)
        except Exception:
            return True

    def _invalidate_bad_av_local(self, path: str) -> str:
        """音画项若本地是 mp3 / 无音轨，返回空串强制重下。"""
        if not path or not os.path.isfile(path):
            return ""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".mp3" or not self._local_has_av(path):
            return ""
        return path

    def _kind_for_play(self, data: UrlListItem, audio_only: bool) -> str:
        if audio_only:
            return "audio"
        if self._item_wants_av(data):
            return "video"
        ext = os.path.splitext(getattr(data, "ext", "") or "")[1].lower()
        if not ext and getattr(data, "ext", ""):
            ext = f".{str(data.ext).lstrip('.').lower()}"
        if ext in _AUDIO_EXTS or (
            getattr(data, "has_audio", False) and not getattr(data, "has_video", False)
        ):
            return "audio"
        return "video"

    def _existing_list_keys(self) -> Set[str]:
        keys: Set[str] = set()
        for i in range(self._media_list.count()):
            it = self._media_list.item(i)
            if not it:
                continue
            pk = it.data(_ROLE_PK) or ""
            local = it.data(_ROLE_LOCAL) or ""
            if pk:
                keys.add(pk)
            if local:
                keys.add(local)
        return keys

    def _make_list_row(
        self,
        item: UrlListItem,
        *,
        page: str,
        audio_only: bool,
        local: str = "",
        pk: str = "",
        page_title: str = "",
        cached_at: float = 0.0,
    ) -> QListWidgetItem:
        label = item.name or "未命名"
        if page_title and page_title not in label:
            label = f"{page_title} · {label}"
        if item.detail and item.detail not in label:
            label = f"{label}    ({item.detail})"
        if audio_only:
            label = f"[音频] {label}"
        if local and os.path.isfile(local):
            stamp = ""
            if cached_at:
                stamp = time.strftime(" %m-%d %H:%M", time.localtime(cached_at))
            label = f"♪ {label}  [已缓存]{stamp}"
        else:
            label = f"▸ {label}"
        full_label = label
        label = _elide_list_label(label)
        row = QListWidgetItem(label)
        row.setData(_ROLE_ITEM, item)
        row.setData(_ROLE_PAGE, page)
        row.setData(_ROLE_AUDIO, audio_only)
        row.setData(_ROLE_LOCAL, local if local and os.path.isfile(local) else "")
        row.setData(_ROLE_PK, pk)
        tip_parts = [full_label]
        if page:
            tip_parts.append(page)
        if local:
            tip_parts.append(local)
        row.setToolTip("\n".join(tip_parts))
        return row

    def _list_item_from_cache(self, m: MediaCacheItem) -> QListWidgetItem:
        audio_only = bool(m.has_audio and not m.has_video)
        if not audio_only and m.ext and f".{m.ext.lstrip('.')}".lower() in _AUDIO_EXTS:
            audio_only = True
        want_av = (m.item_name or "").startswith("音画合并") or (
            bool(m.has_video) and bool(m.has_audio)
        )
        local = m.media_path if m.media_path and os.path.isfile(m.media_path) else ""
        # 名称像音画合并却是 mp3 / 无音轨：不当可用缓存，播放时重下
        if want_av and local:
            local = self._invalidate_bad_av_local(local)
            audio_only = False
        item = UrlListItem(
            name=m.item_name or m.page_title or "未命名",
            detail=m.format_id or "",
            url=m.page_url,
            kind=m.kind or ("default" if want_av and not m.format_id else "format"),
            format_id=m.format_id or "",
            page_url=m.page_url,
            ext=m.ext or ("mp4" if want_av else ""),
            has_video=bool(m.has_video) or want_av,
            has_audio=bool(m.has_audio) or want_av,
        )
        return self._make_list_row(
            item,
            page=m.page_url or "",
            audio_only=False if want_av else audio_only,
            local=local,
            pk=m.pk,
            page_title=m.page_title or "",
            cached_at=m.cached_at,
        )

    def _reload_history_list(self):
        """从本地缓存载入已播过/下载过的媒体。"""
        self._media_list.clear()
        history = self._cache.list_media_items()[:_HISTORY_LIMIT]
        for m in history:
            if not m.media_path or not os.path.isfile(m.media_path):
                continue
            self._media_list.addItem(self._list_item_from_cache(m))
        self._media_list_badge.setText(f"{self._media_list.count()} 项")
        n = self._media_list.count()
        if n:
            self._status.setText(f"已载入历史 {n} 项 · 可直接点选播放")
            self._status.setProperty("tone", "ok")
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)

    def _trim_media_list(self):
        while self._media_list.count() > _HISTORY_LIMIT + 10:
            self._media_list.takeItem(self._media_list.count() - 1)

    def _selected_media_row(self) -> Optional[QListWidgetItem]:
        row = self._media_list.currentRow()
        if row < 0:
            return None
        return self._media_list.item(row)

    @Slot(QListWidgetItem, QListWidgetItem)
    def _on_media_current_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None,
    ):
        if current is None:
            return
        page = current.data(_ROLE_PAGE) or ""
        if page and not self._busy:
            # 方便继续拉热评或再次获取，无需手动粘贴
            self._url_edit.setText(page)
            self._page_url = page


    @Slot(QListWidgetItem)
    def _on_media_item_activate(self, _item: QListWidgetItem):
        self._on_play_selected()

    @Slot()
    def _on_play_selected(self):
        self._fetch_selected_item(play_after=True)

    @Slot()
    def _on_download_selected(self):
        self._fetch_selected_item(play_after=False)

    def _fetch_selected_item(self, *, play_after: bool):
        it = self._selected_media_row()
        if it is None:
            QMessageBox.warning(self, "提示", "请先选中媒体列表中的一项")
            return
        if self._busy:
            QMessageBox.information(self, "提示", "正在处理，请稍候…")
            return

        data = it.data(_ROLE_ITEM)
        if not isinstance(data, UrlListItem):
            QMessageBox.warning(self, "提示", "列表项无效，请重新获取")
            return

        page = it.data(_ROLE_PAGE) or self._page_url or ""
        page = normalize_webpage_url(page) if page else ""
        audio_only = bool(it.data(_ROLE_AUDIO))
        # 音画合并项禁止抽成纯音频
        if self._item_wants_av(data):
            audio_only = False
            it.setData(_ROLE_AUDIO, False)
        local = it.data(_ROLE_LOCAL) or ""
        play_kind = self._kind_for_play(data, audio_only)

        # 历史里误存的无声音画 / 音画名却是 mp3 → 清掉重下
        if local and os.path.isfile(local) and not audio_only and self._item_wants_av(data):
            if not self._invalidate_bad_av_local(local):
                self._status.setText("缓存无完整音画，正在重新下载合并…")
                it.setData(_ROLE_LOCAL, "")
                local = ""

        if local and os.path.isfile(local):
            self._set_media(local, play_kind)
            self._status.setText(f"已选用: {os.path.basename(local)}")
            # 再次播放也提到顶部
            row = self._media_list.row(it)
            if row > 0:
                self._media_list.takeItem(row)
                self._media_list.insertItem(0, it)
                self._media_list.setCurrentRow(0)
            if play_after:
                self.playWithCommentsRequested.emit(local, list(self._comments))
            return

        cached = self._cache.find_media(page, data) if page else None
        if cached and os.path.isfile(cached):
            if not audio_only and self._item_wants_av(data):
                cached = self._invalidate_bad_av_local(cached) or ""
            if cached:
                it.setData(_ROLE_LOCAL, cached)
                self._refresh_list_item_label(it)
                self._set_media(cached, play_kind)
                self._status.setText(f"已命中缓存: {os.path.basename(cached)}")
                row = self._media_list.row(it)
                if row > 0:
                    self._media_list.takeItem(row)
                    self._media_list.insertItem(0, it)
                    self._media_list.setCurrentRow(0)
                if play_after:
                    self.playWithCommentsRequested.emit(cached, list(self._comments))
                return

        fid = ""
        kind = getattr(data, "kind", "") or ""
        if kind == "format":
            fid = getattr(data, "format_id", "") or ""
        elif kind == "entry":
            page = normalize_webpage_url(
                getattr(data, "url", "") or getattr(data, "page_url", "") or page
            )
            fid = ""
        elif kind == "default":
            fid = ""

        if not page:
            QMessageBox.warning(self, "提示", "缺少页面链接，无法拉取")
            return

        self._media_kind = play_kind
        self._play_after_download = play_after
        self._awaiting_fetch = True
        self._manual_download = not play_after
        self._pending_cache_item = data
        self._pending_list_row = self._media_list.currentRow()
        self._page_url = page or self._page_url
        self._set_busy(True)
        self._progress.setVisible(True)
        self._progress.setValue(0)
        action = "拉取并播放" if play_after else "下载"
        self._status.setText(f"正在{action}：{(data.name or '')[:60]}…")
        self._vm.start_url_download(
            page,
            self._out_dir,
            audio_only=audio_only,
            format_id=fid,
        )

    def _refresh_list_item_label(self, it: QListWidgetItem):
        data = it.data(_ROLE_ITEM)
        if not isinstance(data, UrlListItem):
            return
        audio_only = bool(it.data(_ROLE_AUDIO))
        local = it.data(_ROLE_LOCAL) or ""
        page = it.data(_ROLE_PAGE) or ""
        page_title = ""
        # 尽量保留「歌名 · 条目」可读性
        text = it.text()
        if " · " in text:
            raw = text.lstrip("♪▸ ").split("  [")[0]
            if raw.startswith("[音频] "):
                raw = raw[len("[音频] "):]
            parts = raw.split(" · ", 1)
            if len(parts) == 2:
                page_title = parts[0]
        label = data.name or "未命名"
        if page_title and page_title not in label:
            label = f"{page_title} · {label}"
        if data.detail and data.detail not in label:
            label = f"{label}    ({data.detail})"
        if audio_only:
            label = f"[音频] {label}"
        if local and os.path.isfile(local):
            label = f"♪ {label}  [已缓存]"
        else:
            label = f"▸ {label}"
        full_label = label
        it.setText(_elide_list_label(label))
        tip_parts = [full_label]
        if page:
            tip_parts.append(page)
        if local:
            tip_parts.append(local)
        it.setToolTip("\n".join(tip_parts))

    @Slot()
    def _on_remove_selected(self):
        row = self._media_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先选中要移除的项")
            return
        it = self._media_list.item(row)
        pk = (it.data(_ROLE_PK) or "") if it else ""
        local = (it.data(_ROLE_LOCAL) or "") if it else ""
        if pk and local and os.path.isfile(local):
            reply = QMessageBox.question(
                self,
                "移除历史",
                "同时从本地历史缓存中删除该文件？\n（仅移出列表选「否」）",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            )
            if reply == QMessageBox.Cancel:
                return
            if reply == QMessageBox.Yes:
                hit = self._cache.get_media_item(pk)
                if hit:
                    self._cache.delete_media_item(hit)
        self._media_list.takeItem(row)
        self._media_list_badge.setText(f"{self._media_list.count()} 项")

    @Slot()
    def _on_clear_media_list(self):
        """恢复为本地历史列表（丢掉未下载的临时勾选项）。"""
        self._reload_history_list()
        if self._media_list.count() == 0:
            self._status.setText("暂无历史记录 · 获取并播放后会出现在这里")
            self._status.setProperty("tone", "")
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)
    def _start_comment_fetch(self, song_input: str, *, mode: str = "netease"):
        if self._thread and self._thread.isRunning():
            return
        app = AppLogic()
        self._thread = QThread(self)
        self._worker = _CommentFetchWorker(
            song_input,
            app.netease_hot_comments_script,
            getattr(app, "netease_api_base", "") or "",
            app.netease_hot_comments_demo,
            mode=mode,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_comments_fetched)
        self._worker.failed.connect(self._on_comments_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_comment_worker)
        self._thread.start()

    @Slot(object)
    def _on_comments_fetched(self, result: object):
        self._comments_done = True
        if isinstance(result, FetchResult):
            self._comments = list(result.comments)
            self._song_id = result.song_id or ""
            self._song_name = result.song_name or ""
            self._comment_source = result.source or ""
            self._song_title.setText(result.song_name or "热评")
            src = result.source_label
            if result.source == "bilibili":
                self._song_title.setText(result.song_name or "B站")
                self._song_meta.setText(
                    f"{result.song_id} · 弹幕 {len(self._comments)} 条 · {src}"
                )
            else:
                self._song_meta.setText(
                    f"ID {result.song_id} · {len(self._comments)} 条 · {src}"
                )
            self._fill_comment_list()
            note = result.message
            if result.source == "demo":
                self._status.setProperty("tone", "warn")
            elif result.source == "cache":
                self._status.setProperty("tone", "ok")
            else:
                self._status.setProperty("tone", "")
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)
            self._update_result_ui()
        else:
            note = "热评结果异常"
            self._status.setProperty("tone", "danger")
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)
        self._merge_status(comments_note=note)

    @Slot(str)
    def _on_comments_failed(self, message: str):
        self._comments_done = True
        self._comments = []
        self._song_id = ""
        self._song_name = ""
        self._comment_source = ""
        self._fill_comment_list()
        self._status.setProperty("tone", "danger")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        self._merge_status(comments_note=f"热评失败: {message}")

    def _fill_comment_list(self):
        self._comment_list.clear()
        if not self._comments:
            empty = QListWidgetItem("获取后热评或 B 站弹幕会出现在这里")
            empty.setFlags(Qt.NoItemFlags)
            empty.setTextAlignment(Qt.AlignCenter)
            empty.setSizeHint(QSize(0, 72))
            self._comment_list.addItem(empty)
            self._count_badge.setText("0 条")
            return

        self._count_badge.setText(f"{len(self._comments)} 条")
        for c in self._comments:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, c)
            row = self._make_comment_row(c)
            hint_h = max(56, 28 + 18 * (1 + len((c.content or "")) // 42))
            item.setSizeHint(QSize(0, hint_h))
            self._comment_list.addItem(item)
            self._comment_list.setItemWidget(item, row)
            row.adjustSize()
            item.setSizeHint(row.sizeHint().expandedTo(QSize(0, hint_h)))

    def _make_comment_row(self, c: HotComment) -> QWidget:
        w = QFrame()
        w.setObjectName("HotCommentRow")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(8)
        nick = QLabel(c.nickname or "匿名")
        nick.setObjectName("HotCommentNick")
        like = QLabel(f"♥ {c.liked_count}" if c.liked_count else "♥ ·")
        like.setObjectName("HotCommentLike")
        top.addWidget(nick)
        top.addStretch()
        top.addWidget(like)
        body = QLabel((c.content or "").strip().replace("\n", " "))
        body.setObjectName("HotCommentBody")
        body.setWordWrap(True)
        lay.addLayout(top)
        lay.addWidget(body)
        w.adjustSize()
        return w

    def _merge_status(self, *, comments_note: str = "", media_note: str = ""):
        parts = []
        if comments_note:
            parts.append(comments_note)
        if media_note:
            parts.append(media_note)
        if self._media_path and not media_note:
            parts.append(f"媒体已就绪: {os.path.basename(self._media_path)}")
        if self._comments and not comments_note:
            parts.append(f"评论 {len(self._comments)} 条")
        if self._media_list.count() and not media_note:
            parts.append(f"列表 {self._media_list.count()} 项")
        if parts:
            self._status.setText(" · ".join(parts))

    def _set_media(self, path: str, kind: str = ""):
        if path and os.path.isfile(path):
            self._media_path = path
            if kind:
                self._media_kind = kind
            elif not self._media_kind:
                ext = os.path.splitext(path)[1].lower()
                self._media_kind = "audio" if ext in _AUDIO_EXTS else "video"
        else:
            self._media_path = ""
        self._update_result_ui()

    def _update_result_ui(self):
        if self._media_path and os.path.isfile(self._media_path):
            name = os.path.basename(self._media_path)
            self._media_name.setText(_elide_list_label(name, 48))
            self._media_name.setToolTip(name)
            self._media_path_label.setText(_elide_list_label(self._media_path, 72))
            self._media_path_label.setToolTip(self._media_path)
            kind = self._media_kind or "media"
            if kind == "audio":
                self._kind_badge.setText("音频")
                self._kind_badge.setProperty("kind", "audio")
            else:
                self._kind_badge.setText("视频")
                self._kind_badge.setProperty("kind", "video")
            self._kind_badge.style().unpolish(self._kind_badge)
            self._kind_badge.style().polish(self._kind_badge)
            self._btn_home.setEnabled(True)
        else:
            self._media_name.setText("尚未获取媒体")
            self._media_path_label.setText("从下方列表点选播放，或更换本地文件")
            self._kind_badge.setText("—")
            self._kind_badge.setProperty("kind", "")
            self._kind_badge.style().unpolish(self._kind_badge)
            self._kind_badge.style().polish(self._kind_badge)
            self._btn_home.setEnabled(False)
        self._btn_export.setEnabled(bool(self._comments))
        if hasattr(self, "_count_badge"):
            n = len(self._comments)
            self._count_badge.setText(f"{n} 条")
        if not self._comments and self._comment_list.count() == 0:
            self._fill_comment_list()

    @Slot()
    def _on_pick_media(self):
        default = self._media_path or self._out_dir
        path, _ = QFileDialog.getOpenFileName(
            self, "选择唯一媒体文件",
            os.path.dirname(default) if default else "",
            "媒体 (*.mp4 *.mkv *.webm *.mp3 *.m4a *.wav *.flac);;所有文件 (*.*)",
        )
        if path:
            self._set_media(path)
            self._merge_status(media_note=f"已选用本地: {os.path.basename(path)}")

    def _ask_short_video_style(self) -> str:
        """选热评短视频风格；取消返回空串。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("热评短视频风格")
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("选择成片样式："))
        grp = QButtonGroup(dlg)
        r1 = QRadioButton("顺序字幕（底部逐条）")
        r2 = QRadioButton("弹幕风（横向滚动）")
        r3 = QRadioButton("卡片风（昵称 + 正文）")
        r1.setChecked(True)
        for i, r in enumerate((r1, r2, r3)):
            grp.addButton(r, i)
            lay.addWidget(r)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        lay.addWidget(buttons)
        if dlg.exec() != QDialog.Accepted:
            return ""
        checked = grp.checkedId()
        return {0: "ass_caption", 1: "danmaku", 2: "cards"}.get(checked, "ass_caption")

    @Slot()
    def _on_export_comments(self):
        if not self._comments:
            QMessageBox.information(self, "提示", "请先获取热评")
            return
        from core.comment_export import (
            CommentShortVideoRequest,
            build_export_package,
            export_comments_ass,
            export_comments_json,
            render_comment_short_video,
        )

        default_name = self._song_name or self._song_id or "hot_comments"
        for ch in r'\/:*?"<>|':
            default_name = default_name.replace(ch, "_")
        default_dir = self._out_dir if os.path.isdir(self._out_dir) else os.path.expanduser("~")
        path, selected = QFileDialog.getSaveFileName(
            self,
            "导出评论 / 热评短视频",
            os.path.join(default_dir, f"{default_name}_comments.json"),
            "评论 JSON (*.json);;顺序字幕 ASS (*.ass);;热评短视频 MP4 (*.mp4)",
        )
        if not path:
            return
        pkg = build_export_package(
            self._comments,
            song_id=self._song_id,
            song_name=self._song_name,
            media_path=self._media_path,
            media_kind=self._media_kind,
            source=self._comment_source,
        )
        try:
            lower = path.lower()
            sel = (selected or "").lower()
            want_mp4 = "mp4" in sel or "短视频" in sel or lower.endswith(".mp4")
            want_ass = (not want_mp4) and ("ass" in sel or lower.endswith(".ass"))
            if want_mp4:
                if not self._media_path or not os.path.isfile(self._media_path):
                    QMessageBox.warning(
                        self, "提示",
                        "导出热评短视频需要先有媒体文件（播放/下载一条到本地）。",
                    )
                    return
                style = self._ask_short_video_style()
                if not style:
                    return
                if not lower.endswith(".mp4"):
                    path = path + ".mp4"
                self._status.setText("正在生成热评短视频…")
                out = render_comment_short_video(
                    CommentShortVideoRequest(
                        media_path=self._media_path,
                        comments=list(self._comments),
                        output_path=path,
                        style=style,
                        song_name=self._song_name or "",
                        song_id=self._song_id or "",
                    ),
                    bridge=self._vm.bridge,
                )
                tip = f"已导出热评短视频（{style}）：\n{out}"
            elif want_ass:
                if not lower.endswith(".ass"):
                    path = path + ".ass"
                out = export_comments_ass(pkg, path)
                tip = (
                    f"已导出 ASS：\n{out}\n\n"
                    "可作竖屏字幕；也可用「热评短视频 MP4」一键成片。"
                )
            else:
                if not lower.endswith(".json"):
                    path = path + ".json"
                out = export_comments_json(pkg, path)
                tip = f"已导出 JSON：\n{out}"
            self._status.setText(f"已导出: {os.path.basename(out)}")
            QMessageBox.information(self, "导出完成", tip)
        except Exception as e:
            QMessageBox.warning(self, "导出失败", str(e))

    @Slot()
    def _on_send_home(self):
        if not self._media_path or not os.path.isfile(self._media_path):
            QMessageBox.information(self, "提示", "请先获取或选择一条媒体")
            return
        self.playWithCommentsRequested.emit(
            self._media_path, list(self._comments),
        )

    def focus_hot_tab(self):
        """菜单「热评弹幕」：滚到结果区评论列表。"""
        if self._result_box is not None:
            self._scroll.ensureWidgetVisible(self._result_box)
        self._comment_list.setFocus()

    def focus_comments(self):
        self.focus_hot_tab()

    def _set_busy(self, busy: bool):
        self._busy = busy
        self._btn_fetch.setEnabled(not busy)
        self._btn_trial.setEnabled(not busy)
        self._btn_play_item.setEnabled(not busy)
        self._btn_dl_item.setEnabled(not busy)

    @Slot(int, float, str)
    def _on_progress(self, _task_id: int, progress: float, msg: str):
        if self._awaiting_fetch or self._busy:
            self._progress.setVisible(True)
            self._progress.setValue(int(progress))
            self._status.setText(msg)

    @Slot(object)
    def _on_probe_ready(self, info):
        if not self._probe_for_select:
            return
        self._probe_for_select = False
        self._progress.setVisible(False)
        self._set_busy(False)
        if not info:
            self._status.setText("探测无结果")
            return
        try:
            self._cache.save_info(info)
        except Exception:
            pass
        self._open_select_dialog(info)

    @Slot(str)
    def _on_finished(self, path: str):
        was_fetch = self._awaiting_fetch
        play_after = self._play_after_download
        pending = self._pending_cache_item
        list_row = self._pending_list_row
        self._awaiting_fetch = False
        self._play_after_download = False
        self._pending_cache_item = None
        self._pending_list_row = -1
        self._manual_download = False
        self._set_busy(False)
        self._progress.setValue(100)
        self._progress.setVisible(False)

        if not was_fetch:
            return

        play_path = path
        if pending is not None and path and os.path.isfile(path):
            try:
                saved = self._cache.save_media(
                    self._page_url,
                    self._info_title,
                    pending,
                    path,
                )
                if saved:
                    play_path = saved
            except Exception:
                pass

        if play_path and os.path.isfile(play_path):
            if 0 <= list_row < self._media_list.count():
                row_item = self._media_list.item(list_row)
                if row_item:
                    row_item.setData(_ROLE_LOCAL, play_path)
                    if pending is not None and self._page_url:
                        row_item.setData(_ROLE_PK, media_pk(self._page_url, pending))
                    self._refresh_list_item_label(row_item)
                    # 刚播过的提到顶部，方便下次找
                    if list_row > 0:
                        self._media_list.takeItem(list_row)
                        self._media_list.insertItem(0, row_item)
                        self._media_list.setCurrentRow(0)
            kind = "video"
            if pending is not None:
                kind = self._kind_for_play(pending, False)
            elif play_path:
                ext = os.path.splitext(play_path)[1].lower()
                kind = "audio" if ext in _AUDIO_EXTS else "video"
            self._set_media(play_path, kind)
            self._status.setText(f"已就绪并写入历史：{os.path.basename(play_path)}")
            self._status.setProperty("tone", "ok")
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)
            if play_after:
                self.playWithCommentsRequested.emit(
                    play_path, list(self._comments),
                )

    @Slot(str)
    def _on_error(self, msg: str):
        if self._probe_for_select:
            self._probe_for_select = False
            self._set_busy(False)
            self._progress.setVisible(False)
            self._status.setProperty("tone", "danger")
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)
            self._status.setText("获取失败")
            QMessageBox.warning(self, "获取失败", msg)
            return
        if self._awaiting_fetch or self._manual_download or self._busy:
            self._awaiting_fetch = False
            self._play_after_download = False
            self._manual_download = False
            self._pending_cache_item = None
            self._pending_list_row = -1
            self._set_busy(False)
            self._progress.setVisible(False)
            self._status.setProperty("tone", "danger")
            self._status.style().unpolish(self._status)
            self._status.style().polish(self._status)
            self._status.setText("拉取失败")
            QMessageBox.warning(self, "拉取失败", msg)

    @Slot()
    def _cleanup_comment_worker(self):
        if self._worker:
            self._worker.deleteLater()
            self._worker = None
        if self._thread:
            self._thread.deleteLater()
            self._thread = None

    def shutdown(self):
        if self._thread and self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(2000)
