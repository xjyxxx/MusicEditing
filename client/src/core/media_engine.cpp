#include "core/media_engine.h"
#include "core/video_decoder.h"

#include "common/logger.h"

#if defined(MUSIC_HAS_ONNXRUNTIME) && defined(MUSIC_HAS_OPENCV)
#include "core/watermark_inpainter.h"
#endif

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

#if defined(MUSIC_HAS_ONNXRUNTIME) && defined(MUSIC_HAS_OPENCV)
    media::core::WatermarkInpainter g_watermarkInpainter;
#endif
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
#if defined(MUSIC_HAS_ONNXRUNTIME) && defined(MUSIC_HAS_OPENCV)
    g_watermarkInpainter.unload();
#endif
    g_initialized = false;
}

const char* media_engine_last_error() {
    return g_lastError.c_str();
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

#if defined(MUSIC_HAS_ONNXRUNTIME) && defined(MUSIC_HAS_OPENCV)

int media_watermark_load_model(const char* modelPath) {
    if (!modelPath || !*modelPath) {
        setError("模型路径为空");
        return -1;
    }
    if (!g_watermarkInpainter.loadModel(modelPath)) {
        setError(g_watermarkInpainter.lastError());
        return -2;
    }
    return 0;
}

int media_watermark_inpaint_image(
    const char* inputPath,
    const char* outputPath,
    const int* regions,
    int numRegions)
{
    if (!inputPath || !outputPath || !regions || numRegions <= 0) {
        setError("参数无效");
        return -1;
    }
    if (!g_watermarkInpainter.isReady()) {
        setError("请先 media_watermark_load_model");
        return -2;
    }

    std::vector<media::core::WatermarkRegion> rs;
    rs.reserve(static_cast<size_t>(numRegions));
    for (int i = 0; i < numRegions; ++i) {
        media::core::WatermarkRegion r;
        r.x = regions[i * 4 + 0];
        r.y = regions[i * 4 + 1];
        r.w = regions[i * 4 + 2];
        r.h = regions[i * 4 + 3];
        rs.push_back(r);
    }

    if (!g_watermarkInpainter.inpaintImageFile(inputPath, outputPath, rs)) {
        setError(g_watermarkInpainter.lastError());
        return -3;
    }
    return 0;
}

int media_watermark_uses_opencv_fallback() {
    return g_watermarkInpainter.usesOpenCvFallback() ? 1 : 0;
}
#endif

} // extern "C"
