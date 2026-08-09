"""生成轻量 game_event.onnx 占位（顶栏「事件感」打分，便于打通 ORT 路径）。

用法（仓库根）:
  python scripts/make_game_event_stub_onnx.py

依赖：pip install onnx numpy
说明：这是可运行的 stub，不是商业击杀检测器；换真实模型时覆盖 models/game_event.onnx 即可。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "models" / "game_event.onnx"


def main() -> int:
    try:
        import numpy as np
        import onnx
        from onnx import TensorProto, helper, numpy_helper
    except ImportError:
        print("需要: pip install onnx numpy")
        return 2

    # 极简图：ReduceMean over HWC → 1 个标量（高亮区域平均亮度作「事件感」）
    # 输入 NCHW float32 [1,3,64,64]
    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 64, 64])
    y = helper.make_tensor_value_info("score", TensorProto.FLOAT, [1, 1])

    # ReduceMean axes=[2,3] → [1,3,1,1] then Mean → [1,1] via ReduceMean axes=[1]
    node1 = helper.make_node(
        "ReduceMean", inputs=["input"], outputs=["m1"], axes=[2, 3], keepdims=1,
    )
    node2 = helper.make_node(
        "ReduceMean", inputs=["m1"], outputs=["score"], axes=[1], keepdims=1,
    )
    graph = helper.make_graph([node1, node2], "game_event_stub", [x], [y])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(OUT))
    print(f"OK → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
