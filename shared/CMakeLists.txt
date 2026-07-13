add_library(media_shared STATIC
    src/logger.cpp
    src/utils.cpp
    src/config.cpp
    src/protocol.cpp
    src/file_path.cpp
    src/ffmpeg_compat.cpp
)

if(MUSIC_FFMPEG_HWACCEL)
    target_sources(media_shared PRIVATE src/ffmpeg_hwaccel.cpp)
    target_compile_definitions(media_shared PUBLIC MUSIC_FFMPEG_HWACCEL=1)
endif()

target_include_directories(media_shared
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

target_link_libraries(media_shared PUBLIC ffmpeg)

target_compile_definitions(media_shared
    PUBLIC
        MEDIA_SHARED_EXPORTS
)
