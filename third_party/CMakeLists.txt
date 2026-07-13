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

# llama.cpp：优先使用预编译包 llama_prebuilt，否则从源码 add_subdirectory
option(MUSIC_ENABLE_LLAMA "Build llama.cpp inference library" ON)

set(LLAMA_PREBUILT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/llama_prebuilt")

if(MUSIC_ENABLE_LLAMA AND EXISTS "${LLAMA_PREBUILT_DIR}/lib/llama.lib")
    add_library(music_llama INTERFACE)
    target_include_directories(music_llama INTERFACE "${LLAMA_PREBUILT_DIR}/include")
    target_link_libraries(music_llama INTERFACE
        "${LLAMA_PREBUILT_DIR}/lib/llama.lib"
        "${LLAMA_PREBUILT_DIR}/lib/ggml.lib"
        "${LLAMA_PREBUILT_DIR}/lib/ggml-cpu.lib"
        "${LLAMA_PREBUILT_DIR}/lib/ggml-base.lib"
    )
    set(MUSIC_HAS_LLAMA ON PARENT_SCOPE)
    message(STATUS "llama prebuilt: ${LLAMA_PREBUILT_DIR}")

elseif(MUSIC_ENABLE_LLAMA AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/llama.cpp/CMakeLists.txt")
    set(BUILD_SHARED_LIBS OFF CACHE BOOL "Build llama.cpp as static lib" FORCE)
    set(LLAMA_BUILD_COMMON OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_SERVER OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_APP OFF CACHE BOOL "" FORCE)
    set(LLAMA_BUILD_UI OFF CACHE BOOL "" FORCE)
    set(LLAMA_OPENSSL OFF CACHE BOOL "" FORCE)

    add_subdirectory(llama.cpp)

    # 对外暴露 INTERFACE 目标，便于 client/server 链接
    if(TARGET llama)
        add_library(music_llama INTERFACE)
        target_link_libraries(music_llama INTERFACE llama)
        target_include_directories(music_llama INTERFACE
            ${CMAKE_CURRENT_SOURCE_DIR}/llama.cpp/include
        )
        set(MUSIC_HAS_LLAMA ON PARENT_SCOPE)
        message(STATUS "llama.cpp integrated (target: llama, alias: music_llama)")
    endif()
else()
    set(MUSIC_HAS_LLAMA OFF PARENT_SCOPE)
    if(MUSIC_ENABLE_LLAMA)
        message(STATUS "llama.cpp not found at third_party/llama.cpp, LLM inference disabled")
    else()
        message(STATUS "llama.cpp disabled by MUSIC_ENABLE_LLAMA=OFF")
    endif()
endif()
