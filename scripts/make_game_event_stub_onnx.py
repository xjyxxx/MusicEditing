"""生成轻量 game_event.onnx（顶栏 ROI 亮度启发式，打通 ORT 路径）。

用法（仓库根）:
  python scripts/make_game_event_stub_onnx.py

依赖：pip install onnx numpy

重要：这是**可运行 stub**，突出顶栏高亮，不是商业「击杀检测」模型。
真模型请覆盖 models/game_event.onnx（输入建议 NCHW float [1,3,64,64]，输出标量 score）。
客户端推理会裁顶栏再送入模型（见 game_semantic._onnx_event_scores）。
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

    # 输入 NCHW [1,3,64,64]；对上半区域加权平均 → 更像 HUD/击杀播报区
    # score = mean(input * mask)  其中 mask 上半=1.5、下半=0.5（经常量实现）
    x = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, 64, 64])
    y = helper.make_tensor_value_info("score", TensorProto.FLOAT, [1, 1])

    # 垂直权重 [1,1,64,1]：上 28 行 1.6，其余 0.55
    weights = np.full((1, 1, 64, 1), 0.55, dtype=np.float32)
    weights[0, 0, :28, 0] = 1.6
    w_init = numpy_helper.from_array(weights, name="vweight")

    mul = helper.make_node("Mul", inputs=["input", "vweight"], outputs=["weighted"])
    # ReduceMean → [1,3,1,1] then → [1,1]
    r1 = helper.make_node(
        "ReduceMean", inputs=["weighted"], outputs=["m1"], axes=[2, 3], keepdims=1,
    )
    r2 = helper.make_node(
        "ReduceMean", inputs=["m1"], outputs=["score"], axes=[1], keepdims=1,
    )
    graph = helper.make_graph(
        [mul, r1, r2],
        "game_event_stub_v2",
        [x],
        [y],
        initializer=[w_init],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    onnx.checker.check_model(model)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(OUT))
    print(f"OK → {OUT} （stub v2：顶栏加权，非真击杀模型）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
