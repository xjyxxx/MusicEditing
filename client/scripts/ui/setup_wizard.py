"""首次启动依赖向导。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from core.app_logic import update_app_config_value
from core.setup_status import DepItem, SetupStatus, collect_setup_status


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


class SetupWizardDialog(QDialog):
    def __init__(self, vm, parent=None):
        super().__init__(parent)
        self._vm = vm
        self.setWindowTitle("开箱设置 · MusicEditing")
        self.setMinimumSize(560, 520)
        self.resize(640, 560)

        root = QVBoxLayout(self)
        title = QLabel("欢迎使用 MusicEditing")
        title.setObjectName("HomeTitle")
        root.addWidget(title)
        tip = QLabel(
            "本地离线主链路不强制联网。下列依赖按需准备："
            "引擎编译、超分/去水印模型、链接下载、Cookie、GPU。"
            "照片完整能力另见 requirements-iphoto.txt；地点离线字体见 maps/ASSETS.md。"
            "「点了没反应」常见原因：media_cli 未编译、yt-dlp 缺失、Cookie 未配。"
            "可稍后在「个人中心」再次打开本向导。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("MutedText")
        root.addWidget(tip)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setObjectName("WarnText")
        root.addWidget(self._summary)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setSpacing(8)
        scroll.setWidget(self._body)
        root.addWidget(scroll, 1)

        self._rows: dict[str, QLabel] = {}
        self._refresh()

        trial_box = QVBoxLayout()
        trial_tip = QLabel(
            "建议：依赖就绪后点「试跑 15 秒成片」，用 tests 样例走通切片→竖屏。"
            "便携版闪退请先装 VC++ 2015–2022 x64 运行库。"
        )
        trial_tip.setWordWrap(True)
        trial_tip.setObjectName("MutedText")
        trial_box.addWidget(trial_tip)
        self._trial_progress = QProgressBar()
        self._trial_progress.setRange(0, 100)
        self._trial_progress.setValue(0)
        self._trial_progress.setVisible(False)
        trial_box.addWidget(self._trial_progress)
        self._trial_status = QLabel("")
        self._trial_status.setObjectName("MutedText")
        self._trial_status.setWordWrap(True)
        trial_box.addWidget(self._trial_status)
        root.addLayout(trial_box)

        btns = QHBoxLayout()
        btn_refresh = QPushButton("重新检测")
        btn_refresh.clicked.connect(self._refresh)
        btns.addWidget(btn_refresh)
        self._btn_trial = QPushButton("试跑 15 秒成片")
        self._btn_trial.setObjectName("PrimaryBtn")
        self._btn_trial.clicked.connect(self._on_trial)
        btns.addWidget(self._btn_trial)
        btns.addStretch()
        box = QDialogButtonBox(QDialogButtonBox.Ok)
        box.button(QDialogButtonBox.Ok).setText("完成并进入")
        box.accepted.connect(self._on_done)
        btns.addWidget(box)
        root.addLayout(btns)

        self._trial_thread: QThread | None = None

    def _clear_body(self):
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._rows.clear()

    @Slot()
    def _refresh(self):
        self._clear_body()
        app = getattr(self._vm, "_app", None) or getattr(self._vm, "app", None)
        st = collect_setup_status(app)
        self._summary.setText(st.next_actions_summary())
        if st.missing_any:
            self._summary.setObjectName("WarnText")
        else:
            self._summary.setObjectName("InfoText")
        self._summary.style().unpolish(self._summary)
        self._summary.style().polish(self._summary)
        for item in st.items:
            self._body_lay.addWidget(self._make_row(item))
        self._body_lay.addStretch()

    def _make_row(self, item: DepItem) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(8, 6, 8, 6)
        mark = "✓" if item.ok else "!"
        crit = "（必装）" if item.critical and not item.ok else ""
        title = QLabel(f"{mark}  {item.title}{crit}")
        title.setObjectName("InfoText" if item.ok else "WarnText")
        title.setMinimumWidth(180)
        detail = QLabel(item.detail)
        detail.setObjectName("MutedText")
        detail.setWordWrap(True)
        self._rows[item.key] = detail
        lay.addWidget(title)
        lay.addWidget(detail, 1)
        if (not item.ok and item.action) or item.action in (
            "special:gpu", "special:cookie", "special:build", "special:llm",
        ):
            btn = QPushButton(self._action_label(item))
            btn.setObjectName("GhostBtn")
            btn.clicked.connect(lambda _=False, it=item: self._on_action(it))
            lay.addWidget(btn)
        return row

    def _action_label(self, item: DepItem) -> str:
        if item.action == "special:cookie":
            return "去配置 Cookie"
        if item.action == "special:gpu":
            return "个人中心"
        if item.action == "special:build":
            return "如何编译"
        if item.action == "special:llm":
            return "LLM 说明"
        if item.action.endswith(".bat"):
            return "一键下载"
        return "处理"

    @Slot()
    def _on_action(self, item: DepItem):
        if item.action == "special:cookie":
            QMessageBox.information(
                self, "Cookie",
                "请到「链接下载」页点击「Cookie…」，选择扩展导出的 Netscape cookies.txt。\n"
                "抖音需先登录 douyin.com 再导出。\n"
                "不要选 app.conf；失败可重试，B 站会自动合并音视频。",
            )
            parent = self.parent()
            if parent and hasattr(parent, "navigate_to"):
                parent.navigate_to("download")
            self.accept()
            return
        if item.action == "special:gpu":
            parent = self.parent()
            if parent and hasattr(parent, "navigate_to"):
                parent.navigate_to("profile")
            self.accept()
            return
        if item.action == "special:build":
            QMessageBox.information(
                self, "编译引擎",
                "请在仓库根目录运行：\n"
                "  build_x64.bat\n"
                "或直接：\n"
                "  run_ui_x64.bat\n"
                "成功后应有 build_x64\\bin\\Release\\media_cli.exe 与 media_player.exe。\n"
                "完成后点「重新检测」。",
            )
            return
        if item.action == "special:llm":
            QMessageBox.information(
                self, "本地 LLM",
                "将 .gguf 放到 models\\ 目录。\n"
                "GPU 推理推荐（无需完整 CUDA Toolkit）：\n"
                "  python scripts/setup_llama_gpu.py install-vulkan\n"
                "装好 Vulkan SDK 后重开终端，再 build_x64.bat。\n"
                "无 gguf 时演讲金句仍可用规则/人声段兜底。",
            )
            return
        if item.action.endswith(".bat"):
            bat = _project_root() / item.action.replace("/", os.sep)
            if not bat.is_file():
                QMessageBox.warning(self, "脚本缺失", f"未找到：\n{bat}")
                return
            try:
                subprocess.Popen(
                    ["cmd", "/c", str(bat)],
                    cwd=str(_project_root()),
                    creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
                QMessageBox.information(
                    self, "已启动",
                    f"已在新窗口运行：\n{bat.name}\n完成后点「重新检测」。",
                )
            except OSError as e:
                QMessageBox.warning(self, "启动失败", str(e))

    @Slot()
    def _on_trial(self):
        bridge = getattr(self._vm, "bridge", None)
        if bridge is None:
            QMessageBox.warning(
                self, "试跑",
                "引擎尚未就绪。请先运行 build_x64.bat / run_ui_x64.bat，再点「重新检测」。",
            )
            return
        from core.trial_run import find_trial_sample

        if not find_trial_sample():
            QMessageBox.warning(
                self, "试跑",
                "未找到 tests/test_video.mp4 等样例，请放入任意短视频后再试。",
            )
            return

        self._btn_trial.setEnabled(False)
        self._trial_progress.setVisible(True)
        self._trial_progress.setValue(0)
        self._trial_status.setText("试跑进行中…")

        class _Worker(QThread):
            progress = Signal(float, str)
            finished_ok = Signal(str, str)
            finished_err = Signal(str)

            def __init__(self, br, parent=None):
                super().__init__(parent)
                self._br = br

            def run(self):
                try:
                    from core.trial_run import run_trial_15s

                    path, msg = run_trial_15s(
                        self._br,
                        on_progress=lambda p, m: self.progress.emit(p, m),
                    )
                    self.finished_ok.emit(path, msg)
                except Exception as e:
                    self.finished_err.emit(str(e))

        self._trial_thread = _Worker(bridge, self)
        self._trial_thread.progress.connect(self._on_trial_progress)
        self._trial_thread.finished_ok.connect(self._on_trial_ok)
        self._trial_thread.finished_err.connect(self._on_trial_err)
        self._trial_thread.start()

    @Slot(float, str)
    def _on_trial_progress(self, p: float, msg: str):
        self._trial_progress.setValue(int(max(0, min(100, p))))
        self._trial_status.setText(msg)

    @Slot(str, str)
    def _on_trial_ok(self, path: str, msg: str):
        self._btn_trial.setEnabled(True)
        self._trial_progress.setValue(100)
        self._trial_status.setText("试跑成功")
        QMessageBox.information(self, "试跑成功", msg)
        try:
            os.startfile(str(Path(path).parent))  # type: ignore[attr-defined]
        except Exception:
            pass

    @Slot(str)
    def _on_trial_err(self, err: str):
        self._btn_trial.setEnabled(True)
        self._trial_status.setText("试跑失败")
        QMessageBox.warning(
            self, "试跑失败",
            f"{err}\n\n常见原因：media_cli 未编译、ffmpeg 缺失、样例损坏。",
        )

    @Slot()
    def _on_done(self):
        app = getattr(self._vm, "_app", None) or getattr(self._vm, "app", None)
        st = collect_setup_status(app)
        if st.missing_critical:
            r = QMessageBox.warning(
                self, "关键依赖缺失",
                "本地引擎 media_cli 尚未就绪，切片/超分等会「点了没反应」。\n"
                "建议先运行 build_x64.bat，再点「重新检测」。\n\n"
                "仍要进入应用吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return
        update_app_config_value("setup_wizard_done", "true")
        self.accept()
