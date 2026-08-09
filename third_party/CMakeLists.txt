# 第三方依赖

# --- FFmpeg：按目标架构选择 third_party/ffmpeg/{x86|x64} ---
if(CMAKE_SIZEOF_VOID_P EQUAL 4)
    set(_FFMPEG_ARCH "x86")
else()
    set(_FFMPEG_ARCH "x64")
endif()

set(_FFMPEG_LOCAL "${CMAKE_SOURCE_DIR}/third_party/ffmpeg/${_FFMPEG_ARCH}")

if(EXISTS "${_FFMPEG_LOCAL}/lib/avcodec.lib")
    set(MUSIC_FFMPEG_ROOT "${_FFMPEG_LOCAL}")
elseif(CMAKE_SIZEOF_VOID_P EQUAL 4)
    if(EXISTS "${CMAKE_SOURCE_DIR}/third_party/ffmpeg_win32/lib/avcodec.lib")
        set(MUSIC_FFMPEG_ROOT "${CMAKE_SOURCE_DIR}/third_party/ffmpeg_win32")
    elseif(EXISTS "${CMAKE_SOURCE_DIR}/third_party/ffmpeg/lib/avcodec.lib")
        set(MUSIC_FFMPEG_ROOT "${CMAKE_SOURCE_DIR}/third_party/ffmpeg")
    else()
        set(MUSIC_FFMPEG_ROOT "${_FFMPEG_LOCAL}")
    endif()
elseif(EXISTS "${CMAKE_SOURCE_DIR}/third_party/ffmpeg_x64/lib/avcodec.lib")
    set(MUSIC_FFMPEG_ROOT "${CMAKE_SOURCE_DIR}/third_party/ffmpeg_x64")
else()
    set(MUSIC_FFMPEG_ROOT "${_FFMPEG_LOCAL}")
endif()

include(${CMAKE_CURRENT_SOURCE_DIR}/ffmpeg.cmake)

add_subdirectory(opencv)
add_subdirectory(onnxruntime)
add_subdirectory(opengl)

# 向根项目暴露第三方开关（供 client/ 使用）
if(MUSIC_HAS_OPENCV)
    set(MUSIC_HAS_OPENCV ON PARENT_SCOPE)
    set(MUSIC_OPENCV_DLL_DIR "${MUSIC_OPENCV_DLL_DIR}" PARENT_SCOPE)
endif()
if(MUSIC_HAS_ONNXRUNTIME)
    set(MUSIC_HAS_ONNXRUNTIME ON PARENT_SCOPE)
    set(MUSIC_ONNXRUNTIME_DLL_DIR "${MUSIC_ONNXRUNTIME_DLL_DIR}" PARENT_SCOPE)
endif()
if(MUSIC_HAS_GLEW)
    set(MUSIC_HAS_GLEW ON PARENT_SCOPE)
    set(MUSIC_GLEW_DLL_DIR "${MUSIC_GLEW_DLL_DIR}" PARENT_SCOPE)
endif()

# llama.cpp：默认优先 prebuilt；CUDA/Vulkan/FROM_SOURCE 时强制源码
option(MUSIC_ENABLE_LLAMA "Build llama.cpp inference library" ON)
option(MUSIC_LLAMA_FROM_SOURCE "Prefer third_party/llama.cpp over llama_prebuilt" OFF)
option(MUSIC_GGML_CUDA "Enable CUDA backend for llama.cpp (implies FROM_SOURCE; needs Toolkit)" OFF)
option(MUSIC_GGML_VULKAN "Enable Vulkan backend for llama.cpp (implies FROM_SOURCE; no CUDA Toolkit)" OFF)

set(LLAMA_PREBUILT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/llama_prebuilt")
set(LLAMA_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/llama.cpp")

if(MUSIC_GGML_CUDA OR MUSIC_GGML_VULKAN)
    set(MUSIC_LLAMA_FROM_SOURCE ON)
endif()

set(_MUSIC_USE_LLAMA_PREBUILT OFF)
set(_MUSIC_USE_LLAMA_SOURCE OFF)

if(MUSIC_ENABLE_LLAMA AND MUSIC_LLAMA_FROM_SOURCE AND EXISTS "${LLAMA_SRC_DIR}/CMakeLists.txt")
    set(_MUSIC_USE_LLAMA_SOURCE ON)
elseif(MUSIC_ENABLE_LLAMA AND (NOT MUSIC_LLAMA_FROM_SOURCE)
       AND EXISTS "${LLAMA_PREBUILT_DIR}/lib/llama.lib")
    set(_MUSIC_USE_LLAMA_PREBUILT ON)
elseif(MUSIC_ENABLE_LLAMA AND EXISTS "${LLAMA_SRC_DIR}/CMakeLists.txt")
    set(_MUSIC_USE_LLAMA_SOURCE ON)
endif()

if(_MUSIC_USE_LLAMA_PREBUILT)
    add_library(music_llama INTERFACE)
    target_include_directories(music_llama INTERFACE "${LLAMA_PREBUILT_DIR}/include")
    target_link_libraries(music_llama INTERFACE
        "${LLAMA_PREBUILT_DIR}/lib/llama.lib"
        "${LLAMA_PREBUILT_DIR}/lib/ggml.lib"
        "${LLAMA_PREBUILT_DIR}/lib/ggml-cpu.lib"
        "${LLAMA_PREBUILT_DIR}/lib/ggml-base.lib"
    )
    set(MUSIC_HAS_LLAMA ON PARENT_SCOPE)
    set(MUSIC_LLAMA_CUDA OFF PARENT_SCOPE)
    set(MUSIC_LLAMA_VULKAN OFF PARENT_SCOPE)
    message(STATUS "llama prebuilt (CPU): ${LLAMA_PREBUILT_DIR}")
    message(STATUS "  tip: 免 Toolkit 用 Vulkan → scripts/setup_llama_gpu.py vulkan")
    message(STATUS "       或 CUDA Toolkit → scripts/setup_llama_gpu.py cuda")

elseif(_MUSIC_USE_LLAMA_SOURCE)
    set(BUILD_SHARED_LIBS OFF CACHE BOOL "Build llama.cpp as static lib" FORCE)
    set(LLAMA_BUILD_COMMON OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_APP OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_UI OFF CACHE BOOL "" FORCE)
    set(LLAMA_OPENSSL OFF CACHE BOOL "" FORCE)

    set(MUSIC_LLAMA_CUDA OFF PARENT_SCOPE)
    set(MUSIC_LLAMA_VULKAN OFF PARENT_SCOPE)

    if(MUSIC_GGML_CUDA)
        set(GGML_CUDA ON CACHE BOOL "ggml: use CUDA" FORCE)
        if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES OR "${CMAKE_CUDA_ARCHITECTURES}" STREQUAL "")
            set(CMAKE_CUDA_ARCHITECTURES "75;80;86;89" CACHE STRING "CUDA arches" FORCE)
        endif()
        message(STATUS "llama.cpp: GGML_CUDA=ON arches=${CMAKE_CUDA_ARCHITECTURES}")
        set(MUSIC_LLAMA_CUDA ON PARENT_SCOPE)
    elseif(MUSIC_GGML_VULKAN)
        set(GGML_VULKAN ON CACHE BOOL "ggml: use Vulkan" FORCE)
        message(STATUS "llama.cpp: GGML_VULKAN=ON (无需 CUDA Toolkit)")
        set(MUSIC_LLAMA_VULKAN ON PARENT_SCOPE)
    else()
        message(STATUS "llama.cpp: source build (CPU)")
    endif()

    add_subdirectory(llama.cpp)

    if(TARGET llama)
        add_library(music_llama INTERFACE)
        target_link_libraries(music_llama INTERFACE llama)
        target_include_directories(music_llama INTERFACE
            ${LLAMA_SRC_DIR}/include
        )
        set(MUSIC_HAS_LLAMA ON PARENT_SCOPE)
        message(STATUS "llama.cpp integrated (target: llama, alias: music_llama)")
    else()
        set(MUSIC_HAS_LLAMA OFF PARENT_SCOPE)
        set(MUSIC_LLAMA_CUDA OFF PARENT_SCOPE)
        set(MUSIC_LLAMA_VULKAN OFF PARENT_SCOPE)
        message(WARNING "llama.cpp subdirectory did not create target 'llama'")
    endif()
else()
    set(MUSIC_HAS_LLAMA OFF PARENT_SCOPE)
    set(MUSIC_LLAMA_CUDA OFF PARENT_SCOPE)
    set(MUSIC_LLAMA_VULKAN OFF PARENT_SCOPE)
    if(MUSIC_ENABLE_LLAMA)
        message(STATUS "llama.cpp not found (need llama_prebuilt or third_party/llama.cpp)")
    else()
        message(STATUS "llama.cpp disabled by MUSIC_ENABLE_LLAMA=OFF")
    endif()
endif()

