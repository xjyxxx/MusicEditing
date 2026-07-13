#pragma once

#include <memory>
#include <string>

namespace media::core {

/// FFmpeg 音频解码 + miniaudio 播放（独立 demuxer，与视频并行）
class AudioPlayerEngine {
public:
    AudioPlayerEngine();
    ~AudioPlayerEngine();

    AudioPlayerEngine(const AudioPlayerEngine&) = delete;
    AudioPlayerEngine& operator=(const AudioPlayerEngine&) = delete;

    bool open(const std::string& filePath);
    void close();

    bool hasAudio() const;
    bool seek(double timestampSec);

    void pause();
    bool resume();
    bool isPaused() const;

    void setVolume(float volume01);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace media::core
