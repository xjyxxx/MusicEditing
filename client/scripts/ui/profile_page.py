"""个人中心：卡密、GPU、输出目录、诊断与关于。

铺满可用区域；固定双列卡片网格（不随宽度拆装），减少进入时布局跳动。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.elided_label import ElidedPathLabel
from ui.theme import (
    ACCENT, ACCENT_HOVER, ACCENT_ON, BG, BORDER, BORDER_STRONG, ELEVATED,
    FONT_UI, OK, SIGNAL, SIGNAL_SOFT, SIGNAL_BORDER, SURFACE, SURFACE_2, TEXT, TEXT_DIM,
    TEXT_MUTED,
)
from viewmodels.main_vm import MainViewModel


def _profile_stylesheet() -> str:
    return f"""
QWidget#ProfilePage {{
    background: {BG};
}}
QScrollArea#ProfileScroll {{
    background: {BG};
    border: none;
}}
QWidget#ProfileBody {{
    background: {BG};
}}
QFrame#ProfileHero {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {SURFACE}, stop:1 {SURFACE_2});
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#ProfileTitle {{
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 20px;
    font-weight: 600;
    letter-spacing: 0.3px;
}}
QLabel#ProfileSubtitle {{
    color: {TEXT_MUTED};
    font-size: 13px;
}}
QLabel#ProfilePill {{
    background: {ELEVATED};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-radius: 999px;
    padding: 5px 12px;
    font-size: 12px;
}}
QFrame#ProfileCard {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#ProfileCardTitle {{
    color: {SIGNAL};
    font-family: {FONT_UI};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#ProfileCardHint {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QFrame#ProfileStatusBar {{
    background: {SIGNAL_SOFT};
    border: 1px solid {SIGNAL_BORDER};
    border-radius: 10px;
}}
QLabel#ProfileStatusCap {{
    color: {TEXT_MUTED};
    font-size: 12px;
    background: transparent;
    border: none;
}}
QLabel#ProfileStatusValue {{
    color: {SIGNAL};
    font-size: 15px;
    font-weight: 600;
    background: transparent;
    border: none;
}}
QLabel#ProfileFieldLabel {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}
QLineEdit#ProfileKeyEdit {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 10px 12px;
    font-size: 14px;
}}
QLineEdit#ProfileKeyEdit:focus {{
    border: 1px solid {SIGNAL};
}}
QPushButton#ProfilePrimary {{
    background: {ACCENT};
    color: {ACCENT_ON};
    border: 1px solid {ACCENT};
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#ProfilePrimary:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton#ProfileGhost {{
    background: {ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 13px;
}}
QPushButton#ProfileGhost:hover {{
    background: {SURFACE};
    border-color: {BORDER_STRONG};
}}
QPushButton#ProfileLink {{
    background: transparent;
    color: {TEXT_MUTED};
    border: none;
    text-align: left;
    padding: 2px 0;
    font-size: 12px;
}}
QPushButton#ProfileLink:hover {{
    color: {TEXT};
}}
QPushButton#ProfileLink:checked {{
    color: {SIGNAL};
}}
QFrame#ProfilePathBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#ProfileAboutName {{
    color: {TEXT};
    font-family: {FONT_UI};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#ProfileAboutMeta {{
    color: {TEXT_DIM};
    font-size: 12px;
}}
QCheckBox#ProfileGpuCheck {{
    color: {TEXT};
    spacing: 10px;
    font-size: 13px;
}}
QLabel#ProfileGpuOk {{
    color: {OK};
    font-size: 13px;
}}
"""


def _make_card(title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("ProfileCard")
    # Preferred：避免进入页面时随网格被纵向撑开造成「整页在动」
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(10)
    head = QVBoxLayout()
    head.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("ProfileCardTitle")
    head.addWidget(t)
    if hint:
        h = QLabel(hint)
        h.setObjectName("ProfileCardHint")
        h.setWordWrap(True)
        head.addWidget(h)
    lay.addLayout(head)
    return card, lay


def _btn(text: str, *, primary: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("ProfilePrimary" if primary else "ProfileGhost")
    # 随字体缩放：约 2.2 行高，避免固定 42px 在系统放大时显得怪
    b.setMinimumHeight(max(34, b.fontMetrics().height() + 18))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return b


class ProfilePage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        self._first_show = True
        self.setObjectName("ProfilePage")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_profile_stylesheet())
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("ProfileScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # AsNeeded：不占常驻槽；右边距预留与滚动条同宽，避免条出现/消失时内容左右晃
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self._scroll)

        self._body = QWidget()
        self._body.setObjectName("ProfileBody")
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._scroll.setWidget(self._body)

        _sb = max(12, self._scroll.verticalScrollBar().sizeHint().width())
        self._root = QVBoxLayout(self._body)
        self._root.setContentsMargins(12, 10, 12 + _sb, 12)
        self._root.setSpacing(10)

        hero = self._build_hero(vm)
        hero.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._root.addWidget(hero, 0)

        # 固定双列网格（不再随宽度拆装控件，避免进入页时「整页挪一下」）
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(10)
        self._auth_card = self._build_auth_card(vm)
        self._gpu_card = self._build_gpu_card(vm)
        self._out_card = self._build_output_card()
        self._setup_card = self._build_setup_card()
        self._diag_card = self._build_diag_card()
        self._about_card = self._build_about_card(vm)
        self._about_card.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum,
        )

        # 左：授权跨两行；右：GPU / 输出；底：开箱 | 诊断。布局一次定死。
        self._grid.addWidget(self._auth_card, 0, 0, 2, 1)
        self._grid.addWidget(self._gpu_card, 0, 1)
        self._grid.addWidget(self._out_card, 1, 1)
        self._grid.addWidget(self._setup_card, 2, 0)
        self._grid.addWidget(self._diag_card, 2, 1)
        self._grid.setRowStretch(0, 0)
        self._grid.setRowStretch(1, 0)
        self._grid.setRowStretch(2, 0)
        self._grid.setColumnStretch(0, 3)
        self._grid.setColumnStretch(1, 2)

        # 滚动区内容不要 addStretch：widgetResizable 下 stretch 会先吃满视口再被内容顶回去 → 肉眼可见跳动
        self._root.addLayout(self._grid, 0)
        self._root.addWidget(self._about_card, 0)

        vm.authTypeChanged.connect(self._on_auth_changed)
        vm.gpuNameChanged.connect(self._on_gpu_name)
        self._sync_output_label()
        self._sync_gpu_check()
        self._refresh_auth_badge(vm.auth_type)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        # 首帧布局未稳态前不刷新，避免「整页挪一下」
        if self._first_show:
            self._first_show = False
            self.setUpdatesEnabled(False)
            QTimer.singleShot(0, self._finish_first_show)

    def _finish_first_show(self) -> None:
        try:
            self.prepare_for_size(self.size())
        except Exception:
            pass
        self.setUpdatesEnabled(True)

    def prepare_for_size(self, size) -> None:
        """插入堆叠前按最终尺寸预布局，减少首帧跳动。"""
        if size is None or size.width() < 2 or size.height() < 2:
            return
        self.resize(size)
        self._body.adjustSize()
        self.updateGeometry()

    def _build_hero(self, vm: MainViewModel) -> QFrame:
        hero = QFrame()
        hero.setObjectName("ProfileHero")
        lay = QHBoxLayout(hero)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(4)
        title = QLabel("个人中心")
        title.setObjectName("ProfileTitle")
        sub = QLabel("管理授权、硬件加速与本地输出；诊断日志一键打包。")
        sub.setObjectName("ProfileSubtitle")
        sub.setWordWrap(True)
        # 固定两行槽位，避免与右侧版本 pill / 下方卡片叠字
        _sub_h = sub.fontMetrics().lineSpacing() * 2 + 4
        sub.setFixedHeight(_sub_h)
        sub.setToolTip(sub.text())
        left.addWidget(title)
        left.addWidget(sub)
        lay.addLayout(left, 1)

        pill = QLabel(f"v{vm.version}")
        pill.setObjectName("ProfilePill")
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)
        return hero

    def _build_auth_card(self, vm: MainViewModel) -> QFrame:
        card, lay = _make_card(
            "授权 / 卡密",
            "本地卡密或联网激活；可配置购买页与 license 服务器。",
        )

        status = QFrame()
        status.setObjectName("ProfileStatusBar")
        status_lay = QHBoxLayout(status)
        status_lay.setContentsMargins(12, 10, 12, 10)
        status_lay.setSpacing(10)
        cap = QLabel("当前授权")
        cap.setObjectName("ProfileStatusCap")
        self._auth_status = QLabel(vm.auth_type or "试用版")
        self._auth_status.setObjectName("ProfileStatusValue")
        status_lay.addWidget(cap)
        status_lay.addStretch(1)
        status_lay.addWidget(self._auth_status)
        lay.addWidget(status)

        self._quota_label = QLabel("")
        self._quota_label.setObjectName("ProfileCardHint")
        self._quota_label.setWordWrap(True)
        _qh = self._quota_label.fontMetrics().lineSpacing() * 2 + 4
        self._quota_label.setFixedHeight(_qh)
        lay.addWidget(self._quota_label)
        self._refresh_quota_label()

        field = QLabel("卡密")
        field.setObjectName("ProfileFieldLabel")
        lay.addWidget(field)

        self._key_edit = QLineEdit()
        self._key_edit.setObjectName("ProfileKeyEdit")
        self._key_edit.setPlaceholderText("粘贴卡密（≥16 位，需含字母与数字）")
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
        self._key_edit.setClearButtonEnabled(True)
        self._key_edit.setMinimumHeight(max(34, self._key_edit.fontMetrics().height() + 16))
        self._key_edit.returnPressed.connect(self._on_redeem)
        lay.addWidget(self._key_edit)

        self._btn_show_key = QPushButton("隐藏卡密")
        self._btn_show_key.setObjectName("ProfileLink")
        self._btn_show_key.setCheckable(True)
        self._btn_show_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_show_key.toggled.connect(self._on_toggle_key_visible)
        lay.addWidget(self._btn_show_key, 0, Qt.AlignmentFlag.AlignLeft)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self._btn_redeem = _btn("兑换正式版", primary=True)
        self._btn_redeem.clicked.connect(self._on_redeem)
        self._btn_clear = _btn("恢复试用", primary=False)
        self._btn_clear.setToolTip("清除本地卡密，回到试用版能力（次数配额保留）")
        self._btn_clear.clicked.connect(self._on_clear_license)
        actions.addWidget(self._btn_redeem, 2)
        actions.addWidget(self._btn_clear, 1)
        lay.addLayout(actions)

        self._btn_buy = _btn("打开购买页…", primary=False)
        self._btn_buy.setToolTip(
            "需配置 app.conf 的 license_purchase_url，或环境变量 MUSIC_LICENSE_PURCHASE_URL"
        )
        self._btn_buy.clicked.connect(self._on_open_purchase)
        lay.addWidget(self._btn_buy)

        tip = QLabel(
            "试用：OpenCV 超分 2×、快速去水印、单文件切片；"
            "高光导出≤20 次、竖屏≤10 次、最长边≤720p。\n"
            "正式版：AI 4×、批量队列、LaMa 精修、导出不限。\n"
            "联网：app.conf 写 license_server_url（POST /v1/activate）；"
            "无服务器时本地格式校验。"
        )
        tip.setObjectName("ProfileCardHint")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        lay.addStretch(1)
        return card

    def _build_gpu_card(self, vm: MainViewModel) -> QFrame:
        card, lay = _make_card("硬件加速", "影响硬解与 CUDA 相关推理偏好。")
        self._gpu_check = QCheckBox("启用 GPU（D3D11VA / CUDA EP）")
        self._gpu_check.setObjectName("ProfileGpuCheck")
        self._gpu_check.setChecked(bool(getattr(vm, "gpu_enabled", True)))
        self._gpu_check.toggled.connect(self._on_gpu_toggled)
        lay.addWidget(self._gpu_check)
        self._gpu_info = QLabel(f"检测：{vm.gpu_name}")
        self._gpu_info.setObjectName("ProfileGpuOk")
        self._gpu_info.setWordWrap(True)
        lay.addWidget(self._gpu_info)
        lay.addStretch(1)
        return card

    def _build_output_card(self) -> QFrame:
        card, lay = _make_card("默认输出目录", "各功能未另选目录时使用此处。")
        path_box = QFrame()
        path_box.setObjectName("ProfilePathBox")
        path_lay = QHBoxLayout(path_box)
        path_lay.setContentsMargins(12, 10, 12, 10)
        self._out_label = ElidedPathLabel("未设置（各功能将自行选择）")
        self._out_label.setStyleSheet(
            f"color: {TEXT_MUTED}; background: transparent; border: none;"
        )
        path_lay.addWidget(self._out_label, 1)
        lay.addWidget(path_box)
        btn_out = _btn("选择目录…", primary=False)
        btn_out.clicked.connect(self._on_pick_output)
        lay.addWidget(btn_out)
        lay.addStretch(1)
        return card

    def _build_setup_card(self) -> QFrame:
        card, lay = _make_card(
            "开箱与依赖",
            "模型、yt-dlp、Cookie、引擎缺失时，向导会给出优先处理项。",
        )
        btn = _btn("打开开箱向导…", primary=False)
        btn.clicked.connect(self._on_open_wizard)
        lay.addWidget(btn)
        lay.addStretch(1)
        return card

    def _build_diag_card(self) -> QFrame:
        card, lay = _make_card(
            "诊断与清理",
            "打包日志；清理临时帧；检查新版本（需配置 update_manifest_url）。",
        )
        row = QHBoxLayout()
        row.setSpacing(10)
        btn_pack = _btn("打包诊断日志", primary=True)
        btn_pack.clicked.connect(self._on_pack_diag)
        btn_clean = _btn("清理临时帧", primary=False)
        btn_clean.clicked.connect(self._on_cleanup_temp)
        row.addWidget(btn_pack, 1)
        row.addWidget(btn_clean, 1)
        lay.addLayout(row)
        btn_upd = _btn("检查更新…", primary=False)
        btn_upd.clicked.connect(self._on_check_update)
        lay.addWidget(btn_upd)
        lay.addStretch(1)
        return card

    def _build_about_card(self, vm: MainViewModel) -> QFrame:
        card = QFrame()
        card.setObjectName("ProfileCard")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(12)
        left = QVBoxLayout()
        left.setSpacing(2)
        name = QLabel(f"MusicEditing  v{vm.version}")
        name.setObjectName("ProfileAboutName")
        meta = QLabel("本地音视频工作室 · FFmpeg + OpenCV + ONNX")
        meta.setObjectName("ProfileAboutMeta")
        left.addWidget(name)
        left.addWidget(meta)
        lay.addLayout(left, 1)
        return card

    def _refresh_auth_badge(self, auth: str) -> None:
        self._auth_status.setText((auth or "试用版").strip() or "试用版")
        self._refresh_quota_label()

    def _refresh_quota_label(self) -> None:
        if not hasattr(self, "_quota_label"):
            return
        try:
            q = self._vm.trial_quota_summary()
        except Exception:
            self._quota_label.setText("")
            return
        if q.get("licensed"):
            txt = "正式版：导出与功能不限次数。"
            self._quota_label.setText(txt)
            self._quota_label.setToolTip(txt)
            return
        txt = (
            f"试用剩余：高光导出 {q.get('highlight_left')}/{q.get('highlight_max')}，"
            f"竖屏 {q.get('vertical_left')}/{q.get('vertical_max')}；"
            f"最长边≤{q.get('max_export_height')}p。"
        )
        self._quota_label.setText(txt)
        self._quota_label.setToolTip(txt)

    def _sync_gpu_check(self) -> None:
        enabled = bool(getattr(self._vm, "gpu_enabled", True))
        self._gpu_check.blockSignals(True)
        self._gpu_check.setChecked(enabled)
        self._gpu_check.blockSignals(False)

    def _sync_output_label(self) -> None:
        path = getattr(self._vm, "output_dir", "") or ""
        self._out_label.setText(path or "未设置（各功能将自行选择）")

    @Slot(str)
    def _on_auth_changed(self, auth: str):
        self._refresh_auth_badge(auth)

    @Slot(bool)
    def _on_toggle_key_visible(self, checked: bool):
        if checked:
            self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._btn_show_key.setText("显示卡密")
        else:
            self._key_edit.setEchoMode(QLineEdit.EchoMode.Normal)
            self._btn_show_key.setText("隐藏卡密")

    @Slot(str)
    def _on_gpu_name(self, name: str):
        self._gpu_info.setText(f"检测：{name}")
        self._sync_gpu_check()

    @Slot()
    def _on_redeem(self):
        key = self._key_edit.text().strip()
        if not key:
            QMessageBox.warning(self, "授权", "请先粘贴或输入卡密。")
            return
        ok, msg = self._vm.redeem_license(key)
        if ok:
            self._key_edit.clear()
            self._refresh_quota_label()
            QMessageBox.information(self, "授权", msg)
        else:
            QMessageBox.warning(self, "授权", msg)

    @Slot()
    def _on_clear_license(self):
        ok, msg = self._vm.clear_license()
        self._refresh_quota_label()
        QMessageBox.information(self, "授权", msg if ok else msg)

    @Slot()
    def _on_open_purchase(self):
        url = ""
        try:
            url = self._vm.purchase_url()
        except Exception:
            url = ""
        if not url:
            QMessageBox.information(
                self,
                "购买页",
                "尚未配置购买地址。\n\n"
                "在 app.conf 增加：\n"
                "license_purchase_url=https://你的商店/…\n"
                "或设置环境变量 MUSIC_LICENSE_PURCHASE_URL。\n\n"
                "支付成功后把卡密粘贴到上方兑换即可。",
            )
            return
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl(url))

    @Slot(bool)
    def _on_gpu_toggled(self, checked: bool):
        self._vm.set_gpu_enabled(checked)
        self._sync_gpu_check()
        self._gpu_info.setText(f"检测：{self._vm.gpu_name}")

    @Slot()
    def _on_pick_output(self):
        start = getattr(self._vm, "output_dir", "") or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择默认输出目录", start)
        if not path:
            return
        self._vm.set_output_dir(path)
        self._sync_output_label()

    @Slot()
    def _on_check_update(self):
        info = self._vm.check_for_update()
        if info.has_update and info.remote_version:
            try:
                from core.update_check import remember_notified_version
                remember_notified_version(info.remote_version)
            except Exception:
                pass
        if not info.configured:
            from core.update_check import setup_help_text

            QMessageBox.information(
                self,
                "检查更新",
                f"{info.message}\n\n{setup_help_text()}",
            )
            return
        if info.has_update and info.url:
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl

            r = QMessageBox.question(
                self,
                "发现新版本",
                f"{info.message}\n\n{info.notes}\n\n是否打开下载页？",
            )
            if r == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(info.url))
            return
        QMessageBox.information(self, "检查更新", info.message)

    @Slot()
    def _on_open_wizard(self):
        win = self.window()
        if hasattr(win, "open_setup_wizard"):
            win.open_setup_wizard()
        else:
            from ui.setup_wizard import SetupWizardDialog
            SetupWizardDialog(self._vm, self).exec()

    @Slot()
    def _on_pack_diag(self):
        try:
            from core.diag_pack import pack_diagnostics

            extra = {
                "auth": getattr(self._vm, "auth_type", ""),
                "gpu": getattr(self._vm, "gpu_name", ""),
                "output_dir": getattr(self._vm, "output_dir", ""),
            }
            path, names = pack_diagnostics(extra=extra)
        except Exception as e:
            QMessageBox.warning(self, "诊断打包失败", str(e))
            return
        QMessageBox.information(
            self,
            "诊断包已生成",
            f"已写入：\n{path}\n\n含 {len(names)} 项（player / cli / ORT EP / 快照）。\n"
            "反馈问题时请附上此 zip。",
        )
        try:
            __import__("os").startfile(str(Path(path).parent))  # type: ignore[attr-defined]
        except Exception:
            pass

    @Slot()
    def _on_cleanup_temp(self):
        from core.resource_cleanup import cleanup_orphan_temp_dirs, format_bytes

        preview = cleanup_orphan_temp_dirs(max_age_hours=0.0, dry_run=True)
        if not preview:
            QMessageBox.information(self, "清理临时帧", "未发现可清理的临时目录。")
            return
        total = sum(s for _, s in preview)
        ans = QMessageBox.question(
            self,
            "清理临时帧",
            f"将删除 {len(preview)} 个临时目录（约 {format_bytes(total)}）：\n"
            + "\n".join(p for p, _ in preview[:8])
            + ("\n…" if len(preview) > 8 else "")
            + "\n\n继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        freed = cleanup_orphan_temp_dirs(max_age_hours=0.0, dry_run=False)
        QMessageBox.information(
            self,
            "清理完成",
            f"已清理 {len(freed)} 项，释放约 {format_bytes(sum(s for _, s in freed))}。",
        )
