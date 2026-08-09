"""个人中心：卡密、GPU、输出目录、诊断与关于。

适配最大化 / 全屏 / 窗口缩放：内容铺满可用区域，窄屏自动改单列。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.elided_label import ElidedPathLabel
from ui.theme import (
    ACCENT, ACCENT_HOVER, ACCENT_ON, BG, BORDER, BORDER_STRONG, ELEVATED,
    FONT_UI, OK, SIGNAL, SIGNAL_SOFT, SURFACE, SURFACE_2, TEXT, TEXT_DIM,
    TEXT_MUTED,
)
from viewmodels.main_vm import MainViewModel

# 低于此宽度（逻辑像素）改为单列，便于缩小窗口 / 高 DPI 缩放
_NARROW_BREAKPOINT = 860


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
        stop:0 {SURFACE}, stop:0.5 {SURFACE_2}, stop:1 #1A2420);
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
    background: {SURFACE_2};
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
    border: 1px solid #3A6A64;
    border-radius: 10px;
}}
QLabel#ProfileStatusCap {{
    color: {TEXT_MUTED};
    font-size: 12px;
    background: transparent;
    border: none;
}}
QLabel#ProfileStatusValue {{
    color: #B8EDE4;
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
    background: #2C3444;
    border-color: #4A5870;
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
    card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
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
        self._narrow = False
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
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self._scroll)

        self._body = QWidget()
        self._body.setObjectName("ProfileBody")
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._scroll.setWidget(self._body)

        self._root = QVBoxLayout(self._body)
        self._root.setContentsMargins(12, 10, 12, 12)
        self._root.setSpacing(10)

        hero = self._build_hero(vm)
        hero.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._root.addWidget(hero, 0)

        # 主网格：宽屏双列，窄屏单列（resizeEvent 切换）
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

        self._root.addLayout(self._grid, 1)
        self._root.addWidget(self._about_card, 0)

        self._apply_layout(narrow=False)

        vm.authTypeChanged.connect(self._on_auth_changed)
        vm.gpuNameChanged.connect(self._on_gpu_name)
        self._sync_output_label()
        self._sync_gpu_check()
        self._refresh_auth_badge(vm.auth_type)

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                self._grid.removeWidget(w)
                w.setParent(self._body)

    def _apply_layout(self, *, narrow: bool) -> None:
        self._clear_grid()
        self._narrow = narrow
        if narrow:
            # 单列：自上而下铺满
            self._grid.addWidget(self._auth_card, 0, 0)
            self._grid.addWidget(self._gpu_card, 1, 0)
            self._grid.addWidget(self._out_card, 2, 0)
            self._grid.addWidget(self._setup_card, 3, 0)
            self._grid.addWidget(self._diag_card, 4, 0)
            for r in range(5):
                self._grid.setRowStretch(r, 1 if r == 0 else 1)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)
        else:
            # 双列：左授权跨两行；右 GPU/输出；底开箱|诊断
            self._grid.addWidget(self._auth_card, 0, 0, 2, 1)
            self._grid.addWidget(self._gpu_card, 0, 1)
            self._grid.addWidget(self._out_card, 1, 1)
            self._grid.addWidget(self._setup_card, 2, 0)
            self._grid.addWidget(self._diag_card, 2, 1)
            self._grid.setRowStretch(0, 2)
            self._grid.setRowStretch(1, 2)
            self._grid.setRowStretch(2, 1)
            self._grid.setColumnStretch(0, 3)
            self._grid.setColumnStretch(1, 2)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        narrow = self.width() < _NARROW_BREAKPOINT
        if narrow != self._narrow:
            self._apply_layout(narrow=narrow)

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
        sub = QLabel("管理授权、硬件加速与本地输出；诊断日志一键打包。支持最大化 / 缩放窗口。")
        sub.setObjectName("ProfileSubtitle")
        sub.setWordWrap(True)
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
            "本地校验卡密格式；联网支付尚未接入。",
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
        self._btn_clear.setToolTip("清除本地卡密，回到试用版能力")
        self._btn_clear.clicked.connect(self._on_clear_license)
        actions.addWidget(self._btn_redeem, 2)
        actions.addWidget(self._btn_clear, 1)
        lay.addLayout(actions)

        tip = QLabel(
            "试用：快速超分 2×、快速去水印。\n"
            "正式版：AI 4×、批量队列、LaMa 精修。"
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
            "打包 player / cli / ORT EP 日志；清理超分临时帧残留。",
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
            QMessageBox.information(self, "授权", msg)
        else:
            QMessageBox.warning(self, "授权", msg)

    @Slot()
    def _on_clear_license(self):
        ok, msg = self._vm.clear_license()
        QMessageBox.information(self, "授权", msg if ok else msg)

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
