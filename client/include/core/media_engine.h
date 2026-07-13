#pragma once

#include "shared_export.h"

#include <cstdint>

#ifdef __cplusplus
extern "C" {
#endif

/// 引擎初始化（FFmpeg 全局初始化）
MEDIA_API int media_engine_init();

/// 引擎释放
MEDIA_API void media_engine_shutdown();

/// 最近一次 API 错误描述（线程内有效直至下次 setError）
MEDIA_API const char* media_engine_last_error();

/// 获取 FFmpeg 版本字符串
MEDIA_API const char* media_engine_ffmpeg_version();

/// 探测视频文件，返回 0 成功
MEDIA_API int media_probe_video(
    const char* filePath,
    int* outWidth,
    int* outHeight,
    double* outDurationSec,
    double* outFps,
    int64_t* outTotalFrames,
    char* outCodecName,
    int codecNameSize,
    char* outFormatName,
    int formatNameSize
);

/// 遍历视频帧，progressCallback(frameIndex, totalFrames, timestampSec) 返回 0 继续，非 0 停止
typedef int (*MediaFrameProgressFn)(int64_t frameIndex, int64_t totalFrames, double timestampSec, void* userData);

MEDIA_API int media_iterate_frames(
    const char* filePath,
    MediaFrameProgressFn callback,
    void* userData
);

/// 提取缩略图到 RGB24 缓冲区
MEDIA_API int media_extract_thumbnail(
    const char* filePath,
    double timestampSec,
    unsigned char* rgbBuffer,
    int bufferSize
);

#if defined(MUSIC_HAS_ONNXRUNTIME) && defined(MUSIC_HAS_OPENCV)
/// 加载 LaMa ONNX 模型，返回 0 成功
MEDIA_API int media_watermark_load_model(const char* modelPath);

/// 对图片文件去水印；regions 为 numRegions 个 [x,y,w,h]
MEDIA_API int media_watermark_inpaint_image(
    const char* inputPath,
    const char* outputPath,
    const int* regions,
    int numRegions);

/// 当前是否因 LaMa ONNX 不可用而回退 OpenCV inpaint
MEDIA_API int media_watermark_uses_opencv_fallback();
#endif

#ifdef __cplusplus
}
#endif
