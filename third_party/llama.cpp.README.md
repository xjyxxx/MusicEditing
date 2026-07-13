# llama.cpp 源码目录

源码已打包为 **`third_party/llama_prebuilt/`**（仅 include / lib / bin）时，本目录可删除。

## 生成预编译包

```bat
scripts\build_llama_lib.bat
```

默认会：编译 → 输出到 `llama_prebuilt` → 删除 `build` 与本目录源码。

保留源码仅打包：

```bat
scripts\build_llama_lib.bat off keep-src
```

## 恢复源码

从 git 历史恢复 `third_party/llama.cpp`，或：

```bat
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git third_party\llama.cpp
```

（恢复后需删除嵌套 `.git` 再随主仓库提交，或使用 submodule。）
