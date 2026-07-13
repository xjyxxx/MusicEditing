#pragma once

#include <string>
#include <unordered_map>

namespace media::common {

class Config {
public:
    bool loadFromFile(const std::string& path);
    std::string getString(const std::string& key, const std::string& defaultVal = "") const;
    int getInt(const std::string& key, int defaultVal = 0) const;
    bool getBool(const std::string& key, bool defaultVal = false) const;

private:
    std::unordered_map<std::string, std::string> values_;
};

} // namespace media::common
