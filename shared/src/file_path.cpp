#include "common/file_path.h"

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#endif

namespace media::common {

std::wstring utf8PathToWide(const std::string& utf8Path) {
    if (utf8Path.empty()) return {};
    int wlen = MultiByteToWideChar(CP_UTF8, 0, utf8Path.c_str(), -1, nullptr, 0);
    if (wlen <= 0) return {};
    std::wstring wpath(static_cast<size_t>(wlen - 1), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, utf8Path.c_str(), -1, wpath.data(), wlen);
    return wpath;
}

std::string pathUtf8ToNative(const std::string& utf8Path) {
#ifdef _WIN32
    if (utf8Path.empty()) return utf8Path;

    int wlen = MultiByteToWideChar(CP_UTF8, 0, utf8Path.c_str(), -1, nullptr, 0);
    if (wlen <= 0) return utf8Path;

    std::wstring wstr(static_cast<size_t>(wlen - 1), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, utf8Path.c_str(), -1, &wstr[0], wlen);

    int alen = WideCharToMultiByte(CP_ACP, 0, wstr.c_str(), -1, nullptr, 0, nullptr, nullptr);
    if (alen <= 0) return utf8Path;

    std::string native(static_cast<size_t>(alen - 1), '\0');
    WideCharToMultiByte(CP_ACP, 0, wstr.c_str(), -1, &native[0], alen, nullptr, nullptr);
    return native;
#else
    return utf8Path;
#endif
}

std::string pathForFfmpeg(const std::string& utf8Path) {
#if defined(_WIN32) && defined(MUSIC_FFMPEG_UTF8_PATH)
    return utf8Path;
#else
    return pathUtf8ToNative(utf8Path);
#endif
}

} // namespace media::common
