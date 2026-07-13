"""主窗口 UI"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSlider, QComboBox, QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from ui.video_player import VideoPlayerWidget
from viewmodels.main_vm import MainViewModel


class FeatureCard(QFrame):
    """首页功能快捷卡片"""

    def __init__(self, title: str, desc: str, tab_index: int, on_click, parent=None):
        super().__init__(parent)
        self.tab_index = tab_index
        self.setFrameShape(QFrame.StyledPanel)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            "FeatureCard { background: #2d2d3a; border-radius: 8px; padding: 12px; }"
            "FeatureCard:hover { background: #3d3d5c; }"
        )
        layout = QVBoxLayout(self)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-size: 16px; font-weight: bold; color: #e0e0ff;")
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet("color: #aaa; font-size: 12px;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(title_lbl)
        layout.addWidget(desc_lbl)
        self.mousePressEvent = lambda e: on_click(tab_index)


class HomePage(QWidget):
    def __init__(self, vm: MainViewModel, switch_tab, parent=None):
        super().__init__(parent)
        self._vm = vm
        layout = QVBoxLayout(self)

        title = QLabel("AI 本地音视频处理工具")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #fff; margin: 8px 0;")
        layout.addWidget(title)

        splitter = QSplitter(Qt.Vertical)

        # 播放器区域
        player_box = QGroupBox("本地预览播放器")
        player_box.setStyleSheet("QGroupBox { font-weight: bold; color: #aaf; }")
        player_layout = QVBoxLayout(player_box)
        self._player = VideoPlayerWidget()
        player_layout.addWidget(self._player)
        splitter.addWidget(player_box)

        # 功能快捷入口
        cards_widget = QWidget()
        cards_layout = QVBoxLayout(cards_widget)
        cards_layout.setContentsMargins(0, 8, 0, 0)
        hint = QLabel("快捷功能（导入的视频可在上方直接预览）")
        hint.setStyleSheet("color: #888; font-size: 12px;")
        cards_layout.addWidget(hint)

        grid = QGridLayout()
        cards = [
            ("智能切片", "自动识别长视频精彩瞬间，一键剪辑导出", 1),
            ("4K 超分", "1080P 升级 4K，画质修复与帧补全", 2),
            ("一键去水印", "复杂水印、边角水印智能去除", 3),
        ]
        for i, (t, d, idx) in enumerate(cards):
            grid.addWidget(FeatureCard(t, d, idx, switch_tab), i // 3, i % 3)
        cards_layout.addLayout(grid)
        splitter.addWidget(cards_widget)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        # 打开视频时同步导入到 ViewModel（供其他模块使用）
        self._player.fileOpened.connect(vm.import_video)
        vm.videoLoaded.connect(self._on_video_loaded)

    @Slot(object)
    def _on_video_loaded(self, video):
        """其他页面导入视频后，主页播放器同步加载（避免与当前已打开文件重复加载）"""
        if not video or not getattr(video, "file_path", ""):
            return
        cur = os.path.normcase(os.path.abspath(self._player.current_path or ""))
        vid = os.path.normcase(os.path.abspath(video.file_path))
        if cur != vid:
            self._player.load_from_video_model(video, auto_play=False)

    def shutdown_player(self):
        self._player.shutdown()


class SlicePage(QWidget):
    def __init__(self, vm: MainViewModel, parent=None):
        super().__init__(parent)
        self._vm = vm
        layout = QVBoxLayout(self)

        # 导入区
        import_row = QHBoxLayout()
        self._file_label = QLabel("未选择视频")
        btn_import = QPushButton("导入视频")
        btn_import.clicked.connect(self._on_import)
        import_row.addWidget(self._file_label, 1)
        import_row.addWidget(btn_import)
        layout.addLayout(import_row)

        # 视频信息
        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #8cf;")
        layout.addWidget(self._info_label)

        # 参数配置
        params_box = QGroupBox("AI 识别参数")
        params_layout = QGridLayout(params_box)

        self._scene_combo = QComboBox()
        self._scene_combo.addItems(["游戏高光", "演讲金句", "日常精彩片段", "自定义识别"])
        params_layout.addWidget(QLabel("场景:"), 0, 0)
        params_layout.addWidget(self._scene_combo, 0, 1)

        self._min_slider = QSlider(Qt.Horizontal)
        self._min_slider.setRange(3, 30)
        self._min_slider.setValue(3)
        self._min_label = QLabel("3s")
        params_layout.addWidget(QLabel("最短片段:"), 1, 0)
        params_layout.addWidget(self._min_slider, 1, 1)
        params_layout.addWidget(self._min_label, 1, 2)

        self._max_slider = QSlider(Qt.Horizontal)
        self._max_slider.setRange(10, 120)
        self._max_slider.setValue(60)
        self._max_label = QLabel("60s")
        params_layout.addWidget(QLabel("最长片段:"), 2, 0)
        params_layout.addWidget(self._max_slider, 2, 1)
        params_layout.addWidget(self._max_label, 2, 2)

        self._sens_slider = QSlider(Qt.Horizontal)
        self._sens_slider.setRange(0, 100)
        self._sens_slider.setValue(50)
        self._sens_label = QLabel("50%")
        params_layout.addWidget(QLabel("敏感度:"), 3, 0)
        params_layout.addWidget(self._sens_slider, 3, 1)
        params_layout.addWidget(self._sens_label, 3, 2)

        self._min_slider.valueChanged.connect(lambda v: self._min_label.setText(f"{v}s"))
        self._max_slider.valueChanged.connect(lambda v: self._max_label.setText(f"{v}s"))
        self._sens_slider.valueChanged.connect(lambda v: self._sens_label.setText(f"{v}%"))

        layout.addWidget(params_box)

        # 进度
        self._progress = QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # 高光列表
        self._highlight_list = QListWidget()
        layout.addWidget(self._highlight_list)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_analyze = QPushButton("AI 智能分析")
        btn_analyze.setStyleSheet("background: #5b5bd6; color: white; padding: 8px 20px;")
        btn_analyze.clicked.connect(self._on_analyze)
        btn_export = QPushButton("批量导出")
        btn_export.clicked.connect(self._on_export)
        btn_row.addWidget(btn_analyze)
        btn_row.addWidget(btn_export)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        vm.videoLoaded.connect(self._on_video_loaded)
        vm.progressUpdated.connect(self._on_progress)
        vm.highlightsReady.connect(self._on_highlights)
        vm.errorOccurred.connect(self._show_error)

    @Slot()
    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频",
            "", "视频文件 (*.mp4 *.mov *.avi *.flv *.mkv);;所有文件 (*.*)"
        )
        if path:
            self._vm.import_video(path)

    @Slot(object)
    def _on_video_loaded(self, video):
        name = os.path.basename(video.file_path)
        self._file_label.setText(name)
        self._info_label.setText(
            f"分辨率: {video.width}x{video.height} | "
            f"时长: {video.duration_sec:.1f}s | "
            f"帧率: {video.fps:.1f}fps | "
            f"编码: {video.codec_name}"
        )

    @Slot()
    def _on_analyze(self):
        self._vm.update_slice_params(
            self._scene_combo.currentText(),
            self._min_slider.value(),
            self._max_slider.value(),
            self._sens_slider.value() / 100.0,
        )
        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._highlight_list.clear()
        self._vm.start_slice_analysis()

    @Slot(int, float, str)
    def _on_progress(self, task_id, progress, message):
        self._progress.setValue(int(progress))

    @Slot(list)
    def _on_highlights(self, segments):
        self._progress.setValue(100)
        for seg in segments:
            self._highlight_list.addItem(
                f"[{seg.start_sec:.1f}s - {seg.end_sec:.1f}s] 得分: {seg.score:.2f}"
            )

    @Slot()
    def _on_export(self):
        if self._highlight_list.count() == 0:
            QMessageBox.warning(self, "提示", "请先完成 AI 分析")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if out_dir:
            self._vm.set_output_dir(out_dir)
            QMessageBox.information(self, "导出", f"将导出到: {out_dir}\n（导出功能待后续实现）")

    @Slot(str)
    def _show_error(self, msg):
        QMessageBox.critical(self, "错误", msg)


class PlaceholderPage(QWidget):
    """画质增强 / 去水印 / 个人中心 占位页"""

    def __init__(self, title: str, desc: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 20px; font-weight: bold; color: #fff;")
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet("color: #aaa;")
        desc_lbl.setWordWrap(True)
        layout.addWidget(lbl)
        layout.addWidget(desc_lbl)
        layout.addStretch()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AI 本地音视频处理工具")
        self.setMinimumSize(960, 720)
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #1e1e2e; color: #e0e0e0; }
            QTabWidget::pane { border: 1px solid #444; }
            QTabBar::tab { background: #2d2d3a; color: #ccc; padding: 8px 16px; }
            QTabBar::tab:selected { background: #5b5bd6; color: white; }
            QPushButton { background: #3d3d5c; color: #eee; border-radius: 4px; padding: 6px 14px; }
            QPushButton:hover { background: #5b5bd6; }
            QGroupBox { border: 1px solid #555; border-radius: 4px; margin-top: 8px; padding-top: 8px; }
            QGroupBox::title { color: #aaf; }
            QProgressBar { border: 1px solid #555; border-radius: 4px; text-align: center; }
            QProgressBar::chunk { background: #5b5bd6; }
            QListWidget { background: #2d2d3a; border: 1px solid #555; }
        """)

        self._vm = MainViewModel()

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # 顶部状态栏
        status_bar = QHBoxLayout()
        self._gpu_label = QLabel()
        self._auth_label = QLabel()
        self._version_label = QLabel(f"v{self._vm.version}")
        status_bar.addWidget(self._gpu_label)
        status_bar.addWidget(self._auth_label)
        status_bar.addStretch()
        status_bar.addWidget(self._version_label)
        main_layout.addLayout(status_bar)

        self._vm.gpuNameChanged.connect(lambda n: self._gpu_label.setText(f"GPU: {n}"))
        self._vm.authTypeChanged.connect(lambda a: self._auth_label.setText(f"授权: {a}"))
        self._gpu_label.setText(f"GPU: {self._vm.gpu_name}")
        self._auth_label.setText(f"授权: {self._vm.auth_type}")

        # 标签页
        self._tabs = QTabWidget()
        self._home_page = HomePage(self._vm, self._switch_tab)
        self._tabs.addTab(self._home_page, "首页")
        self._tabs.addTab(SlicePage(self._vm), "智能切片")
        self._tabs.addTab(PlaceholderPage("画质增强 / 4K 超分",
            "支持 1080P→4K 超分、基础修复、老旧视频修复。付费功能待授权解锁。"), "画质增强")
        self._tabs.addTab(PlaceholderPage("一键去水印",
            "支持矩形/多区域框选水印，时间段水印去除。AI 修复预览待实现。"), "去水印")
        self._tabs.addTab(PlaceholderPage("个人中心",
            "卡密兑换、版本更新、关于软件。"), "个人中心")
        main_layout.addWidget(self._tabs)

        # 底部状态
        self._status_label = QLabel(self._vm.status_message)
        self._status_label.setStyleSheet("color: #888; padding: 4px;")
        self._vm.statusMessageChanged.connect(self._status_label.setText)
        main_layout.addWidget(self._status_label)

        # GPU 提示
        from core.app_logic import AppLogic
        app = AppLogic()
        if not app.gpu_info["cuda_available"]:
            QMessageBox.information(
                self, "硬件提示",
                "当前为 CPU 模式，处理速度较慢。\n支持 NVIDIA 显卡硬件加速（CUDA）。"
            )

    def _switch_tab(self, index: int):
        self._tabs.setCurrentIndex(index)

    def shutdown(self):
        """退出前释放播放器与子进程"""
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        self._home_page.shutdown_player()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)


def run_app():
    import sys
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(True)
    win = MainWindow()
    app.aboutToQuit.connect(win.shutdown)
    win.show()
    sys.exit(app.exec())
