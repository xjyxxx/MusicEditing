#!/usr/bin/env python3
"""AI 本地音视频处理工具 - 启动入口"""

import os
import sys
from pathlib import Path

# 确保 scripts 目录在 Python 路径中
scripts_dir = Path(__file__).resolve().parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from core.app_logger import setup_logging

setup_logging("MusicEditing", os.environ.get("MUSIC_LOG_LEVEL", "INFO"))

from ui.main_window import run_app

if __name__ == "__main__":
    run_app()
