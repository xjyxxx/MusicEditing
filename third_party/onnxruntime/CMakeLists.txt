# ONNX Runtime 集成：优先使用 third_party/onnxruntime/{x64|x86} 本地预编译包
option(MUSIC_ENABLE_ONNXRUNTIME "Enable ONNX Runtime (LaMa watermark inpaint)" ON)

if(NOT MUSIC_ENABLE_ONNXRUNTIME)
    set(MUSIC_HAS_ONNXRUNTIME OFF PARENT_SCOPE)
    return()
endif()

if(CMAKE_SIZEOF_VOID_P EQUAL 4)
    set(_ORT_ARCH "x86")
else()
    set(_ORT_ARCH "x64")
endif()

set(_ORT_LOCAL "${CMAKE_CURRENT_SOURCE_DIR}/${_ORT_ARCH}")
set(_ORT_LIB "${_ORT_LOCAL}/lib/onnxruntime.lib")
set(_ORT_DLL "${_ORT_LOCAL}/bin/onnxruntime.dll")
set(_ORT_INC "${_ORT_LOCAL}/include/onnxruntime_cxx_api.h")

if(EXISTS "${_ORT_LIB}" AND EXISTS "${_ORT_INC}")
    add_library(music_onnxruntime INTERFACE)
    target_include_directories(music_onnxruntime INTERFACE "${_ORT_LOCAL}/include")
    target_link_libraries(music_onnxruntime INTERFACE "${_ORT_LIB}")
    target_compile_definitions(music_onnxruntime INTERFACE MUSIC_HAS_ONNXRUNTIME=1)

    set(MUSIC_HAS_ONNXRUNTIME ON PARENT_SCOPE)
    set(MUSIC_ONNXRUNTIME_DLL_DIR "${_ORT_LOCAL}/bin" PARENT_SCOPE)
    message(STATUS "ONNX Runtime local prebuilt (${_ORT_ARCH}): ${_ORT_LOCAL}")
    return()
endif()

message(STATUS "ONNX Runtime 未找到: ${_ORT_LOCAL}")
message(STATUS "  请运行: scripts\\setup_onnxruntime_x64.bat")
set(MUSIC_HAS_ONNXRUNTIME OFF PARENT_SCOPE)
