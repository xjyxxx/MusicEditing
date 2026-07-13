#pragma once

#include <string>

namespace media::core {

/// 从视频提取 16kHz 单声道 PCM WAV，供 ASR 使用
bool extractAudioToWav(const std::string& videoPath, const std::string& wavPath);

} // namespace media::core
