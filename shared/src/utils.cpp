#include "common/utils.h"

#include <cctype>
#include <filesystem>
#include <sstream>

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#endif

namespace media::common {

namespace {

#ifdef _WIN32
std::wstring utf8PathToWide(const std::string& utf8Path) {
    if (utf8Path.empty()) return {};
    int wlen = MultiByteToWideChar(CP_UTF8, 0, utf8Path.c_str(), -1, nullptr, 0);
    if (wlen <= 0) return {};
    std::wstring wpath(static_cast<size_t>(wlen - 1), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, utf8Path.c_str(), -1, wpath.data(), wlen);
    return wpath;
}
#endif

} // namespace

std::string formatTime(double seconds) {
    if (seconds < 0) seconds = 0;
    int totalSec = static_cast<int>(seconds);
    int h = totalSec / 3600;
    int m = (totalSec % 3600) / 60;
    int s = totalSec % 60;
    int ms = static_cast<int>((seconds - totalSec) * 1000);

    std::ostringstream oss;
    if (h > 0) {
        oss << h << ":";
        if (m < 10) oss << "0";
        oss << m << ":";
        if (s < 10) oss << "0";
        oss << s;
    } else {
        oss << m << ":";
        if (s < 10) oss << "0";
        oss << s;
    }
    oss << "." << ms;
    return oss.str();
}

std::string getFileExtension(const std::string& path) {
    auto pos = path.find_last_of('.');
    if (pos == std::string::npos) return "";
    std::string ext = path.substr(pos + 1);
    for (auto& c : ext) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return ext;
}

bool fileExists(const std::string& path) {
#if defined(_WIN32) && defined(MUSIC_FFMPEG_UTF8_PATH)
    const std::wstring wpath = utf8PathToWide(path);
    return !wpath.empty() && std::filesystem::exists(wpath);
#else
    return std::filesystem::exists(path);
#endif
}

std::vector<std::string> splitString(const std::string& str, char delimiter) {
    std::vector<std::string> result;
    std::stringstream ss(str);
    std::string item;
    while (std::getline(ss, item, delimiter)) {
        result.push_back(item);
    }
    return result;
}

} // namespace media::common
