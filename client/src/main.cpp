#include "core/video_decoder.h"
#include "core/media_engine.h"

#include "common/logger.h"

#include <iostream>

int main(int argc, char* argv[]) {
    media_engine_init();

    const char* testFile = (argc > 1) ? argv[1] : nullptr;
    if (!testFile) {
        std::cout << "用法: media_engine_test <视频文件路径>" << std::endl;
        std::cout << "FFmpeg 版本: " << media_engine_ffmpeg_version() << std::endl;
        return 0;
    }

    int width = 0, height = 0;
    double duration = 0, fps = 0;
    int64_t totalFrames = 0;
    char codec[64] = {};
    char format[64] = {};

    int ret = media_probe_video(testFile, &width, &height, &duration, &fps,
        &totalFrames, codec, sizeof(codec), format, sizeof(format));

    if (ret != 0) {
        std::cerr << "探测失败, code=" << ret << std::endl;
        return 1;
    }

    std::cout << "=== 视频信息 ===" << std::endl;
    std::cout << "文件: " << testFile << std::endl;
    std::cout << "分辨率: " << width << "x" << height << std::endl;
    std::cout << "时长: " << duration << "s" << std::endl;
    std::cout << "帧率: " << fps << " fps" << std::endl;
    std::cout << "总帧数: " << totalFrames << std::endl;
    std::cout << "编码: " << codec << ", 格式: " << format << std::endl;

    int frameCount = 0;
    auto progressCb = [](int64_t idx, int64_t total, double ts, void* userData) -> int {
        auto* count = static_cast<int*>(userData);
        (*count)++;
        if (idx % 100 == 0) {
            std::cout << "帧 " << idx;
            if (total > 0) std::cout << "/" << total;
            std::cout << " @ " << ts << "s" << std::endl;
        }
        return (*count < 500) ? 0 : 1;
    };

    ret = media_iterate_frames(testFile, progressCb, &frameCount, 1);
    std::cout << "遍历完成, 共处理 " << frameCount << " 帧, code=" << ret << std::endl;

    media_engine_shutdown();
    return 0;
}
