# OpenGL / GLEW（项目内预编译）

本目录存放 **GLEW 2.3.1** 预编译包（从本机 `glew-2.3.1` 复制进仓库，不依赖外部路径）。

系统 OpenGL 实现仍由显卡驱动提供（链接 `opengl32.lib`），**无需**再下载 OpenGL 本体。

```
third_party/opengl/
├── VERSION.txt
├── LICENSE.txt
├── CMakeLists.txt
├── x64/
│   ├── include/GL/   glew.h, wglew.h, ...
│   ├── lib/          glew32.lib（动态导入库）、glew32s.lib（静态，可选）
│   └── bin/          glew32.dll
└── x86/              同上（Win32）
```

## CMake

检测到 `x64/lib/glew32.lib` 后定义：

- 目标：`music_glew`
- 宏：`MUSIC_HAS_GLEW=1`
- 变量：`MUSIC_GLEW_DLL_DIR`（构建后自动拷贝 `glew32.dll`）

- C++：`media_player` 链接本库  
- UI：`client/scripts/ui/gl_video_widget.py` 用 **Qt QOpenGLWidget** 实际绘制视频帧（不依赖 Python 绑定 GLEW）

## 使用注意

C++ 中应在创建 OpenGL 上下文之后：

```cpp
#include <GL/glew.h>
// ... 创建上下文 ...
glewExperimental = GL_TRUE;
if (glewInit() != GLEW_OK) { /* 失败 */ }
```

若改用静态库 `glew32s.lib`，需在编译定义中加 `GLEW_STATIC`，且不必拷贝 dll。
