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
    };

    /// 播放时缩小输出（0=原始分辨率），降低 IPC/显示开销
    void setPlaybackScale(int width, int height);

    /// 解码并输出一帧 RGB24；minTimestampSec>=0 时在 C++ 内跳帧（不写盘/不过滤）
    bool decodeNextFrameToFile(const std::string& rgbFilePath, DecodeFrameResult* result,
        double minTimestampSec = -1.0, bool applyFilter = true);

    void pause() { paused_ = true; }
    void resume() { paused_ = false; }
    bool isPaused() const { return paused_; }

    /// 设置 OpenCV 帧滤镜：clahe / denoise / sharpen / off
    bool setFrameFilter(const std::string& name);
    std::string frameFilterName() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
    bool paused_ = false;
    bool hwAccelPreferred_ = false;

    void ensureSwsContext(int srcW, int srcH, int srcPixFmt);
};

} // namespace media::core
