#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace media::core {

struct WatermarkRegion {
    int x = 0;
    int y = 0;
    int w = 0;
    int h = 0;
};

/// LaMa ONNX 去水印（需 MUSIC_HAS_ONNXRUNTIME + MUSIC_HAS_OPENCV）
class WatermarkInpainter {
public:
    WatermarkInpainter() = default;
    ~WatermarkInpainter();

    WatermarkInpainter(const WatermarkInpainter&) = delete;
    WatermarkInpainter& operator=(const WatermarkInpainter&) = delete;

    /// 加载 models/lama.onnx 或指定路径
    bool loadModel(const std::string& modelPath);

    void unload();

    bool isReady() const;

    bool usesOpenCvFallback() const;

    /// 对 RGB24 帧原地修复（可多个矩形水印区域）
    bool inpaintRgbFrame(
        uint8_t* rgb,
        int width,
        int height,
        int strideBytes,
        const std::vector<WatermarkRegion>& regions);

    /// 从文件修复并保存（PNG/JPG/BMP）
    bool inpaintImageFile(
        const std::string& inputPath,
        const std::string& outputPath,
        const std::vector<WatermarkRegion>& regions);

    const std::string& lastError() const { return lastError_; }

private:
    struct Impl;
    Impl* impl_ = nullptr;
    std::string lastError_;
};

} // namespace media::core
