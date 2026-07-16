# GLEW / OpenGL 扩展加载器：third_party/opengl/{x64|x86}
option(MUSIC_ENABLE_GLEW "Enable GLEW (OpenGL extension loader)" ON)

if(NOT MUSIC_ENABLE_GLEW)
    set(MUSIC_HAS_GLEW OFF PARENT_SCOPE)
    return()
endif()

if(CMAKE_SIZEOF_VOID_P EQUAL 4)
    set(_GLEW_ARCH "x86")
else()
    set(_GLEW_ARCH "x64")
endif()

set(_GLEW_LOCAL "${CMAKE_CURRENT_SOURCE_DIR}/${_GLEW_ARCH}")
set(_GLEW_LIB "${_GLEW_LOCAL}/lib/glew32.lib")
set(_GLEW_DLL "${_GLEW_LOCAL}/bin/glew32.dll")
set(_GLEW_INC "${_GLEW_LOCAL}/include/GL/glew.h")

if(EXISTS "${_GLEW_LIB}" AND EXISTS "${_GLEW_INC}" AND EXISTS "${_GLEW_DLL}")
    add_library(music_glew INTERFACE)
    target_include_directories(music_glew INTERFACE "${_GLEW_LOCAL}/include")
    # glew32.lib = 动态库导入库；运行时需要 glew32.dll
    # opengl32 = Windows 系统 OpenGL（驱动实现）
    target_link_libraries(music_glew INTERFACE
        "${_GLEW_LIB}"
        opengl32
    )
    target_compile_definitions(music_glew INTERFACE
        MUSIC_HAS_GLEW=1
        GLEW_NO_GLU
    )

    set(MUSIC_HAS_GLEW ON PARENT_SCOPE)
    set(MUSIC_GLEW_DLL_DIR "${_GLEW_LOCAL}/bin" PARENT_SCOPE)
    message(STATUS "GLEW local prebuilt (${_GLEW_ARCH}): ${_GLEW_LOCAL}")
else()
    set(MUSIC_HAS_GLEW OFF PARENT_SCOPE)
    message(STATUS "GLEW 未找到: ${_GLEW_LOCAL}")
    message(STATUS "  需要 include/GL/glew.h、lib/glew32.lib、bin/glew32.dll")
endif()
