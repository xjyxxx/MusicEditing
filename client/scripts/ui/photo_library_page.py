"""macOS 风格本地照片图库：统一管理照片与视频，不移动原文件。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QPoint, QSize, Qt, Slot, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QImageReader, QPainter, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from core.image_loader import load_preview
from core.photo_library_index import PhotoAsset
from services.photo_library_service import PhotoLibraryService
from ui.background_task_manager import BackgroundTaskManager
from ui.photo_edit_dialog import PhotoEditDialog
from ui.zoomable_image_view import ZoomableImageView


class PhotoLibraryPage(QWidget):
    def __init__(self, vm, open_image_editor: Callable[[str, str], None],
                 open_video_editor: Callable[[str, str], None],
                 open_video_preview: Callable[[str], None], parent=None):
        super().__init__(parent)
        self._vm = vm
        self._open_image_editor = open_image_editor
        self._open_video_editor = open_video_editor
        self._open_video_preview = open_video_preview
        self._service = PhotoLibraryService(vm.bridge)
        self._tasks = BackgroundTaskManager(self, max_threads=4)
        self._tasks.taskSucceeded.connect(self._on_task_succeeded)
        self._tasks.taskFailed.connect(self._on_task_failed)
        self._section = "all"
        self._assets: dict[str, PhotoAsset] = {}
        self._thumb_generation = 0
        self._scan_running = False
        self._build_ui()
        self.refresh()


    def _build_ui(self) -> None:
        self.setObjectName("PhotoLibraryPage")
        self.setStyleSheet(self._stylesheet())
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        toolbar = QFrame()
        toolbar.setObjectName("PhotoToolbar")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(20, 12, 20, 12)
        brand = QLabel("照片")
        brand.setObjectName("PhotoBrand")
        bar.addWidget(brand)
        self._title = QLabel("所有项目")
        self._title.setObjectName("PhotoTitle")
        bar.addWidget(self._title)
        bar.addStretch()
        self._search = QLineEdit()
        self._search.setObjectName("PhotoSearch")
        self._search.setPlaceholderText("搜索照片和视频")
        self._search.setClearButtonEnabled(True)
        self._search.setFixedWidth(230)
        self._search.textChanged.connect(self.refresh)
        bar.addWidget(self._search)
        self._btn_add = QPushButton("添加图库")
        self._btn_add.setObjectName("PhotoPrimary")
        self._btn_add.clicked.connect(self._choose_root)
        bar.addWidget(self._btn_add)
        self._btn_refresh = QToolButton()
        self._btn_refresh.setText("↻")
        self._btn_refresh.setToolTip("重新扫描所有图库")
        self._btn_refresh.clicked.connect(self._start_scan)
        bar.addWidget(self._btn_refresh)
        root.addWidget(toolbar)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.addWidget(self._build_sidebar())
        split.addWidget(self._build_grid())
        split.addWidget(self._build_inspector())
        split.setSizes([176, 820, 244])
        root.addWidget(split, 1)

    def _build_sidebar(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("PhotoSidebar")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 18, 12, 12)
        lay.setSpacing(4)
        label = QLabel("图库")
        label.setObjectName("PhotoSectionLabel")
        lay.addWidget(label)
        self._nav: dict[str, QPushButton] = {}
        for key, text in (
            ("all", "所有项目"), ("photos", "照片"), ("videos", "视频"), ("favorites", "收藏"),
            ("edited", "已编辑"), ("live", "Live Photo"), ("locations", "地点照片"),
        ):
            button = QPushButton(text)
            button.setObjectName("PhotoNav")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=key: self._set_section(value))
            lay.addWidget(button)
            self._nav[key] = button
        self._nav["all"].setChecked(True)
        lay.addSpacing(16)
        roots_title = QLabel("我的图库")
        roots_title.setObjectName("PhotoSectionLabel")
        lay.addWidget(roots_title)
        self._roots = QListWidget()
        self._roots.setObjectName("PhotoRoots")
        self._roots.setMaximumHeight(180)
        lay.addWidget(self._roots)
        btn_remove = QPushButton("移除所选图库")
        btn_remove.setObjectName("PhotoSubtle")
        btn_remove.clicked.connect(self._remove_selected_root)
        lay.addWidget(btn_remove)
        lay.addStretch()
        privacy = QLabel("仅索引本机路径\n不会复制或上传原文件")
        privacy.setObjectName("PhotoPrivacy")
        privacy.setWordWrap(True)
        lay.addWidget(privacy)
        return panel


    def _build_grid(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("PhotoContent")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)
        self._summary = QLabel("选择「添加图库」开始建立本地索引")
        self._summary.setObjectName("PhotoSummary")
        lay.addWidget(self._summary)
        self._grid = QListWidget()
        self._grid.setObjectName("PhotoGrid")
        self._grid.setViewMode(QListWidget.IconMode)
        self._grid.setResizeMode(QListWidget.Adjust)
        self._grid.setMovement(QListWidget.Static)
        self._grid.setWrapping(True)
        self._grid.setWordWrap(True)
        self._grid.setSpacing(12)
        self._grid.setIconSize(QSize(170, 122))
        self._grid.setGridSize(QSize(188, 180))
        self._grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._grid.itemSelectionChanged.connect(self._on_selection_changed)
        self._grid.itemDoubleClicked.connect(lambda _item: self._open_selected())
        lay.addWidget(self._grid, 1)
        return panel

    def _build_inspector(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("PhotoInspector")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(16, 18, 16, 14)
        lay.setSpacing(10)
        cap = QLabel("信息")
        cap.setObjectName("PhotoSectionLabel")
        lay.addWidget(cap)
        self._preview = QLabel("未选择项目")
        self._preview.setObjectName("PhotoInspectorPreview")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumHeight(150)
        self._preview.setWordWrap(True)
        lay.addWidget(self._preview)
        self._name = QLabel("选择一张照片或视频")
        self._name.setObjectName("PhotoAssetName")
        self._name.setWordWrap(True)
        lay.addWidget(self._name)
        self._meta = QLabel("")
        self._meta.setObjectName("PhotoAssetMeta")
        self._meta.setWordWrap(True)
        lay.addWidget(self._meta)
        self._favorite = QPushButton("♡ 收藏")
        self._favorite.setObjectName("PhotoSubtle")
        self._favorite.clicked.connect(self._toggle_favorite)
        lay.addWidget(self._favorite)
        self._open = QPushButton("打开预览")
        self._open.setObjectName("PhotoPrimary")
        self._open.clicked.connect(self._open_selected)
        lay.addWidget(self._open)
        self._enhance = QPushButton("送去画质增强")
        self._enhance.clicked.connect(lambda: self._send_selected("enhance"))
        lay.addWidget(self._enhance)
        self._watermark = QPushButton("送去去水印")
        self._watermark.clicked.connect(lambda: self._send_selected("watermark"))
        lay.addWidget(self._watermark)
        self._edit = QPushButton("非破坏编辑")
        self._edit.clicked.connect(self._open_edit)
        lay.addWidget(self._edit)
        self._map = QPushButton("在地图中查看")
        self._map.setObjectName("PhotoSubtle")
        self._map.clicked.connect(self._open_map)
        lay.addWidget(self._map)
        lay.addStretch()
        self._set_inspector(None)
        return panel

    def _set_section(self, section: str) -> None:
        self._section = section
        for key, button in self._nav.items():
            button.setChecked(key == section)
        self.refresh()

    @Slot()
    def _choose_root(self) -> None:
        start = self._service.roots()[0] if self._service.roots() else str(Path.home() / "Pictures")
        root = QFileDialog.getExistingDirectory(self, "添加照片图库", start)
        if not root:
            return
        try:
            self._service.add_root(root)
        except ValueError as exc:
            QMessageBox.warning(self, "照片图库", str(exc))
            return
        self._start_scan()

    @Slot()
    def _remove_selected_root(self) -> None:
        item = self._roots.currentItem()
        if item is None:
            return
        root = str(item.data(Qt.UserRole) or "")
        if not root:
            return
        answer = QMessageBox.question(self, "移除图库", "只移除索引，不会删除原始文件。继续吗？")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._service.remove_root(root)
        self.refresh()


    @Slot()
    def _start_scan(self) -> None:
        if self._scan_running:
            return
        roots = self._service.roots()
        if not roots:
            self._choose_root()
            return
        self._scan_running = True
        self._btn_add.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._summary.setText("正在建立本地索引… 可继续浏览其它页面")
        self._tasks.submit("scan", lambda token: self._service.scan(roots, token))

    @Slot(str, object)
    def _on_task_succeeded(self, key: str, result: object) -> None:
        if key == "scan":
            changed, scanned = result
            self._on_scan_finished(int(changed), int(scanned), "")
        elif key.startswith("photo-thumb:"):
            generation, path, image = result
            self._on_photo_thumb_ready(int(generation), str(path), image)
        elif key.startswith("video-thumb:"):
            generation, path, thumb_path = result
            self._on_video_thumb_ready(int(generation), str(path), str(thumb_path))

    @Slot(str, str)
    def _on_task_failed(self, key: str, message: str) -> None:
        if key == "scan":
            self._on_scan_finished(0, 0, message)

    def _on_scan_finished(self, changed: int, scanned: int, error: str) -> None:
        self._scan_running = False
        self._btn_add.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        if error:
            QMessageBox.warning(self, "照片图库", f"索引失败：{error}")
        else:
            self._summary.setText(f"已扫描 {scanned} 个媒体文件 · 更新 {changed} 项")
        self.refresh()

    @Slot()
    def refresh(self) -> None:
        self._refresh_roots()
        assets = self._service.query(self._section, self._search.text(), limit=600)
        self._assets = {asset.path: asset for asset in assets}
        self._grid.clear()
        self._thumb_generation += 1
        self._tasks.cancel_prefix("photo-thumb:")
        self._tasks.cancel_prefix("video-thumb:")
        generation = self._thumb_generation
        label = {
            "all": "所有项目", "photos": "照片", "videos": "视频", "favorites": "收藏",
            "edited": "已编辑", "live": "Live Photo", "locations": "地点照片",
        }[self._section]
        self._title.setText(label)
        self._summary.setText(f"{len(assets)} 个项目 · 按最近日期排列" if assets else "没有匹配项目")
        videos: list[PhotoAsset] = []
        photos: list[PhotoAsset] = []
        for asset in assets:
            item = QListWidgetItem(self._icon_for(asset), self._item_text(asset))
            item.setData(Qt.UserRole, asset.path)
            item.setTextAlignment(Qt.AlignHCenter)
            item.setToolTip(asset.path)
            self._grid.addItem(item)
            if asset.kind == "video":
                videos.append(asset)
            else:
                photos.append(asset)
        self._set_inspector(None)
        if photos:
            self._start_photo_thumbnails(generation, photos[:300])
        if videos and self._vm.bridge:
            self._start_video_thumbnails(generation, videos[:100])

    def _refresh_roots(self) -> None:
        self._roots.clear()
        for root, title in self._service.albums():
            item = QListWidgetItem(title or Path(root).name or root)
            item.setData(Qt.UserRole, root)
            item.setToolTip(root)
            self._roots.addItem(item)

    @staticmethod
    def _item_text(asset: PhotoAsset) -> str:
        flags = []
        if asset.favorite:
            flags.append("♥")
        if asset.live_photo:
            flags.append("Live")
        if asset.edited:
            flags.append("已编辑")
        kind = "视频" if asset.kind == "video" else "照片"
        tail = " · ".join([asset.date_label, kind, *flags])
        return f"{asset.name}\n{tail}"

    def _icon_for(self, asset: PhotoAsset) -> QIcon:
        return QIcon(self._video_placeholder(asset.name) if asset.kind == "video" else self._photo_placeholder())

    @staticmethod
    def _photo_placeholder() -> QPixmap:
        pixmap = QPixmap(170, 122)
        pixmap.fill(QColor("#E5E5EA"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#8E8E93"))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(52, 35, 66, 48)
        painter.drawEllipse(62, 43, 12, 12)
        painter.drawLine(55, 79, 77, 61)
        painter.drawLine(77, 61, 96, 79)
        painter.end()
        return pixmap

    @staticmethod
    def _cover_pixmap(source: QPixmap) -> QPixmap:
        target = QSize(170, 122)
        scaled = source.scaled(target, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - target.width()) // 2)
        y = max(0, (scaled.height() - target.height()) // 2)
        return scaled.copy(x, y, target.width(), target.height())

    @staticmethod
    def _video_placeholder(name: str) -> QPixmap:
        pixmap = QPixmap(170, 122)
        pixmap.fill(QColor("#30343B"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#0A84FF"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(65, 41, 42, 42)
        painter.setBrush(QColor("white"))
        painter.drawPolygon(QPolygon([QPoint(84, 54), QPoint(84, 70), QPoint(98, 62)]))
        painter.end()
        return pixmap


    def _start_photo_thumbnails(self, generation: int, assets: list[PhotoAsset]) -> None:
        for index, asset in enumerate(assets):
            key = f"photo-thumb:{generation}:{index}"
            self._tasks.submit(
                key,
                lambda token, item=asset, gen=generation: self._decode_photo_thumbnail(gen, item, token),
            )

    @staticmethod
    def _decode_photo_thumbnail(generation: int, asset: PhotoAsset, token) -> tuple[int, str, QImage]:
        if token.cancelled:
            return generation, asset.path, QImage()
        reader = QImageReader(asset.path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > 360:
            reader.setScaledSize(size.scaled(360, 360, Qt.KeepAspectRatio))
        return generation, asset.path, reader.read()

    def _on_photo_thumb_ready(self, generation: int, path: str, image: object) -> None:
        if generation != self._thumb_generation or not isinstance(image, QImage) or image.isNull():
            return
        icon = QIcon(self._cover_pixmap(QPixmap.fromImage(image)))
        for row in range(self._grid.count()):
            item = self._grid.item(row)
            if item and item.data(Qt.UserRole) == path:
                item.setIcon(icon)
                break

    def _start_video_thumbnails(self, generation: int, assets: list[PhotoAsset]) -> None:
        if self._service.bridge is None:
            return
        for index, asset in enumerate(assets):
            key = f"video-thumb:{generation}:{index}"
            self._tasks.submit(
                key,
                lambda token, item=asset, gen=generation: (
                    gen, item.path, self._service.video_thumbnail(item.path, max_width=240)
                ),
            )

    def _on_video_thumb_ready(self, generation: int, path: str, thumb_path: str) -> None:
        if generation != self._thumb_generation or not os.path.isfile(thumb_path):
            return
        preview = load_preview(thumb_path, max_side=360)
        if not preview.ok:
            return
        for row in range(self._grid.count()):
            item = self._grid.item(row)
            if item and item.data(Qt.UserRole) == path:
                item.setIcon(QIcon(self._cover_pixmap(preview.pixmap)))
                break

    @Slot()
    def _on_selection_changed(self) -> None:
        self._set_inspector(self._selected_asset())

    def _selected_asset(self) -> PhotoAsset | None:
        item = self._grid.currentItem()
        return self._assets.get(str(item.data(Qt.UserRole))) if item else None

    def _set_inspector(self, asset: PhotoAsset | None) -> None:
        enabled = asset is not None
        self._favorite.setEnabled(enabled)
        self._open.setEnabled(enabled)
        self._enhance.setEnabled(enabled)
        self._watermark.setEnabled(enabled)
        self._edit.setEnabled(bool(asset and asset.kind == "photo"))
        self._map.setEnabled(bool(asset and asset.latitude is not None and asset.longitude is not None))
        if asset is None:
            self._preview.setPixmap(QPixmap())
            self._preview.setText("未选择项目")
            self._name.setText("选择一张照片或视频")
            self._meta.setText("")
            self._favorite.setText("♡ 收藏")
            return
        self._name.setText(asset.name)
        flags = []
        if asset.live_photo:
            flags.append("Live Photo")
        if asset.edited:
            flags.append("已应用非破坏编辑")
        if asset.latitude is not None:
            flags.append(f"位置 {asset.latitude:.5f}, {asset.longitude:.5f}")
        if asset.camera:
            flags.append(asset.camera)
        self._meta.setText(
            f"{asset.date_label}\n{'视频' if asset.kind == 'video' else '照片'} · "
            f"{asset.size_bytes / (1024 * 1024):.1f} MB"
            + ("\n" + "\n".join(flags) if flags else "")
        )
        self._favorite.setText("♥ 已收藏" if asset.favorite else "♡ 收藏")
        self._open.setText("播放视频" if asset.kind == "video" else "打开预览")
        self._enhance.setText("送去视频增强" if asset.kind == "video" else "送去画质增强")
        self._watermark.setText("送去视频去水印" if asset.kind == "video" else "送去去水印")
        if asset.kind == "photo":
            preview = load_preview(asset.path, max_side=480)
            if preview.ok:
                self._preview.setText("")
                self._preview.setPixmap(preview.pixmap.scaled(210, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        self._preview.setPixmap(self._video_placeholder(asset.name).scaled(210, 150, Qt.KeepAspectRatio))
        self._preview.setText("")

    @Slot()
    def _toggle_favorite(self) -> None:
        asset = self._selected_asset()
        if asset is None:
            return
        self._service.set_favorite(asset.path, not asset.favorite)
        self.refresh()

    @Slot()
    def _open_selected(self) -> None:
        asset = self._selected_asset()
        if asset is None:
            return
        if asset.kind == "video":
            self._open_video_preview(asset.path)
        else:
            self._show_image_preview(asset.path, asset.name)

    def _open_edit(self) -> None:
        asset = self._selected_asset()
        if asset is None or asset.kind != "photo":
            return
        dialog = PhotoEditDialog(asset.path, self)
        dialog.exec()
        if dialog.saved:
            self._service.refresh_edit(asset.path)
            self.refresh()

    def _open_map(self) -> None:
        asset = self._selected_asset()
        if asset is None or asset.latitude is None or asset.longitude is None:
            return
        # 仅在用户明确点击时将其照片坐标交给浏览器；不会后台上传位置。
        url = QUrl(f"https://www.openstreetmap.org/?mlat={asset.latitude:.7f}&mlon={asset.longitude:.7f}#map=15/{asset.latitude:.7f}/{asset.longitude:.7f}")
        QDesktopServices.openUrl(url)

    def _send_selected(self, target: str) -> None:
        asset = self._selected_asset()
        if asset is None:
            return
        if asset.kind == "video":
            self._open_video_editor(asset.path, target)
        else:
            self._open_image_editor(asset.path, target)

    def _show_image_preview(self, path: str, name: str) -> None:
        preview = load_preview(path, max_side=3200)
        if not preview.ok:
            QMessageBox.warning(self, "照片", "无法加载该图片")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(name)
        dialog.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        dialog.setSizeGripEnabled(True)
        dialog.setMinimumSize(640, 480)
        dialog.resize(900, 680)
        lay = QVBoxLayout(dialog)
        image = ZoomableImageView(preview.pixmap)
        image.setMinimumSize(480, 320)
        lay.addWidget(image, 1)
        base_info = f"{preview.native_width} × {preview.native_height} · {preview.backend}"
        info = QLabel(f"{base_info} · 100% · 滚轮缩放 / 左键拖动 / 双击适合窗口")
        info.setAlignment(Qt.AlignCenter)
        image.zoomChanged.connect(
            lambda percent: info.setText(
                f"{base_info} · {percent}% · 滚轮缩放 / 左键拖动 / 双击适合窗口"
            )
        )
        lay.addWidget(info)
        dialog.exec()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not hasattr(self, "_grid"):
            return
        available = max(320, self._grid.viewport().width() - 8)
        columns = max(2, available // 190)
        cell_width = max(150, min(230, available // columns))
        icon_width = max(132, cell_width - 18)
        icon_height = max(96, int(icon_width * 0.72))
        self._grid.setIconSize(QSize(icon_width, icon_height))
        self._grid.setGridSize(QSize(cell_width, icon_height + 58))

    def closeEvent(self, event) -> None:
        self._tasks.cancel_all()
        super().closeEvent(event)

    @staticmethod
    def _stylesheet() -> str:
        return """
        #PhotoLibraryPage { background: #F5F5F7; color: #1D1D1F; }
        #PhotoToolbar { background: rgba(255,255,255,235); border-bottom: 1px solid #D2D2D7; }
        #PhotoBrand { font-size: 20px; font-weight: 700; color: #1D1D1F; }
        #PhotoTitle { font-size: 14px; color: #6E6E73; padding-left: 8px; }
        #PhotoSearch { background: #E8E8ED; border: none; border-radius: 9px; color: #1D1D1F; padding: 7px 12px; }
        #PhotoSidebar { background: #ECECEF; border: none; }
        #PhotoContent, #PhotoInspector { background: #FFFFFF; border: none; }
        #PhotoInspector { border-left: 1px solid #E5E5EA; }
        #PhotoSectionLabel { color: #6E6E73; font-size: 11px; font-weight: 700; padding: 4px 7px; }
        QPushButton#PhotoNav { background: transparent; border: none; color: #3A3A3C; text-align: left; border-radius: 7px; padding: 7px 10px; }
        QPushButton#PhotoNav:hover { background: #DCDCE1; }
        QPushButton#PhotoNav:checked { background: #D4E8FF; color: #0066CC; font-weight: 700; }
        QPushButton#PhotoPrimary { background: #0A84FF; color: white; border: none; border-radius: 8px; padding: 7px 13px; font-weight: 600; }
        QPushButton#PhotoPrimary:hover { background: #0077ED; }
        QPushButton#PhotoSubtle { background: #F2F2F7; color: #1D1D1F; border: 1px solid #D2D2D7; border-radius: 8px; padding: 7px 10px; }
        QPushButton#PhotoSubtle:hover { background: #E5E5EA; }
        QToolButton { background: #F2F2F7; color: #1D1D1F; border: 1px solid #D2D2D7; border-radius: 8px; padding: 5px 9px; font-size: 18px; }
        #PhotoRoots { background: transparent; border: none; color: #3A3A3C; padding: 0; }
        #PhotoRoots::item { padding: 5px 7px; border-radius: 6px; }
        #PhotoRoots::item:selected { background: #D4E8FF; color: #0066CC; }
        #PhotoSummary, #PhotoAssetMeta { color: #6E6E73; font-size: 12px; }
        #PhotoGrid { background: transparent; border: none; outline: none; padding: 2px; }
        #PhotoGrid::item { color: #3A3A3C; border: 2px solid transparent; border-radius: 9px; padding: 3px; }
        #PhotoGrid::item:hover { background: #F2F2F7; }
        #PhotoGrid::item:selected { border-color: #0A84FF; background: #EAF4FF; color: #1D1D1F; }
        #PhotoInspectorPreview { background: #F2F2F7; border-radius: 10px; color: #8E8E93; }
        #PhotoAssetName { color: #1D1D1F; font-size: 14px; font-weight: 700; }
        #PhotoPrivacy { color: #8E8E93; font-size: 11px; padding: 6px; }
        QSplitter::handle { background: #E5E5EA; width: 1px; }
        """
