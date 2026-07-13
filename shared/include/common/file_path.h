#pragma once

#include <string>

#ifdef _WIN32
#include <string> // wstring
#endif

namespace media::common {

/// 将 UTF-8 路径转为 Windows 本地编码（GBK 等），供旧版 Win32 FFmpeg
std::string pathUtf8ToNative(const std::string& utf8Path);

#ifdef _WIN32
/// UTF-8 → 宽字符（供 ONNX/OpenCV 等 API）
std::wstring utf8PathToWide(const std::string& utf8Path);
#endif

/// 打开 FFmpeg 媒体文件时使用的路径（x64 现代库保持 UTF-8，Win32 转 GBK）
std::string pathForFfmpeg(const std::string& utf8Path);

} // namespace media::common
