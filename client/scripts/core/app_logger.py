"""应用统一日志（UI / 子进程 IPC）——写入 docs/*.txt"""

from __future__ import annotations

import logging
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def log_dir() -> Path:
    """运行时日志目录：项目 docs/"""
    d = _project_root() / "docs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file_path(component: str) -> Path:
    """组件日志 txt 路径，如 docs/log_media_player.txt"""
    safe = component.strip().lower().replace(" ", "_")
    if not safe.startswith("log_"):
        safe = f"log_{safe}"
    return log_dir() / f"{safe}.txt"


def setup_logging(name: str = "MusicEditing", level: str = "INFO") -> logging.Logger:
    """初始化控制台 + docs/log_{name}.txt"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    lvl = getattr(logging, level.upper(), logging.INFO)
    logger.setLevel(lvl)
    fmt = logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    log_path = log_file_path(name)
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    logger.info("日志文件: %s level=%s", log_path, level)
    return logger


def media_player_log_path() -> str:
    return str(log_file_path("media_player"))
