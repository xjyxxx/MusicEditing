# 第三方组件许可证说明

本项目的**原创代码**版权归 xjyxxx 所有（见根目录 LICENSE，保留所有权利）。

`third_party/` 中的预编译库与源码属于第三方，分发与使用时须遵守其各自许可证：

| 组件 | 路径 | 许可证 | 说明 |
|------|------|--------|------|
| FFmpeg | `third_party/ffmpeg/` | LGPL 2.1+（shared 构建） | 动态链接；若修改 FFmpeg 源码须公开修改部分 |
| OpenCV | `third_party/opencv/` | Apache 2.0 | 保留 NOTICE 与许可证声明 |
| llama.cpp | `third_party/llama_prebuilt/`、`third_party/llama.cpp/` | MIT | 保留版权声明 |
| PySide6 / vosk 等 | Python 依赖 | 各自 PyPI 许可证 | 运行时通过 pip 安装 |

若你仅使用本仓库中的**自研部分**，仍须遵守上述第三方条款。
若需闭源商用整个产品，请单独评估 FFmpeg LGPL 等合规要求。
