#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llama GPU 源码构建（推荐 Vulkan，无需下载巨型 CUDA Toolkit）。

用法:
  python scripts/setup_llama_gpu.py              # 检测
  python scripts/setup_llama_gpu.py vulkan       # 装 Vulkan SDK（若缺）并源码构建
  python scripts/setup_llama_gpu.py cuda         # 需 CUDA Toolkit（体积大，可选）
  python scripts/setup_llama_gpu.py install-vulkan
  python scripts/setup_llama_gpu.py install-cuda

兼容旧入口: setup_llama_cuda.py → 转发到本脚本。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LLAMA_SRC = ROOT / "third_party" / "llama.cpp"
BUILD_DIR = ROOT / "build_x64"
CUDA_VERSIONS = [
    "v12.6", "v12.5", "v12.4", "v12.3", "v12.2", "v12.1", "v12.0",
    "v13.0", "v13.1", "v13.2", "v13.3",
]


def find_nvcc() -> Path | None:
    w = shutil.which("nvcc")
    if w:
        return Path(w)
    base = Path(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA")
    for ver in CUDA_VERSIONS:
        p = base / ver / "bin" / "nvcc.exe"
        if p.is_file():
            return p
    return None


def find_vulkan_sdk() -> Path | None:
    env = os.environ.get("VULKAN_SDK", "").strip()
    if env:
        p = Path(env)
        if (p / "Include" / "vulkan" / "vulkan.h").is_file() or (
            p / "include" / "vulkan" / "vulkan.h"
        ).is_file():
            return p
    root = Path(r"C:\VulkanSDK")
    if not root.is_dir():
        return None
    versions = sorted(
        [d for d in root.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )
    for d in versions:
        if (d / "Include" / "vulkan" / "vulkan.h").is_file() or (
            d / "include" / "vulkan" / "vulkan.h"
        ).is_file():
            return d
    return None


def find_glslc(sdk: Path | None = None) -> Path | None:
    w = shutil.which("glslc")
    if w:
        return Path(w)
    sdk = sdk or find_vulkan_sdk()
    if not sdk:
        return None
    for rel in ("Bin/glslc.exe", "bin/glslc.exe"):
        p = sdk / rel
        if p.is_file():
            return p
    return None


def run(cmd: list[str], env: dict | None = None) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd, cwd=str(ROOT), env=env)


def ensure_llama_src() -> bool:
    if (LLAMA_SRC / "CMakeLists.txt").is_file():
        return True
    print(f"[错误] 缺少源码: {LLAMA_SRC}")
    print("  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git third_party/llama.cpp")
    return False


def cmd_check() -> int:
    print("=== MusicEditing · llama GPU 检测 ===\n")
    print("推荐：Vulkan（无需 CUDA Toolkit，体积小得多）")
    print("备选：CUDA（需完整 Toolkit，数 GB）\n")
    if not ensure_llama_src():
        return 1
    print(f"[OK] 源码: {LLAMA_SRC}")

    smi = shutil.which("nvidia-smi")
    if smi:
        subprocess.call(
            [smi, "--query-gpu=name,driver_version", "--format=csv,noheader"]
        )
    else:
        print("[警告] 未找到 nvidia-smi")

    sdk = find_vulkan_sdk()
    glslc = find_glslc(sdk)
    nvcc = find_nvcc()

    print()
    if sdk and glslc:
        print(f"[OK] Vulkan SDK: {sdk}")
        print(f"[OK] glslc: {glslc}")
        print("可执行: python scripts/setup_llama_gpu.py vulkan")
    else:
        print("[缺失] Vulkan SDK / glslc")
        print("  python scripts/setup_llama_gpu.py install-vulkan")
        print("  然后: python scripts/setup_llama_gpu.py vulkan")

    print()
    if nvcc:
        print(f"[OK] nvcc: {nvcc}")
        print("可执行: python scripts/setup_llama_gpu.py cuda")
    else:
        print("[跳过] 无 CUDA Toolkit（体积大，一般不必装）")

    if not ((sdk and glslc) or nvcc):
        print("\n装好前主工程仍用 llama_prebuilt (CPU)。")
        return 2
    return 0


def cmd_install_vulkan() -> int:
    print("安装 Vulkan SDK（winget KhronosGroup.VulkanSDK）…")
    code = run(
        [
            "winget", "install", "-e", "--id", "KhronosGroup.VulkanSDK",
            "--accept-package-agreements", "--accept-source-agreements",
        ]
    )
    if code != 0:
        print("[错误] winget 失败，请手动: https://vulkan.lunarg.com/sdk/home")
        return code
    print("安装后请重开终端，再运行:")
    print("  python scripts/setup_llama_gpu.py vulkan")
    return 0


def cmd_install_cuda() -> int:
    print("警告: CUDA Toolkit 体积很大（数 GB）。若只要 LLM 上 GPU，请改用 Vulkan。")
    print("安装 NVIDIA CUDA Toolkit（winget Nvidia.CUDA）…")
    code = run(
        [
            "winget", "install", "-e", "--id", "Nvidia.CUDA",
            "--accept-package-agreements", "--accept-source-agreements",
        ]
    )
    if code != 0:
        print("[错误] winget 失败: https://developer.nvidia.com/cuda-downloads")
        return code
    print("安装后请重开终端，再运行:")
    print("  python scripts/setup_llama_gpu.py cuda")
    return 0


def _cmake_build(extra: list[str], env: dict) -> int:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("media_player.exe", "media_cli.exe"):
        subprocess.call(
            ["taskkill", "/F", "/IM", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    cmake = [
        "cmake", "-S", str(ROOT), "-B", str(BUILD_DIR),
        "-G", "Visual Studio 18 2026", "-A", "x64",
        *extra,
    ]
    code = run(cmake, env=env)
    if code != 0:
        print("[错误] CMake 配置失败")
        return code
    code = run(
        ["cmake", "--build", str(BUILD_DIR), "--config", "Release", "--target", "media_cli"],
        env=env,
    )
    if code != 0:
        print("[错误] 编译失败")
        return code
    return 0


def cmd_build_vulkan() -> int:
    if not ensure_llama_src():
        return 1
    sdk = find_vulkan_sdk()
    glslc = find_glslc(sdk)
    if not sdk or not glslc:
        print("[错误] 未找到 Vulkan SDK / glslc，先 install-vulkan")
        return 2
    env = os.environ.copy()
    env["VULKAN_SDK"] = str(sdk)
    bin_dir = str(glslc.parent)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    print(f"VULKAN_SDK={sdk}")
    code = _cmake_build(
        [
            "-DMUSIC_GGML_VULKAN=ON",
            "-DMUSIC_LLAMA_FROM_SOURCE=ON",
            "-DMUSIC_GGML_CUDA=OFF",
        ],
        env,
    )
    if code == 0:
        print()
        print("[成功] llama 已按源码+Vulkan 链入 media_cli（无需 CUDA Toolkit）")
        print("验证: 配置日志含「GGML_VULKAN=ON」；个人中心开 GPU；准备 .gguf")
    return code


def cmd_build_cuda() -> int:
    if not ensure_llama_src():
        return 1
    nvcc = find_nvcc()
    if not nvcc:
        print("[错误] 未找到 nvcc。更推荐: python scripts/setup_llama_gpu.py vulkan")
        return 2
    env = os.environ.copy()
    env["PATH"] = str(nvcc.parent) + os.pathsep + env.get("PATH", "")
    if "CUDA_PATH" not in env:
        env["CUDA_PATH"] = str(nvcc.parent.parent)
    print(f"CUDA_PATH={env['CUDA_PATH']}")
    code = _cmake_build(
        [
            "-DMUSIC_GGML_CUDA=ON",
            "-DMUSIC_LLAMA_FROM_SOURCE=ON",
            "-DMUSIC_GGML_VULKAN=OFF",
            "-DCMAKE_CUDA_ARCHITECTURES=89;86;80;75",
        ],
        env,
    )
    if code == 0:
        print()
        print("[成功] llama 已按源码+CUDA 链入 media_cli")
    return code


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "check").strip().lower()
    # 兼容旧 cuda 脚本参数
    if mode in ("", "check", "c"):
        return cmd_check()
    if mode in ("vulkan", "vk", "build-vulkan"):
        return cmd_build_vulkan()
    if mode in ("cuda", "build", "build-cuda"):
        return cmd_build_cuda()
    if mode in ("install-vulkan", "install_vulkan", "iv"):
        return cmd_install_vulkan()
    if mode in ("install", "install-cuda", "install_cuda", "ic"):
        return cmd_install_cuda()
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
