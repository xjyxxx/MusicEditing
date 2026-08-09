# llama.cpp 源码目录

## 三种用法

| 模式 | 何时 | CMake |
|------|------|------|
| **CPU prebuilt** | 默认；无 Vulkan/CUDA | `third_party/llama_prebuilt/` |
| **源码 + Vulkan（推荐）** | 要 GPU、**不想下数 GB CUDA Toolkit** | `-DMUSIC_GGML_VULKAN=ON` |
| **源码 + CUDA** | 已有 Toolkit | `-DMUSIC_GGML_CUDA=ON` |

## 切到 GPU（推荐 Vulkan）

```bat
rem 1) 安装 Vulkan SDK（远小于 CUDA Toolkit）
python scripts\setup_llama_gpu.py install-vulkan

rem 2) 重开终端后编译
python scripts\setup_llama_gpu.py vulkan
```

检测：

```bat
python scripts\setup_llama_gpu.py
```

若坚持 CUDA（体积大）：

```bat
python scripts\setup_llama_gpu.py install-cuda
python scripts\setup_llama_gpu.py cuda
```

`build_x64.bat`：有 `nvcc` 走 CUDA；否则有 Vulkan SDK 走 Vulkan；都没有则 prebuilt CPU。

运行时：个人中心打开 GPU → `MUSIC_LLM_N_GPU_LAYERS=-1`；配置 `llm_model_path=` 指向 `.gguf`。

## 仅打 CPU 预编译包

```bat
scripts\build_llama_lib.bat
```

## 恢复源码

```bat
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git third_party\llama.cpp
```
