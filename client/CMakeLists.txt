# 媒体处理引擎 - 客户端核心库
add_library(media_engine SHARED
    src/core/video_decoder.cpp
    src/core/media_engine.cpp
)

target_include_directories(media_engine
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE
        ${CMAKE_SOURCE_DIR}/shared/include
)

target_compile_definitions(media_engine PRIVATE MEDIA_SHARED_EXPORTS)

target_link_libraries(media_engine
    PUBLIC
        media_shared
        ffmpeg
)

target_sources(media_engine PRIVATE src/core/frame_processor.cpp)
if(MUSIC_HAS_OPENCV)
    target_link_libraries(media_engine PRIVATE music_opencv)
    target_compile_definitions(media_engine PRIVATE MUSIC_HAS_OPENCV=1)
    add_custom_command(TARGET media_engine POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<IF:$<CONFIG:Debug>,${MUSIC_OPENCV_DLL_DIR}/opencv_world4120d.dll,${MUSIC_OPENCV_DLL_DIR}/opencv_world4120.dll>"
            $<TARGET_FILE_DIR:media_engine>
        COMMENT "复制 OpenCV DLL (media_engine)"
    )
endif()

# 测试可执行文件
add_executable(media_engine_test src/main.cpp)
target_link_libraries(media_engine_test PRIVATE media_engine)

# CLI 工具（供 64 位 Python 子进程调用）
set(MEDIA_CLI_SOURCES src/media_cli.cpp)

if(MUSIC_HAS_LLAMA)
    list(APPEND MEDIA_CLI_SOURCES
        src/core/audio_extractor.cpp
        src/core/llm_engine.cpp
        src/core/highlight_analyzer.cpp
    )
endif()

add_executable(media_cli ${MEDIA_CLI_SOURCES})

# 统一播放器进程（FFmpeg 解码，Python stdin/stdout 拉帧）
set(PLAYER_SOURCES
    src/player_main.cpp
    src/core/video_player_engine.cpp
    src/core/frame_processor.cpp
)
add_executable(media_player ${PLAYER_SOURCES})
target_include_directories(media_player PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_SOURCE_DIR}/shared/include
)
target_link_libraries(media_player PRIVATE media_shared ffmpeg)
if(WIN32 AND MUSIC_FFMPEG_HWACCEL)
    target_link_libraries(media_player PRIVATE d3d11 dxgi)
    message(STATUS "media_player: D3D11VA hwaccel enabled")
endif()
if(MUSIC_HAS_OPENCV)
    target_link_libraries(media_player PRIVATE music_opencv)
    target_compile_definitions(media_player PRIVATE MUSIC_HAS_OPENCV=1)
    add_custom_command(TARGET media_player POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
            "$<IF:$<CONFIG:Debug>,${MUSIC_OPENCV_DLL_DIR}/opencv_world4120d.dll,${MUSIC_OPENCV_DLL_DIR}/opencv_world4120.dll>"
            $<TARGET_FILE_DIR:media_player>
        COMMENT "复制 OpenCV DLL"
    )
    message(STATUS "media_player: OpenCV frame filters enabled")
endif()

target_include_directories(media_cli PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_SOURCE_DIR}/shared/include
)

target_link_libraries(media_cli PRIVATE media_engine)

if(MUSIC_HAS_LLAMA)
    target_compile_definitions(media_cli PRIVATE MUSIC_HAS_LLAMA)
    target_link_libraries(media_cli PRIVATE music_llama)
    message(STATUS "media_cli: speech analysis + llama enabled")
endif()

# FFmpeg DLL 复制（按当前架构使用 FFMPEG_BIN_DIR）
add_custom_command(TARGET media_engine POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        ${FFMPEG_BIN_DIR}
        $<TARGET_FILE_DIR:media_engine>
    COMMENT "复制 FFmpeg DLL 到输出目录"
)

# 复制 Python 脚本和资源到输出目录
add_custom_command(TARGET media_engine POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        ${CMAKE_CURRENT_SOURCE_DIR}/scripts
        $<TARGET_FILE_DIR:media_engine>/scripts
    COMMAND ${CMAKE_COMMAND} -E copy_directory
        ${CMAKE_CURRENT_SOURCE_DIR}/resources
        $<TARGET_FILE_DIR:media_engine>/resources
    COMMENT "复制 Python 脚本和资源"
)
