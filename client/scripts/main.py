#!/usr/bin/env python3
"""AI 本地音视频处理工具 - 启动入口"""

import os
import sys
import threading
from pathlib import Path

# 确保 scripts 目录在 Python 路径中
scripts_dir = Path(__file__).resolve().parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

# 便携包用 pythonw：必须尽早隐藏 media_cli/ffmpeg 等控制台子进程，否则狂闪黑框且 UI 卡
try:
    from core.win_subprocess import install_hidden_console_patch

    install_hidden_console_patch()
except Exception:
    pass

# 须在首次 import QtMultimedia 之前：用系统 WMF，避免与引擎目录 av*.dll 混载导致
# 「一点播放就跳到最后一帧」。开发机也可设 QT_MEDIA_BACKEND=ffmpeg 覆盖。
os.environ.setdefault("QT_MEDIA_BACKEND", "windows")

from core.app_logger import setup_logging

setup_logging("MusicEditing", os.environ.get("MUSIC_LOG_LEVEL", "INFO"))


def _bg_cleanup_orphan_temps():
    """启动时后台清理崩溃残留临时帧（>6h），不堵 UI 主线程。"""
    try:
        from core.resource_cleanup import cleanup_orphan_temp_dirs

        cleanup_orphan_temp_dirs(max_age_hours=6.0, dry_run=False)
    except Exception:
        pass


threading.Thread(
    target=_bg_cleanup_orphan_temps, daemon=True, name="orphan-temp-cleanup",
).start()

from ui.main_window import run_app

if __name__ == "__main__":
    run_app()
