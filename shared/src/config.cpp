#include "common/config.h"

#include <fstream>
#include <sstream>

namespace media::common {

bool Config::loadFromFile(const std::string& path) {
    std::ifstream file(path);
    if (!file.is_open()) return false;

    std::string line;
    while (std::getline(file, line)) {
        if (line.empty() || line[0] == '#' || line[0] == ';') continue;
        auto pos = line.find('=');
        if (pos == std::string::npos) continue;
        std::string key = line.substr(0, pos);
        std::string val = line.substr(pos + 1);
        while (!key.empty() && (key.back() == ' ' || key.back() == '\t')) key.pop_back();
        while (!val.empty() && (val.front() == ' ' || val.front() == '\t')) val.erase(val.begin());
        values_[key] = val;
    }
    return true;
}

std::string Config::getString(const std::string& key, const std::string& defaultVal) const {
    auto it = values_.find(key);
    return it != values_.end() ? it->second : defaultVal;
}

int Config::getInt(const std::string& key, int defaultVal) const {
    auto it = values_.find(key);
    if (it == values_.end()) return defaultVal;
    try {
        return std::stoi(it->second);
    } catch (...) {
        return defaultVal;
    }
}

bool Config::getBool(const std::string& key, bool defaultVal) const {
    auto val = getString(key);
    if (val.empty()) return defaultVal;
    if (val == "1" || val == "true" || val == "True" || val == "yes") return true;
    if (val == "0" || val == "false" || val == "False" || val == "no") return false;
    return defaultVal;
}

} // namespace media::common
