# OpenCV 集成：优先使用 third_party/opencv/{x64|x86} 本地预编译包
option(MUSIC_ENABLE_OPENCV "Enable OpenCV frame processing" ON)

if(NOT MUSIC_ENABLE_OPENCV)
    set(MUSIC_HAS_OPENCV OFF PARENT_SCOPE)
    return()
endif()

if(CMAKE_SIZEOF_VOID_P EQUAL 4)
    set(_OCV_ARCH "x86")
else()
    set(_OCV_ARCH "x64")
endif()

set(_OCV_LOCAL "${CMAKE_CURRENT_SOURCE_DIR}/${_OCV_ARCH}")
set(_OCV_LIB "${_OCV_LOCAL}/lib/opencv_world4120.lib")
set(_OCV_DLL "${_OCV_LOCAL}/bin/opencv_world4120.dll")
set(_OCV_INC "${_OCV_LOCAL}/include/opencv2/opencv.hpp")

# --- 方式 1：仓库内置预编译包（推荐，便于打包分发）---
if(EXISTS "${_OCV_LIB}" AND EXISTS "${_OCV_INC}")
    add_library(music_opencv INTERFACE)
    target_include_directories(music_opencv INTERFACE "${_OCV_LOCAL}/include")
    target_link_libraries(music_opencv INTERFACE "${_OCV_LIB}")
    target_compile_definitions(music_opencv INTERFACE MUSIC_HAS_OPENCV=1)

    set(MUSIC_HAS_OPENCV ON PARENT_SCOPE)
    set(MUSIC_OPENCV_DLL_DIR "${_OCV_LOCAL}/bin" PARENT_SCOPE)
    message(STATUS "OpenCV local prebuilt (${_OCV_ARCH}): ${_OCV_LOCAL}")
    return()
endif()

# --- 方式 2：回退到外部 OPENCV_DIR（开发机 D:/APP/opencv/...）---
if(NOT OPENCV_DIR)
    if(CMAKE_SIZEOF_VOID_P EQUAL 4)
        set(OPENCV_DIR "D:/APP/opencv/build_x86" CACHE PATH "OpenCV CMake 目录 (Win32)")
    else()
        set(OPENCV_DIR "D:/APP/opencv/build" CACHE PATH "OpenCV CMake 目录 (x64)")
    endif()
endif()

if(NOT EXISTS "${OPENCV_DIR}/OpenCVConfig.cmake")
    message(STATUS "OpenCV 未找到: ${_OCV_LOCAL}")
    message(STATUS "  请运行: scripts\\import_opencv.bat ${_OCV_ARCH}")
    set(MUSIC_HAS_OPENCV OFF PARENT_SCOPE)
    return()
endif()

set(OpenCV_DIR "${OPENCV_DIR}" CACHE PATH "" FORCE)
find_package(OpenCV QUIET)
if(NOT OpenCV_FOUND)
    find_package(OpenCV QUIET COMPONENTS core imgproc)
endif()
if(NOT OpenCV_FOUND)
    message(STATUS "OpenCV find_package 失败 (${OPENCV_DIR})")
    set(MUSIC_HAS_OPENCV OFF PARENT_SCOPE)
    return()
endif()

if(CMAKE_SIZEOF_VOID_P EQUAL 4)
    set(_OPENCV_LIB_CANDIDATES
        "${OPENCV_DIR}/x86/vc16/lib"
        "${OPENCV_DIR}/lib/Release"
        "${OPENCV_DIR}/lib")
    set(_OPENCV_BIN_CANDIDATES
        "${OPENCV_DIR}/x86/vc16/bin"
        "${OPENCV_DIR}/bin/Release"
        "${OPENCV_DIR}/bin")
else()
    set(_OPENCV_LIB_CANDIDATES
        "${OPENCV_DIR}/x64/vc16/lib"
        "${OPENCV_DIR}/lib/Release"
        "${OPENCV_DIR}/lib")
    set(_OPENCV_BIN_CANDIDATES
        "${OPENCV_DIR}/x64/vc16/bin"
        "${OPENCV_DIR}/bin/Release"
        "${OPENCV_DIR}/bin")
endif()

set(_OPENCV_LIB_DIR "")
foreach(_d ${_OPENCV_LIB_CANDIDATES})
    if(EXISTS "${_d}/opencv_world4120.lib")
        set(_OPENCV_LIB_DIR "${_d}")
        break()
    endif()
endforeach()

set(_OPENCV_BIN_DIR "")
foreach(_d ${_OPENCV_BIN_CANDIDATES})
    if(EXISTS "${_d}/opencv_world4120.dll")
        set(_OPENCV_BIN_DIR "${_d}")
        break()
    endif()
endforeach()

if(NOT _OPENCV_LIB_DIR)
    message(STATUS "OpenCV 架构不匹配: 在 ${OPENCV_DIR} 下未找到 opencv_world4120.lib")
    set(MUSIC_HAS_OPENCV OFF PARENT_SCOPE)
    return()
endif()

add_library(music_opencv INTERFACE)
target_include_directories(music_opencv INTERFACE ${OpenCV_INCLUDE_DIRS})
target_link_libraries(music_opencv INTERFACE ${OpenCV_LIBS})
target_compile_definitions(music_opencv INTERFACE MUSIC_HAS_OPENCV=1)

set(MUSIC_HAS_OPENCV ON PARENT_SCOPE)
if(_OPENCV_BIN_DIR)
    set(MUSIC_OPENCV_DLL_DIR "${_OPENCV_BIN_DIR}" PARENT_SCOPE)
else()
    set(MUSIC_OPENCV_DLL_DIR "${_OPENCV_LIB_DIR}" PARENT_SCOPE)
endif()
message(STATUS "OpenCV ${OpenCV_VERSION} external (${_OCV_ARCH}, ${OPENCV_DIR})")
