# PySceneDetect（仓库内第三方源码）

本目录已**随仓库附带** [PySceneDetect](https://www.scenedetect.com/) 源码（BSD-3-Clause），供「游戏高光」视觉场景切点使用。

上游：https://github.com/Breakthrough/PySceneDetect  
当前同步版本见 `pyproject.toml` / 包内版本号（约 0.7.x）。

## 别人拿到代码后怎么用

**方式 A（推荐，与 `run_ui_x64.bat` 一致）**

```bat
pip install -r client\scripts\requirements.txt
scripts\install_scenedetect.bat
```

`run_ui_x64.bat` / `run_ui.bat` 会用**绝对路径**自动：

```bat
pip install -e "%PROJECT_DIR%\third_party\PySceneDetect"
```

（不要在 requirements.txt 里写相对路径 `-e ../../...`，pip 按当前工作目录解析会失败。）

**方式 B：仅 editable 安装本目录**

```bat
scripts\install_scenedetect.bat
```

或：

```bat
pip install -e third_party\PySceneDetect
```

**方式 C：不 pip，运行时直接引用**

`client/scripts/core/scene_detect.py` 会在 import 失败时把本目录加入 `sys.path`（需本目录下存在 `scenedetect/` 包）。仍建议 pip 安装，依赖声明更清晰。

## 说明

- 这是 **Python 库**，不参与 CMake/`build_x64.bat` 编译；缺库时 UI 能启动，但「游戏高光」会回退时间轴规则。
- 另需已有依赖：`numpy`、`opencv-python-headless`（已在 `client/scripts/requirements.txt`）。
- 上游完整说明见同目录 `README.md`（官方原文）。
