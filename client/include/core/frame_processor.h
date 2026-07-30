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
    Film,       ///< 胶片：暖色 + 轻微暗角
    Neon,       ///< 霓虹：边缘高亮
    Comic,      ///< 漫画：平滑 + 墨线
    Pixel,      ///< 像素风：最近邻放大
};

/// 滤镜计算设备：auto 优先 OpenCL，失败回退 CPU
enum class FrameFilterDevice {
    Auto = 0,
    Cpu,
    OpenCL,
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

    /// clahe | denoise | sharpen | film | neon | comic | pixel | off
    bool setModeFromString(const std::string& name);

    std::string modeName() const;

    /// auto | cpu | opencl
    bool setDeviceFromString(const std::string& name);
    FrameFilterDevice device() const { return device_; }
    /// 配置的设备名
    std::string deviceName() const;
    /// 最近一次实际使用的设备（opencl | cpu）
    std::string activeDeviceName() const;

    /// 探测本机 OpenCL（静态缓存）
    static bool openclAvailable();

private:
    bool enabled_ = true;
    FrameFilterMode mode_ = FrameFilterMode::Passthrough;
    FrameFilterDevice device_ = FrameFilterDevice::Auto;
    bool last_used_opencl_ = false;

#ifdef MUSIC_HAS_OPENCV
    bool processCpu(uint8_t* rgb, int width, int height, int step);
    bool processOpenCL(uint8_t* rgb, int width, int height, int step);
#endif
};

} // namespace media::core
