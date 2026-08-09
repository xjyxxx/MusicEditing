#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包可分发的 MusicEditing 便携目录（内嵌 Python，默认不带可读源码）。

用法（仓库根）:
  python scripts/pack_portable.py
  python scripts/pack_portable.py --zip
  python scripts/pack_portable.py --ship-source   # 调试：保留 .py（不推荐外发）

说明:
  - 默认将 client/scripts 编成 .pyc 后删除 .py，降低源码泄露风险
  - C++ 引擎本身就是 exe/dll，不含工程源码
  - .pyc 仍可被反编译，不是军工级保护；需要更强可再上 Nuitka
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "build_x64" / "bin" / "Release"

# 官方 Windows embeddable（可随包带走，不依赖对方装 Python）
EMBED_PY_VERSION = "3.10.11"
EMBED_PY_URL = (
    f"https://www.python.org/ftp/python/{EMBED_PY_VERSION}/"
    f"python-{EMBED_PY_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

REQUIRED_BIN = (
    "media_cli.exe",
    "media_player.exe",
    "media_engine.dll",
    "ffmpeg.exe",
    "ffprobe.exe",
)

OPTIONAL_BIN_GLOBS = (
    "avcodec-*.dll",
    "avdevice-*.dll",
    "avfilter-*.dll",
    "avformat-*.dll",
    "avutil-*.dll",
    "swresample-*.dll",
    "swscale-*.dll",
    "glew32.dll",
    "opencv_world*.dll",
    "onnxruntime.dll",
    "onnxruntime_providers_shared.dll",
    "yt-dlp.exe",
    "exiftool.exe",
    # ffplay 仅调试用，默认不打进包
)

CUDA_ORT_GLOBS = (
    "onnxruntime_providers_cuda.dll",
    "onnxruntime_providers_tensorrt.dll",
)

SKIP_BIN_NAMES = {
    "media_engine_test.exe",
    "shared_test.exe",
    "_sr_test_ai.png",
    "_sr_test_in.png",
    "_sr_test_out.png",
}


def _die(msg: str, code: int = 1) -> None:
    print(f"[错误] {msg}", flush=True)
    raise SystemExit(code)


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path, *, ignore=None) -> None:
    if not src.is_dir():
        return
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def _expand_globs(folder: Path, patterns: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for pat in patterns:
        out.extend(sorted(folder.glob(pat)))
    return out


def _ignore_pycache(dirpath: str, names: list[str]) -> list[str]:
    skip = []
    for n in names:
        if n in ("__pycache__", ".pytest_cache", ".mypy_cache"):
            skip.append(n)
        elif n.endswith(".pyc"):
            skip.append(n)
    return skip


def _ignore_scenedetect(dirpath: str, names: list[str]) -> list[str]:
    """PySceneDetect 源码里 packaging/ 含安装包 7z，约几十 MB，分发不需要。"""
    skip = _ignore_pycache(dirpath, names)
    base = Path(dirpath).name.lower()
    for n in names:
        low = n.lower()
        if low in ("packaging", "docs", "tests", "test", ".git", ".github", "website"):
            skip.append(n)
        elif low.endswith(".7z") or low.endswith(".msi"):
            skip.append(n)
    if base == "windows" or "prerequisites" in Path(dirpath).as_posix().lower():
        for n in names:
            if n not in skip:
                skip.append(n)
    return skip


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if r.returncode != 0:
        _die(f"命令失败 ({r.returncode}): {' '.join(cmd)}")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 1000:
        print(f"[缓存] {dest.name}", flush=True)
        return
    print(f"[下载] {url}", flush=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(dest)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _enable_embed_site(runtime: Path) -> None:
    """打开 embed 包的 site-packages，否则 pip 装的库 import 不到。"""
    pths = list(runtime.glob("python*._pth"))
    if not pths:
        _die(f"未找到 python*._pth: {runtime}")
    pth = pths[0]
    zips = list(runtime.glob("python*.zip"))
    zip_name = zips[0].name if zips else "python310.zip"
    content = f"{zip_name}\n.\nLib\\site-packages\nimport site\n"
    pth.write_text(content, encoding="utf-8", newline="\n")
    print(f"[嵌入] 已启用 site: {pth.name}", flush=True)


def _strip_python_sources(out_root: Path, *, py_exe: Path) -> None:
    """把 UI 编成 .pyc 后删除 .py，避免分发包直接泄露源码。

    注意：.pyc 仍可被反编译，只是提高门槛；真要强保护需 Nuitka 等另做。
    必须用「包内 embed 的同版本 python」编译，否则版本不匹配无法加载。
    """
    scripts = out_root / "client" / "scripts"
    if not scripts.is_dir():
        return
    if not py_exe.is_file():
        _die(f"无法去源码：找不到 {py_exe}")

    print("[安全] 编译 UI 为字节码并移除 .py 源码…", flush=True)
    # -b: legacy 同目录 .pyc；-o 2: 去断言/部分调试信息
    _run([
        str(py_exe), "-m", "compileall", "-b", "-q", "-f", "-o", "2",
        str(scripts),
    ])

    removed = 0
    for py in scripts.rglob("*.py"):
        try:
            py.unlink()
            removed += 1
        except OSError:
            pass
    # 清掉残留 __pycache__（legacy 已写到旁路 .pyc）
    for cache in scripts.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    main_pyc = scripts / "main.pyc"
    if not main_pyc.is_file():
        _die("去源码失败：未生成 client/scripts/main.pyc")
    print(f"[安全] 已删除 {removed} 个 .py，入口: client/scripts/main.pyc", flush=True)


def _remove_shipped_scenedetect_sources(out_root: Path) -> None:
    """PySceneDetect 已 pip 进 runtime，不必再带一份可读源码。"""
    sd = out_root / "third_party" / "PySceneDetect"
    if sd.is_dir():
        print("[安全] 移除 third_party/PySceneDetect 源码（已装入 runtime）", flush=True)
        shutil.rmtree(sd, ignore_errors=True)


def _embed_python_runtime(out_root: Path, *, with_scenedetect: bool) -> Path:
    """下载官方 embeddable Python，预装依赖（真正可拷到别人电脑）。"""
    if struct_calcsize_p() != 8:
        _die("打包机必须是 64 位 Python")

    cache = ROOT / "dist" / "_cache"
    embed_zip = cache / f"python-{EMBED_PY_VERSION}-embed-amd64.zip"
    get_pip = cache / "get-pip.py"
    _download(EMBED_PY_URL, embed_zip)
    _download(GET_PIP_URL, get_pip)

    runtime = out_root / "runtime"
    print("[嵌入] 解压 embeddable Python → runtime\\", flush=True)
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir(parents=True)
    with zipfile.ZipFile(embed_zip, "r") as zf:
        zf.extractall(runtime)

    _enable_embed_site(runtime)
    py = runtime / "python.exe"
    if not py.is_file():
        _die(f"解压失败，未找到 {py}")

    print("[嵌入] 安装 pip …", flush=True)
    _run([str(py), str(get_pip), "--no-warn-script-location"])

    req = out_root / "client" / "scripts" / "requirements.txt"
    if not req.is_file():
        _die(f"缺少 {req}")

    print("[嵌入] pip 安装 PySide6 / numpy / opencv / vosk …（需联网，数分钟）", flush=True)
    _run([str(py), "-m", "pip", "install", "--upgrade", "pip", "wheel"])
    _run([str(py), "-m", "pip", "install", "-r", str(req)])

    sd = out_root / "third_party" / "PySceneDetect"
    if with_scenedetect and (sd / "scenedetect" / "__init__.py").is_file():
        print("[嵌入] pip 安装 PySceneDetect", flush=True)
        _run([str(py), "-m", "pip", "install", str(sd)])

    _run([
        str(py), "-c",
        "import PySide6, numpy; print('runtime OK', PySide6.__version__)",
    ])
    return py


def struct_calcsize_p() -> int:
    import struct
    return struct.calcsize("P")


def _find_vcvars64() -> Path | None:
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    if not vswhere.is_file():
        return None
    try:
        r = subprocess.run(
            [
                str(vswhere),
                "-latest",
                "-products", "*",
                "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                "-property", "installationPath",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    root = (r.stdout or "").strip()
    if not root:
        return None
    cand = Path(root) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    return cand if cand.is_file() else None


def _compile_exe_launcher(out_root: Path) -> Path | None:
    """编译无黑框 MusicEditing.exe；失败则返回 None（仍保留 .bat）。

    注意：不能用 ``cmd /c "call \"…\\vcvars64.bat\" && …"``——嵌套引号会被
    cmd 拆坏（VS 安装在 ``Program Files\\Microsoft Visual Studio\\…`` 时必现）。
    正确做法是写临时 .bat 再 ``cmd /c build.bat``。
    """
    src = ROOT / "scripts" / "portable_launcher.c"
    if not src.is_file():
        print("[警告] 缺少 portable_launcher.c，跳过 exe 启动器")
        return None
    vcvars = _find_vcvars64()
    if vcvars is None:
        print("[警告] 未找到 VS vcvars64.bat，跳过 MusicEditing.exe（仍可用 .bat）")
        return None

    out_exe = out_root / "MusicEditing.exe"
    # 在临时目录编译，避免污染包根
    work = out_root / "_launcher_build"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    obj = work / "portable_launcher.obj"
    # 用绝对路径写进 bat；路径含空格时靠 bat 内双引号，勿再经 cmd /c 二次转义
    build_bat = work / "build_launcher.bat"
    build_bat.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                f'call "{vcvars}"',
                "if errorlevel 1 exit /b 1",
                (
                    f'cl /nologo /O2 /W3 /utf-8 '
                    f'/Fo"{obj}" /Fe"{out_exe}" "{src}" '
                    f"/link /SUBSYSTEM:WINDOWS user32.lib"
                ),
                "exit /b %ERRORLEVEL%",
                "",
            ]
        ),
        encoding="ascii",
        newline="\r\n",
    )
    print("[编译] MusicEditing.exe（无控制台启动器）…", flush=True)
    r = subprocess.run(
        ["cmd", "/c", str(build_bat)],
        cwd=str(work),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if r.returncode != 0 or not out_exe.is_file():
        def _safe(s: str) -> str:
            return (s or "").encode("ascii", "replace").decode("ascii")[-800:]
        print(_safe(r.stdout), flush=True)
        print(_safe(r.stderr), flush=True)
        print("[警告] MusicEditing.exe 编译失败，将使用「启动 MusicEditing.bat」")
        shutil.rmtree(work, ignore_errors=True)
        return None
    shutil.rmtree(work, ignore_errors=True)
    print(f"[完成] {out_exe.name}", flush=True)
    return out_exe


def _write_launcher(out_root: Path, *, embed_python: bool) -> None:
    # 主入口：MusicEditing.exe（能编出来时）
    exe = None
    if embed_python:
        exe = _compile_exe_launcher(out_root)

    # 文件名用中文方便用户；内容尽量 ASCII，避免 cmd 默认代码页把 UTF-8 bat 解析坏
    bat = out_root / "启动 MusicEditing.bat"
    if embed_python:
        body = r"""@echo off
setlocal
cd /d "%~dp0"

rem Prefer GUI launcher when present
if exist "%~dp0MusicEditing.exe" (
  start "" "%~dp0MusicEditing.exe"
  exit /b 0
)

echo ========================================
echo  MusicEditing portable (fallback)
echo ========================================

set "PY=%~dp0runtime\pythonw.exe"
if not exist "%PY%" set "PY=%~dp0runtime\python.exe"
if not exist "%PY%" (
  echo [ERROR] missing runtime\pythonw.exe
  pause
  exit /b 1
)

set "BIN=%~dp0build_x64\bin\Release"
if not exist "%BIN%\media_cli.exe" (
  echo [ERROR] missing media_cli.exe
  pause
  exit /b 1
)

set "PATH=%BIN%;%PATH%"
set PYTHONUTF8=1
set PYTHONNOUSERSITE=1

if exist "%~dp0client\scripts\main.pyc" (
  start "" "%PY%" "%~dp0client\scripts\main.pyc"
) else if exist "%~dp0client\scripts\main.py" (
  start "" "%PY%" "%~dp0client\scripts\main.py"
) else (
  echo [ERROR] missing client\scripts\main.pyc
  pause
  exit /b 1
)
exit /b 0
"""
    else:
        body = r"""@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>&1 || (echo Need system Python & pause & exit /b 1)
set "PATH=%~dp0build_x64\bin\Release;%PATH%"
set PYTHONUTF8=1
python -m pip install -r "%~dp0client\scripts\requirements.txt" -q
if exist "%~dp0client\scripts\main.pyc" (
  python "%~dp0client\scripts\main.pyc"
) else (
  python "%~dp0client\scripts\main.py"
)
if errorlevel 1 pause
"""
    bat.write_text(body, encoding="ascii", newline="\r\n")
    if exe:
        print("[提示] 请双击 MusicEditing.exe 启动（.bat 仅备用）", flush=True)
    else:
        print("[提示] 未生成 MusicEditing.exe，请用「启动 MusicEditing.bat」", flush=True)


def _write_readme(
    out_root: Path,
    *,
    with_cuda_ort: bool,
    with_models: bool,
    embed_python: bool,
    ship_source: bool = False,
) -> None:
    txt = out_root / "使用说明.txt"
    if embed_python:
        need = [
            "一、对方电脑需要",
            "  1. Windows 10/11 64 位",
            "  2. 一般无需安装 Python（本包已内嵌 runtime\\）",
            "  3. 若双击闪退：安装 Microsoft Visual C++ 2015–2022 Redistributable (x64)",
            "     https://learn.microsoft.com/zh-cn/cpp/windows/latest-supported-vc-redist",
            "  4. 显卡驱动建议较新。演讲金句 GPU 加速用驱动自带的 Vulkan 运行时，",
            "     不需要 Vulkan SDK；没有独显则自动 CPU，其它功能仍可用。",
            "",
            "二、怎么启动",
            "  解压后双击 MusicEditing.exe（推荐，无黑框）",
            "  「启动 MusicEditing.bat」仅作备用。",
        ]
    else:
        need = [
            "一、对方电脑需要",
            "  1. Windows 10/11 64 位 + 自备 64 位 Python 3.10+",
            "  2. VC++ 2015–2022 x64 运行库",
            "",
            "二、怎么启动",
            "  双击 MusicEditing.exe 或「启动 MusicEditing.bat」",
        ]
    src_note = (
        "  - client\\scripts            已编译为 .pyc（默认不含可读源码）"
        if not ship_source
        else "  - client\\scripts            含 .py 源码（--ship-source 调试包）"
    )
    lines = [
        "MusicEditing 便携版 — 使用说明",
        "=" * 40,
        "",
        *need,
        "",
        "三、本包包含",
        "  - MusicEditing.exe          主程序入口",
        "  - runtime\\                 内嵌官方 Python + PySide6 等（默认）" if embed_python else "  - （未内嵌 Python）",
        src_note,
        "  - build_x64\\bin\\Release     引擎 / FFmpeg / OpenCV / ORT（已是二进制）",
        "  - third_party               yt-dlp / exiftool 等",
        "  - models                    去水印/超分 ONNX（若未跳过）",
        "",
        "四、安全说明",
        "  - C++ 引擎以 exe/dll 分发，不含工程源码",
        "  - Python UI 默认只带字节码 .pyc（可提高阅读门槛，但仍可被专业工具反编译）",
        "  - 不含 Vulkan SDK / CUDA Toolkit / 完整仓库",
        "",
        f"  CUDA ORT EP: {'已包含' if with_cuda_ort else '未包含（默认）'}",
        f"  models: {'已包含' if with_models else '未包含'}",
        "",
        "五、常见问题",
        "  - 闪退：装 VC++ 2015–2022 x64 运行库（少数机器缺）。",
        "  - 抖音失败：下载页导入 Netscape cookies.txt。",
        "  - 演讲慢：个人中心开 GPU，准备 .gguf；需驱动支持 Vulkan。",
        "",
        f"打包时间: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    txt.write_text("\n".join(lines), encoding="utf-8", newline="\r\n")


def pack(
    out_root: Path,
    *,
    with_models: bool,
    with_cuda_ort: bool,
    with_scenedetect: bool,
    with_llm: bool,
    make_zip: bool,
    embed_python: bool,
    ship_source: bool = False,
) -> Path:
    if not BIN.is_dir():
        _die(f"未找到 {BIN}，请先 .\\build_x64.bat 或 setup_llama_gpu.py vulkan")

    for name in REQUIRED_BIN:
        if not (BIN / name).is_file():
            _die(f"缺少必需文件: {BIN / name}")

    if out_root.exists():
        print(f"[清理] {out_root}")
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)

    print("[拷贝] client/scripts + client/resources")
    _copy_tree(ROOT / "client" / "scripts", out_root / "client" / "scripts", ignore=_ignore_pycache)
    _copy_tree(ROOT / "client" / "resources", out_root / "client" / "resources")

    out_bin = out_root / "build_x64" / "bin" / "Release"
    out_bin.mkdir(parents=True)
    print(f"[拷贝] {BIN} → build_x64/bin/Release")

    for name in REQUIRED_BIN:
        _copy_file(BIN / name, out_bin / name)

    for src in _expand_globs(BIN, OPTIONAL_BIN_GLOBS):
        if src.name in SKIP_BIN_NAMES:
            continue
        _copy_file(src, out_bin / src.name)

    if with_cuda_ort:
        for src in _expand_globs(BIN, CUDA_ORT_GLOBS):
            print(f"  + CUDA ORT {src.name}")
            _copy_file(src, out_bin / src.name)
    else:
        print("  （跳过 onnxruntime_providers_cuda/tensorrt，可用 --with-cuda-ort）")

    bin_res = BIN / "resources"
    if bin_res.is_dir():
        _copy_tree(bin_res, out_bin / "resources")

    # exiftool：只放 third_party 一份（Release 里常有完整 files，体积大）
    # FFmpeg：只保留 build_x64/bin/Release（media_bridge 会找），避免 third_party 再拷一份 DLL
    print("[拷贝] third_party 运行时（去重，避免 FFmpeg/工具双份）")
    tp = out_root / "third_party"

    ytdlp_src = ROOT / "third_party" / "yt-dlp" / "yt-dlp.exe"
    if ytdlp_src.is_file():
        _copy_file(ytdlp_src, tp / "yt-dlp" / "yt-dlp.exe")
    elif (out_bin / "yt-dlp.exe").is_file():
        _copy_file(out_bin / "yt-dlp.exe", tp / "yt-dlp" / "yt-dlp.exe")
    # Release 里若已有 yt-dlp，删掉重复以省体积
    dup = out_bin / "yt-dlp.exe"
    if dup.is_file() and (tp / "yt-dlp" / "yt-dlp.exe").is_file():
        try:
            dup.unlink()
        except OSError:
            pass

    et_src = ROOT / "third_party" / "exiftool"
    if (et_src / "exiftool.exe").is_file():
        _copy_file(et_src / "exiftool.exe", tp / "exiftool" / "exiftool.exe")
        if (et_src / "exiftool_files").is_dir():
            _copy_tree(et_src / "exiftool_files", tp / "exiftool" / "exiftool_files")
    elif (out_bin / "exiftool.exe").is_file():
        _copy_file(out_bin / "exiftool.exe", tp / "exiftool" / "exiftool.exe")
        if (out_bin / "exiftool_files").is_dir():
            _copy_tree(out_bin / "exiftool_files", tp / "exiftool" / "exiftool_files")
    # 去掉 Release 里重复的 exiftool（third_party 优先被查找）
    for name in ("exiftool.exe",):
        p = out_bin / name
        if p.is_file() and (tp / "exiftool" / name).is_file():
            try:
                p.unlink()
            except OSError:
                pass
    if (out_bin / "exiftool_files").is_dir() and (tp / "exiftool" / "exiftool_files").is_dir():
        shutil.rmtree(out_bin / "exiftool_files", ignore_errors=True)

    # 不需要 ffplay
    for name in ("ffplay.exe",):
        p = out_bin / name
        if p.is_file():
            try:
                p.unlink()
            except OSError:
                pass

    if with_scenedetect:
        sd = ROOT / "third_party" / "PySceneDetect"
        if (sd / "scenedetect" / "__init__.py").is_file():
            print("[拷贝] third_party/PySceneDetect（不含 packaging 安装包）")
            _copy_tree(sd, tp / "PySceneDetect", ignore=_ignore_scenedetect)
        else:
            print("[警告] 未找到 PySceneDetect，跳过")

    models_dst = out_root / "models"
    models_dst.mkdir(parents=True, exist_ok=True)
    readme_models = ROOT / "models" / "README.md"
    if readme_models.is_file():
        _copy_file(readme_models, models_dst / "README.md")

    if with_models:
        print("[拷贝] models（ONNX 等）")
        for name in ("lama.onnx", "realesr-general-x4v3.onnx", "game_event.onnx"):
            src = ROOT / "models" / name
            if src.is_file():
                print(f"  + {name} ({src.stat().st_size / 1e6:.1f} MB)")
                _copy_file(src, models_dst / name)
        if with_llm:
            for src in sorted((ROOT / "models").glob("*.gguf")):
                print(f"  + LLM {src.name}")
                _copy_file(src, models_dst / src.name)
            for src in sorted((ROOT / "models").glob("ggml-*.bin")):
                print(f"  + {src.name}")
                _copy_file(src, models_dst / src.name)
            vosk = ROOT / "models" / "vosk-model-small-cn-0.22"
            if vosk.is_dir():
                _copy_tree(vosk, models_dst / "vosk-model-small-cn-0.22")
    else:
        print("[跳过] models")

    for name in ("test_video.mp4", "222222.mp4"):
        src = ROOT / "tests" / name
        if src.is_file():
            print(f"[拷贝] tests/{name}")
            _copy_file(src, out_root / "tests" / name)
            break

    if embed_python:
        py = _embed_python_runtime(out_root, with_scenedetect=with_scenedetect)
        if with_scenedetect:
            _remove_shipped_scenedetect_sources(out_root)
        if not ship_source:
            _strip_python_sources(out_root, py_exe=py)
        else:
            print("[警告] --ship-source：分发包将包含可读 .py（仅调试用）", flush=True)
    else:
        print("[跳过] 内嵌 Python（--no-embed-python）；对方需自备 Python）")
        if not ship_source:
            print("[警告] 无内嵌 Python 时无法用同版本编译 .pyc，将保留 .py", flush=True)

    _write_launcher(out_root, embed_python=embed_python)
    _write_readme(
        out_root,
        with_cuda_ort=with_cuda_ort,
        with_models=with_models,
        embed_python=embed_python,
        ship_source=ship_source,
    )

    total = 0
    for dirpath, _dns, fns in os.walk(out_root):
        for fn in fns:
            try:
                total += (Path(dirpath) / fn).stat().st_size
            except OSError:
                pass
    print(f"\n[完成] 目录: {out_root}")
    print(f"[完成] 约 {total / (1024 ** 3):.2f} GB（{total / (1024 ** 2):.0f} MB）")

    zip_path = None
    if make_zip:
        zip_path = out_root.with_suffix(".zip")
        if zip_path.exists():
            zip_path.unlink()
        print(f"[压缩] {zip_path.name} …")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for dirpath, _dns, fns in os.walk(out_root):
                for fn in fns:
                    fp = Path(dirpath) / fn
                    arc = fp.relative_to(out_root.parent)
                    zf.write(fp, arc.as_posix())
        print(f"[完成] zip {zip_path.stat().st_size / (1024 ** 2):.0f} MB → {zip_path}")

    return zip_path or out_root


def main() -> int:
    ap = argparse.ArgumentParser(
        description="打包 MusicEditing 便携分发目录（默认内嵌 Python，对方不用装）",
    )
    ap.add_argument("--out", type=Path, default=None, help="输出目录")
    ap.add_argument("--zip", action="store_true", help="额外打成 zip")
    ap.add_argument("--skip-models", action="store_true", help="不拷贝 models")
    ap.add_argument("--with-cuda-ort", action="store_true", help="包含 CUDA ORT EP")
    ap.add_argument("--no-scenedetect", action="store_true", help="不带 PySceneDetect")
    ap.add_argument("--with-llm", action="store_true", help="额外拷贝 .gguf / vosk")
    ap.add_argument(
        "--no-embed-python",
        action="store_true",
        help="不内嵌 Python（旧行为：对方需自备 Python，不推荐）",
    )
    ap.add_argument(
        "--ship-source",
        action="store_true",
        help="保留可读 .py 源码（默认删除，仅调试包使用）",
    )
    args = ap.parse_args()

    stamp = _dt.datetime.now().strftime("%Y%m%d")
    out = args.out or (ROOT / "dist" / f"MusicEditing_Portable_{stamp}")
    if not out.is_absolute():
        out = (ROOT / out).resolve()

    pack(
        out,
        with_models=not args.skip_models,
        with_cuda_ort=args.with_cuda_ort,
        with_scenedetect=not args.no_scenedetect,
        with_llm=args.with_llm,
        make_zip=args.zip,
        embed_python=not args.no_embed_python,
        ship_source=args.ship_source,
    )
    print(
        "\n发给别人: 整个文件夹或 .zip；"
        "对方解压后双击 MusicEditing.exe"
        + ("（无需安装 Python）" if not args.no_embed_python else ""),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
