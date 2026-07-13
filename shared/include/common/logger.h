#pragma once

#include <string>

namespace media::common {

enum class LogLevel {
    Trace,
    Debug,
    Info,
    Warn,
    Error
};

class Logger {
public:
    static void init(const std::string& name = "MusicEditing");
    static void setLevel(LogLevel level);
    static void log(LogLevel level, const std::string& message);
};

#define LOG_DEBUG(msg) media::common::Logger::log(media::common::LogLevel::Debug, msg)
#define LOG_INFO(msg)  media::common::Logger::log(media::common::LogLevel::Info,  msg)
#define LOG_WARN(msg)  media::common::Logger::log(media::common::LogLevel::Warn,  msg)
#define LOG_ERROR(msg) media::common::Logger::log(media::common::LogLevel::Error, msg)

} // namespace media::common
