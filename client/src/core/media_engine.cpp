#include "core/media_engine.h"
#include "core/video_decoder.h"

#include "common/logger.h"

#define __STDC_CONSTANT_MACROS
#ifdef _WIN32
extern "C" {
#include "libavutil/ffversion.h"
}
#endif

#include <cstring>
#include <mutex>
#include <string>

namespace {
    std::mutex g_engineMutex;
    bool g_initialized = false;
    std::string g_lastError;

    void setError(const std::string& msg) {
        g_lastError = msg;
        LOG_ERROR(msg);
    }
}

extern "C" {

int media_engine_init() {
    std::lock_guard<std::mutex> lock(g_engineMutex);
    if (g_initialized) return 0;
    media::common::Logger::init("MediaEngine");
    g_initialized = true;
    LOG_INFO(std::string("媒体引擎已初始化, FFmpeg ") + FFMPEG_VERSION);
    return 0;
}

void media_engine_shutdown() {
    std::lock_guard<std::mutex> lock(g_engineMutex);
    g_initialized = false;
}

const char* media_engine_ffmpeg_version() {
    return FFMPEG_VERSION;
}

int media_probe_video(
    const char* filePath,
    int* outWidth,
    int* outHeight,
    double* outDurationSec,
    double* outFps,
    int64_t* outTotalFrames,
    char* outCodecName,
    int codecNameSize,
    char* outFormatName,
    int formatNameSize)
{
    if (!filePath) {
        setError("文件路径为空");
        return -1;
    }

    media::core::VideoDecoder decoder;
    if (!decoder.open(filePath)) {
        setError("打开视频失败: " + std::string(filePath));
        return -2;
    }

    const auto& info = decoder.info();
    if (outWidth)       *outWidth = info.width;
    if (outHeight)      *outHeight = info.height;
    if (outDurationSec) *outDurationSec = info.durationSec;
    if (outFps)         *outFps = info.fps;
    if (outTotalFrames) *outTotalFrames = info.totalFrames;

    if (outCodecName && codecNameSize > 0) {
        strncpy(outCodecName, info.codecName.c_str(), static_cast<size_t>(codecNameSize - 1));
        outCodecName[codecNameSize - 1] = '\0';
    }
    if (outFormatName && formatNameSize > 0) {
        strncpy(outFormatName, info.formatName.c_str(), static_cast<size_t>(formatNameSize - 1));
        outFormatName[formatNameSize - 1] = '\0';
    }

    return 0;
}

int media_iterate_frames(const char* filePath, MediaFrameProgressFn callback, void* userData) {
    if (!filePath || !callback) {
        setError("参数无效");
        return -1;
    }

    media::core::VideoDecoder decoder;
    if (!decoder.open(filePath)) {
        setError("打开视频失败");
        return -2;
    }

    const int64_t total = decoder.info().totalFrames > 0
        ? decoder.info().totalFrames : 0;

    bool ok = decoder.iterateFrames([&](int64_t idx, double ts) {
        return callback(idx, total, ts, userData) == 0;
    });

    return ok ? 0 : -3;
}

int media_extract_thumbnail(
    const char* filePath,
    double timestampSec,
    unsigned char* rgbBuffer,
    int bufferSize)
{
    if (!filePath || !rgbBuffer) {
        setError("参数无效");
        return -1;
    }

    media::core::VideoDecoder decoder;
    if (!decoder.open(filePath)) {
        setError("打开视频失败");
        return -2;
    }

    if (!decoder.extractThumbnail(timestampSec, rgbBuffer, bufferSize)) {
        setError("提取缩略图失败");
        return -3;
    }

    return 0;
}

} // extern "C"
