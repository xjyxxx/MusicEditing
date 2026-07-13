#pragma once

#include <string>
#include <vector>

namespace media::common {

std::string formatTime(double seconds);
std::string getFileExtension(const std::string& path);
bool fileExists(const std::string& path);
std::vector<std::string> splitString(const std::string& str, char delimiter);

} // namespace media::common
