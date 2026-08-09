#pragma once

#include "common/protocol.h"

#include <memory>
#include <string>

namespace media::core {

/// FFmpeg Stateful 播放器引擎（解码 → RGB24，供 Python UI 拉帧显示）
class VideoPlayerEngine {
public:
    VideoPlayerEngine();
    ~VideoPlayerEngine();

    VideoPlayerEngine(const VideoPlayerEngine&) = delete;
    VideoPlayerEngine& operator=(const VideoPlayerEngine&) = delete;

    bool open(const std::string& filePath);
    void close();

    /// 打开前设置：是否尝试 D3D11VA 硬解（x64/modern FFmpeg）
    void setHwAccelPreferred(bool enabled) { hwAccelPreferred_ = enabled; }
    bool isHwAccelActive() const;
    std::string hwAccelName() const;

    bool isOpen() const;
    const common::VideoInfo& info() const;
    bool hasAudioStream() const;

    bool seek(double timestampSec);

    struct DecodeFrameResult {
        double timestampSec = 0.0;
        int skippedFrames = 0;
        int decodeMs = 0;
        bool hwTransfer = false;
        int width = 0;
        int height = 0;
        int stride = 0; // RGB 行跨度（字节）
    };

    /// 播放时缩小输出（0=原始分辨率），降低 IPC/显示开销
    void setPlaybackScale(int width, int height);

    /// 解码到紧密打包或带 stride 的 RGB24 缓冲区；capacity 为字节数
    /// 成功时 result->width/height/stride 有效；像素写入 outRgb（按 stride）
    bool decodeNextFrameToBuffer(uint8_t* outRgb, size_t capacity, DecodeFrameResult* result,
        double minTimestampSec = -1.0, bool applyFilter = true);

    /// 兼容：解码并写出 RGB24 文件（测试/回退）
    bool decodeNextFrameToFile(const std::string& rgbFilePath, DecodeFrameResult* result,
        double minTimestampSec = -1.0, bool applyFilter = true);

    void pause() { paused_ = true; }
    void resume() { paused_ = false; }
    bool isPaused() const { return paused_; }

    /// 设置 OpenCV 帧滤镜：clahe / denoise / sharpen / film / neon / comic / pixel / off
    bool setFrameFilter(const std::string& name);
    std::string frameFilterName() const;

    /// 滤镜设备：auto | cpu | opencl
    bool setFrameFilterDevice(const std::string& name);
    std::string frameFilterDeviceName() const;
    std::string frameFilterActiveDeviceName() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    bool paused_ = false;
    bool hwAccelPreferred_ = false;

    void ensureSwsContext(int srcW, int srcH, int srcPixFmt);
};

} // namespace media::core
