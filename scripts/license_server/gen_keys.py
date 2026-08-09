#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""签发正式版卡密，写入 keys.json。

用法:
  python scripts/license_server/gen_keys.py --count 5
  python scripts/license_server/gen_keys.py --count 1 --note "给测试用户A"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from server import KEYS_PATH, issue_key, normalize_key


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    if args.count < 1 or args.count > 1000:
        print("count 范围 1..1000")
        return 1

    data = {}
    if KEYS_PATH.is_file():
        try:
            data = json.loads(KEYS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}

    issued = []
    for i in range(args.count):
        k = issue_key()
        data[normalize_key(k)] = {
            "active": True,
            "allow_rebind": True,
            "note": args.note or f"issued-{i+1}",
        }
        issued.append(k)

    KEYS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {KEYS_PATH}（共 {len(data)} 条）")
    print("—— 请妥善保存并发送给用户 ——")
    for k in issued:
        print(k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
