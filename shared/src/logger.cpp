#include "common/logger.h"

#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>

namespace media::common {

namespace {
    std::mutex g_logMutex;
    LogLevel g_level = LogLevel::Info;
    std::string g_name = "MusicEditing";
    std::ofstream g_logFile;

    LogLevel parseLevel(const char* s) {
        if (!s) return LogLevel::Info;
        std::string v(s);
        if (v == "debug" || v == "DEBUG") return LogLevel::Debug;
        if (v == "trace" || v == "TRACE") return LogLevel::Trace;
        if (v == "warn" || v == "WARN") return LogLevel::Warn;
        if (v == "error" || v == "ERROR") return LogLevel::Error;
        return LogLevel::Info;
    }

    const char* levelName(LogLevel level) {
        switch (level) {
        case LogLevel::Trace: return "TRACE";
        case LogLevel::Debug: return "DEBUG";
        case LogLevel::Info:  return "INFO";
        case LogLevel::Warn:  return "WARN";
        case LogLevel::Error: return "ERROR";
        default: return "UNKNOWN";
        }
    }

    void writeLine(const std::string& line) {
        std::cerr << line << std::endl;
        if (g_logFile.is_open()) {
            g_logFile << line << std::endl;
            g_logFile.flush();
        }
    }
}

void Logger::init(const std::string& name) {
    std::lock_guard<std::mutex> lock(g_logMutex);
    g_name = name;

    if (const char* logPath = std::getenv("MUSIC_LOG_FILE")) {
        if (g_logFile.is_open()) {
            g_logFile.close();
        }
        g_logFile.open(logPath, std::ios::app);
    }

    if (const char* lvl = std::getenv("MUSIC_LOG_LEVEL")) {
        g_level = parseLevel(lvl);
    }
}

void Logger::setLevel(LogLevel level) {
    std::lock_guard<std::mutex> lock(g_logMutex);
    g_level = level;
}

void Logger::log(LogLevel level, const std::string& message) {
    if (level < g_level) return;

    auto now = std::chrono::system_clock::now();
    auto time = std::chrono::system_clock::to_time_t(now);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &time);
#else
    localtime_r(&time, &tm);
#endif

    std::ostringstream oss;
    oss << std::put_time(&tm, "%H:%M:%S")
        << " [" << g_name << "] "
        << levelName(level) << " "
        << message;

    std::lock_guard<std::mutex> lock(g_logMutex);
    writeLine(oss.str());
}

} // namespace media::common
