#pragma once

#include <cstdint>
#include <string>

namespace media::common {

enum class TaskState : int32_t {
    Waiting = 0,
    Processing = 1,
    Rendering = 2,
    Completed = 3,
    Failed = 4,
    Cancelled = 5
};

enum class TaskType : int32_t {
    Slice = 0,
    Enhance = 1,
    Watermark = 2
};

struct VideoInfo {
    std::string filePath;
    int width = 0;
    int height = 0;
    double durationSec = 0.0;
    double fps = 0.0;
    int64_t totalFrames = 0;
    std::string codecName;
    std::string formatName;
};

struct TaskProgress {
    int32_t taskId = 0;
    TaskType type = TaskType::Slice;
    TaskState state = TaskState::Waiting;
    int64_t currentFrame = 0;
    int64_t totalFrames = 0;
    float progress = 0.0f;
    std::string message;
};

} // namespace media::common
