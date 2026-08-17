#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外发专用打包入口：强制 zip + 内嵌 Python + 严格无业务源码。

禁止 --ship-source。对方解压后双击 MusicEditing.exe 即可。

用法（仓库根）:
  python scripts/pack_for_share.py
  python scripts/pack_for_share.py --profile slim
  .\\scripts\\pack_for_share.bat

说明见 docs/design/distribution.md「代码安全」。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pack_portable import PACK_PROFILES, _die, pack  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="外发打包：zip + 内嵌 Python + 严格删除业务 .py（禁止带源码）",
    )
    ap.add_argument("--out", type=Path, default=None, help="输出目录")
    ap.add_argument(
        "--profile",
        choices=sorted(PACK_PROFILES.keys()),
        default="standard",
        help="slim=演示 / standard=默认可卖 / full=含 LLM+vosk",
    )
    ap.add_argument("--skip-models", action="store_true", help="不拷贝 models（省 ~200MB）")
    ap.add_argument(
        "--with-models",
        action="store_true",
        help="强制带上 ONNX models（覆盖默认瘦包）",
    )
    ap.add_argument("--with-tests", action="store_true", help="打包测试视频（默认不带）")
    ap.add_argument("--with-cuda-ort", action="store_true", help="包含 CUDA ORT EP")
    ap.add_argument("--no-scenedetect", action="store_true", help="不带 PySceneDetect")
    ap.add_argument("--with-llm", action="store_true", help="额外拷贝 .gguf / vosk")
    ap.add_argument("--sign", action="store_true", help="尝试签名 MusicEditing.exe")
    ap.add_argument(
        "--with-iphoto-extras",
        action="store_true",
        help="安装 requirements-iphoto（HEIC 等）",
    )
    ap.add_argument(
        "--with-maps",
        action="store_true",
        help="拷贝 maps/font（体积大）",
    )
    # 明确拒绝危险开关（若用户从别处抄命令带上）
    ap.add_argument("--ship-source", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-embed-python", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.ship_source:
        _die("外发包禁止 --ship-source（会泄露可读源码）。请用本脚本默认行为。")
    if args.no_embed_python:
        _die("外发包必须内嵌 Python（不可 --no-embed-python）。")

    prof = dict(PACK_PROFILES[args.profile])
    # 外发默认瘦包：不带 ONNX models（~200MB）；需要去水印/超分时加 --with-models
    # --skip-models 保留兼容（与默认相同）；--with-models 才强制带上
    with_models = bool(args.with_models) and not args.skip_models
    with_scenedetect = bool(prof["with_scenedetect"]) and not args.no_scenedetect
    with_llm = bool(prof["with_llm"]) or args.with_llm
    with_cuda_ort = bool(prof["with_cuda_ort"]) or args.with_cuda_ort

    stamp = _dt.datetime.now().strftime("%Y%m%d")
    suffix = "" if args.profile == "standard" else f"_{args.profile}"
    out = args.out or (ROOT / "dist" / f"MusicEditing_Share_{stamp}{suffix}")
    if not out.is_absolute():
        out = (ROOT / out).resolve()

    print("=== 外发打包（强制：zip + 内嵌 Python + 严格无业务 .py）===", flush=True)
    print(
        f"  models={'是' if with_models else '否（默认瘦包，加 --with-models 可开）'}  "
        f"tests={'是' if args.with_tests else '否'}",
        flush=True,
    )
    result = pack(
        out,
        with_models=with_models,
        with_cuda_ort=with_cuda_ort,
        with_scenedetect=with_scenedetect,
        with_llm=with_llm,
        make_zip=True,
        embed_python=True,
        ship_source=False,
        do_sign=args.sign,
        profile=args.profile,
        strict_no_source=True,
        with_iphoto_extras=args.with_iphoto_extras,
        with_maps=args.with_maps,
        skip_tests=not args.with_tests,
    )
    print("\n可以发给别人的文件:", flush=True)
    print(f"  {result}", flush=True)
    print("对方：解压 → 双击 MusicEditing.exe（无需装 Python）", flush=True)
    print(
        "注意：.pyc 可提高阅读门槛，但仍可被专业反编译；"
        "更强保护见 docs/design/distribution.md",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
