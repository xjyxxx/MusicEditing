#pragma once

#include <cstdint>
#include <string>

namespace media::core {

/// 解码后帧处理滤镜（OpenCV 可选）
enum class FrameFilterMode {
    Passthrough = 0,
    Clahe,      ///< 自适应对比度增强（画质预览）
    Denoise,    ///< 双边滤波降噪
    Sharpen,    ///< 锐化
};

class FrameProcessor {
public:
    FrameProcessor() = default;

    /// 处理 RGB24 帧（原地修改）；返回 false 表示丢弃该帧
    bool processRgbFrame(uint8_t* rgb, int width, int height, int strideBytes = 0);

    void setEnabled(bool enabled) { enabled_ = enabled; }
    bool isEnabled() const { return enabled_; }

    void setMode(FrameFilterMode mode) { mode_ = mode; }
    FrameFilterMode mode() const { return mode_; }

    /// clahe | denoise | sharpen | off
    bool setModeFromString(const std::string& name);

    std::string modeName() const;

private:
    bool enabled_ = true;
    FrameFilterMode mode_ = FrameFilterMode::Passthrough;
};

} // namespace media::core
