"""个人中心：卡密、GPU、输出目录、关于。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ui.elided_label import ElidedPathLabel
from viewmodels.main_vm import MainViewModel


class ProfilePage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        title = QLabel("个人中心")
        title.setObjectName("HomeTitle")
        root.addWidget(title)
        sub = QLabel("卡密兑换、GPU 加速、默认输出目录与关于信息。")
        sub.setObjectName("HomeSubtitle")
        sub.setWordWrap(True)
        root.addWidget(sub)

        # ── 授权 ──
        auth_box = QGroupBox("授权 / 卡密")
        auth_lay = QVBoxLayout(auth_box)
        self._auth_status = QLabel(f"当前：{vm.auth_type}")
        self._auth_status.setObjectName("MetaBadge")
        auth_lay.addWidget(self._auth_status)
        key_row = QHBoxLayout()
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("输入卡密（≥16 字符，本地校验）")
        self._key_edit.setEchoMode(QLineEdit.Password)
        btn_redeem = QPushButton("兑换")
        btn_redeem.setObjectName("PrimaryBtn")
        btn_redeem.clicked.connect(self._on_redeem)
        btn_clear = QPushButton("恢复试用")
        btn_clear.setObjectName("GhostBtn")
        btn_clear.clicked.connect(self._on_clear_license)
        key_row.addWidget(self._key_edit, 1)
        key_row.addWidget(btn_redeem)
        key_row.addWidget(btn_clear)
        auth_lay.addLayout(key_row)
        tip = QLabel("正式联网校验与支付尚未接入；当前为本地格式校验，便于联调门禁。")
        tip.setObjectName("MutedText")
        tip.setWordWrap(True)
        auth_lay.addWidget(tip)
        root.addWidget(auth_box)

        # ── GPU ──
        gpu_box = QGroupBox("硬件加速")
        gpu_lay = QVBoxLayout(gpu_box)
        self._gpu_check = QCheckBox("启用 GPU（硬解 D3D11VA / 优先 CUDA 相关能力）")
        self._gpu_check.setChecked(bool(getattr(vm, "gpu_enabled", True)))
        self._gpu_check.toggled.connect(self._on_gpu_toggled)
        gpu_lay.addWidget(self._gpu_check)
        self._gpu_info = QLabel(f"检测：{vm.gpu_name}")
        self._gpu_info.setObjectName("InfoText")
        self._gpu_info.setWordWrap(True)
        gpu_lay.addWidget(self._gpu_info)
        root.addWidget(gpu_box)

        # ── 输出目录 ──
        out_box = QGroupBox("默认输出目录")
        out_lay = QVBoxLayout(out_box)
        out_row = QHBoxLayout()
        self._out_label = ElidedPathLabel("未设置（各功能将自行选择）")
        btn_out = QPushButton("选择…")
        btn_out.setObjectName("GhostBtn")
        btn_out.clicked.connect(self._on_pick_output)
        out_row.addWidget(self._out_label, 1)
        out_row.addWidget(btn_out)
        out_lay.addLayout(out_row)
        root.addWidget(out_box)

        # ── 关于 ──
        about = QGroupBox("关于")
        about_lay = QVBoxLayout(about)
        about_lay.addWidget(QLabel(f"MusicEditing  v{vm.version}"))
        about_lay.addWidget(QLabel("本地音视频工作室 · FFmpeg + OpenCV + ONNX"))
        root.addWidget(about)

        root.addStretch()

        vm.authTypeChanged.connect(self._on_auth_changed)
        vm.gpuNameChanged.connect(self._on_gpu_name)
        self._sync_output_label()
        self._sync_gpu_check()

    def _sync_gpu_check(self) -> None:
        enabled = bool(getattr(self._vm, "gpu_enabled", True))
        self._gpu_check.blockSignals(True)
        self._gpu_check.setChecked(enabled)
        self._gpu_check.blockSignals(False)

    def _sync_output_label(self) -> None:
        path = getattr(self._vm, "output_dir", "") or ""
        if path:
            self._out_label.setText(path)
        else:
            self._out_label.setText("未设置（各功能将自行选择）")

    @Slot(str)
    def _on_auth_changed(self, auth: str):
        self._auth_status.setText(f"当前：{auth}")

    @Slot(str)
    def _on_gpu_name(self, name: str):
        self._gpu_info.setText(f"检测：{name}")
        self._sync_gpu_check()

    @Slot()
    def _on_redeem(self):
        key = self._key_edit.text().strip()
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
