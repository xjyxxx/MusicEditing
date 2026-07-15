#pragma once

#include "common/protocol.h"

#include <functional>
#include <memory>
#include <string>

namespace media::core {

using FrameCallback = std::function<bool(int64_t frameIndex, double timestampSec)>;

class VideoDecoder {
public:
    VideoDecoder();
    ~VideoDecoder();

    VideoDecoder(const VideoDecoder&) = delete;
    VideoDecoder& operator=(const VideoDecoder&) = delete;

    /// preferHwaccel：与播放器相同，请求 D3D11VA；失败自动回退 CPU
    bool open(const std::string& filePath, bool preferHwaccel = false);
    void close();

    bool isOpen() const;
    bool isHwAccelActive() const;
    const common::VideoInfo& info() const;

    /// 遍历视频帧，回调返回 false 时提前停止
    bool iterateFrames(FrameCallback callback);

    /// 提取指定时间点的首帧到 RGB24 缓冲区（width*height*3 字节）
    bool extractThumbnail(double timestampSec, unsigned char* rgbBuffer, int bufferSize);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace media::core
