#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容入口：转发到 setup_llama_gpu.py（推荐 Vulkan，免 CUDA Toolkit）。"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

# 旧用法 install/build/check → 映射到新脚本
args = sys.argv[1:]
if not args or args[0].lower() in ("check", "c", ""):
    sys.argv = [sys.argv[0], "check"]
elif args[0].lower() in ("install", "i"):
    # 默认引导 Vulkan，不再默认拉巨型 CUDA
    print("提示: 默认改走 Vulkan（免 CUDA Toolkit）。若坚持 CUDA: setup_llama_gpu.py install-cuda")
    sys.argv = [sys.argv[0], "install-vulkan"]
elif args[0].lower() in ("build", "b"):
    sys.argv = [sys.argv[0], "vulkan"]
else:
    sys.argv = [sys.argv[0], *args]

runpy.run_path(str(Path(__file__).with_name("setup_llama_gpu.py")), run_name="__main__")
