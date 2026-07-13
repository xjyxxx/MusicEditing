# 由 third_party/CMakeLists.txt 在设置 MUSIC_FFMPEG_ROOT 后 include
# 目录结构: include/  lib/*.lib  bin/*.dll

if(NOT MUSIC_FFMPEG_ROOT OR NOT EXISTS "${MUSIC_FFMPEG_ROOT}/lib/avcodec.lib")
    message(FATAL_ERROR
        "FFmpeg 未就绪: ${MUSIC_FFMPEG_ROOT}\n"
        "  Win32 → third_party/ffmpeg/x86\n"
        "  x64   → third_party/ffmpeg/x64（运行 scripts\\setup_ffmpeg_x64.bat）")
endif()

set(FFMPEG_ROOT ${MUSIC_FFMPEG_ROOT})
set(FFMPEG_INCLUDE_DIR ${FFMPEG_ROOT}/include)
set(FFMPEG_LIB_DIR     ${FFMPEG_ROOT}/lib)
set(FFMPEG_BIN_DIR     ${FFMPEG_ROOT}/bin)

set(_FFMPEG_CANDIDATES avcodec avformat avutil avdevice avfilter swresample swscale postproc)
set(FFMPEG_LIBRARIES)
foreach(_lib ${_FFMPEG_CANDIDATES})
    if(EXISTS "${FFMPEG_LIB_DIR}/${_lib}.lib")
        list(APPEND FFMPEG_LIBRARIES ${_lib})
    endif()
endforeach()
if(NOT FFMPEG_LIBRARIES)
    message(FATAL_ERROR "FFmpeg lib 目录无可用 .lib: ${FFMPEG_LIB_DIR}")
endif()

add_library(ffmpeg INTERFACE)
target_include_directories(ffmpeg INTERFACE ${FFMPEG_INCLUDE_DIR})
target_link_directories(ffmpeg INTERFACE ${FFMPEG_LIB_DIR})
target_link_libraries(ffmpeg INTERFACE ${FFMPEG_LIBRARIES})

if(WIN32)
    target_compile_definitions(ffmpeg INTERFACE __STDC_CONSTANT_MACROS)
endif()

if(EXISTS "${FFMPEG_INCLUDE_DIR}/libavutil/hwcontext.h")
    # FFmpeg 4.x+ Windows 构建内部 UTF-8→UTF-16，路径应保持 UTF-8
    target_compile_definitions(ffmpeg INTERFACE MUSIC_FFMPEG_UTF8_PATH=1)
endif()

set(FFMPEG_INCLUDE_DIR ${FFMPEG_INCLUDE_DIR} PARENT_SCOPE)
set(FFMPEG_LIB_DIR     ${FFMPEG_LIB_DIR}     PARENT_SCOPE)
set(FFMPEG_BIN_DIR     ${FFMPEG_BIN_DIR}     PARENT_SCOPE)

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(_MUSIC_ARCH_BITS "64")
else()
    set(_MUSIC_ARCH_BITS "32")
endif()

if(EXISTS "${FFMPEG_INCLUDE_DIR}/libavutil/hwcontext.h")
    set(MUSIC_FFMPEG_HWACCEL ON PARENT_SCOPE)
    message(STATUS "FFmpeg hwaccel: D3D11VA headers found")
else()
    set(MUSIC_FFMPEG_HWACCEL OFF PARENT_SCOPE)
endif()

message(STATUS "FFmpeg root: ${FFMPEG_ROOT} (${_MUSIC_ARCH_BITS}-bit)")
