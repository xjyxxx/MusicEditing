#pragma once

#include <cstdint>
#include <string>

namespace media::core {

/// Real-ESRGAN ONNX 超分（需 MUSIC_HAS_ONNXRUNTIME + MUSIC_HAS_OPENCV）
/// 快速模式：OpenCV 双三次插值（无需模型）
class SuperResolution {
public:
    SuperResolution() = default;
    ~SuperResolution();

    SuperResolution(const SuperResolution&) = delete;
    SuperResolution& operator=(const SuperResolution&) = delete;

    /// 加载 models/realesr-general-x4v3.onnx；快速模式可传 "-"
    bool loadModel(const std::string& modelPath);

    void unload();

    bool isReady() const;

    bool usesOpenCvFallback() const;

    bool usesCuda() const;

    /// opencv / cuda / cpu
    const char* executionProvider() const;

    /// 模型固有倍率（Real-ESRGAN x4v3 = 4）
    int modelScale() const;

    /// 对图片文件超分并保存；scale=2|4；strength 0~1（AI 与双三次混合，越小越自然）
    bool upscaleImageFile(
        const std::string& inputPath,
        const std::string& outputPath,
        int scale,
        float strength = 0.65f);

    const std::string& lastError() const { return lastError_; }

private:
    struct Impl;
    Impl* impl_ = nullptr;
    std::string lastError_;
};

} // namespace media::core
