#include "core/video_player_engine.h"

#include "common/logger.h"

#include <iostream>
#include <sstream>
#include <string>
#include <cctype>

namespace {

media::core::VideoPlayerEngine g_player;
bool g_hwaccel_preferred = false;

std::string trim(const std::string& s) {
    size_t b = 0, e = s.size();
    while (b < e && (s[b] == ' ' || s[b] == '\t' || s[b] == '\r')) ++b;
    while (e > b && (s[e - 1] == ' ' || s[e - 1] == '\t' || s[e - 1] == '\r')) --e;
    return s.substr(b, e - b);
}

void replyError(const std::string& msg) {
    std::cout << "ERROR " << msg << std::endl;
    std::cout.flush();
    LOG_ERROR(msg);
}

void logCmd(const std::string& line) {
    LOG_DEBUG("IPC << " + line);
}

} // namespace

int main() {
    media::common::Logger::init("MediaPlayer");
    LOG_INFO("media_player 启动");
#if defined(MUSIC_HAS_GLEW) && MUSIC_HAS_GLEW
    LOG_INFO("GLEW 已链接（OpenGL 扩展加载器；画面由 UI QOpenGLWidget 渲染）");
#endif

    std::string line;
    while (std::getline(std::cin, line)) {
        line = trim(line);
        if (line.empty()) continue;
        logCmd(line);

        std::istringstream iss(line);
        std::string cmd;
        iss >> cmd;

        if (cmd == "QUIT" || cmd == "quit") {
            g_player.close();
            std::cout << "BYE" << std::endl;
            LOG_INFO("media_player 退出");
            break;
        }

        if (cmd == "HWACCEL") {
            std::string mode;
            iss >> mode;
            for (char& c : mode) {
                c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
            }
            g_hwaccel_preferred = (mode == "on" || mode == "1" || mode == "true");
            g_player.setHwAccelPreferred(g_hwaccel_preferred);
            std::cout << "HWACCEL_OK enabled=" << (g_hwaccel_preferred ? 1 : 0) << std::endl;
            std::cout.flush();
            continue;
        }

        if (cmd == "OPEN") {
            std::string path;
            std::getline(iss, path);
            path = trim(path);
            if (path.size() >= 2 && path.front() == '"' && path.back() == '"') {
                path = path.substr(1, path.size() - 2);
            }
            g_player.setHwAccelPreferred(g_hwaccel_preferred);
            if (!g_player.open(path)) {
                replyError("open_failed");
                continue;
            }
            const auto& info = g_player.info();
            std::cout << "OPEN_OK duration=" << info.durationSec
                << " fps=" << info.fps
                << " width=" << info.width
                << " height=" << info.height
                << " audio=" << (g_player.hasAudioStream() ? 1 : 0)
                << " hw=" << (g_player.isHwAccelActive() ? 1 : 0)
                << " hw_name=" << g_player.hwAccelName() << std::endl;
            std::cout.flush();
            continue;
        }

        if (cmd == "CLOSE") {
            g_player.close();
            std::cout << "CLOSE_OK" << std::endl;
            std::cout.flush();
            continue;
        }

        if (cmd == "SEEK") {
            double sec = 0;
            iss >> sec;
            if (!g_player.seek(sec)) {
                replyError("seek_failed");
            } else {
                std::cout << "SEEK_OK timestamp=" << sec << std::endl;
            }
            std::cout.flush();
            continue;
        }

        if (cmd == "PAUSE") {
            g_player.pause();
            std::cout << "PAUSE_OK" << std::endl;
            std::cout.flush();
            continue;
        }

        if (cmd == "RESUME") {
            g_player.resume();
            std::cout << "RESUME_OK" << std::endl;
            std::cout.flush();
            continue;
        }

        if (cmd == "FILTER") {
            std::string mode;
            iss >> mode;
            if (!g_player.setFrameFilter(mode)) {
                replyError("invalid_filter");
            } else {
                std::cout << "FILTER_OK mode=" << g_player.frameFilterName() << std::endl;
            }
            std::cout.flush();
            continue;
        }

        if (cmd == "SCALE") {
            int sw = 0, sh = 0;
            iss >> sw >> sh;
            g_player.setPlaybackScale(sw, sh);
            std::cout << "SCALE_OK width=" << sw << " height=" << sh << std::endl;
            std::cout.flush();
            continue;
        }

        if (cmd == "NEXT") {
            std::string outPath;
            double minTs = -1.0;
            int applyFilter = 1;
            iss >> outPath;
            if (iss >> minTs) {
                int filterFlag = 1;
                if (iss >> filterFlag) {
                    applyFilter = filterFlag;
                }
            }

            media::core::VideoPlayerEngine::DecodeFrameResult decoded{};
            if (!g_player.decodeNextFrameToFile(outPath, &decoded, minTs, applyFilter != 0)) {
                std::cout << "FRAME_EOF" << std::endl;
            } else {
                const auto& info = g_player.info();
                const int fw = decoded.width > 0 ? decoded.width : info.width;
                const int fh = decoded.height > 0 ? decoded.height : info.height;
                std::cout << "FRAME_OK timestamp=" << decoded.timestampSec
                    << " width=" << fw
                    << " height=" << fh
                    << " skipped=" << decoded.skippedFrames
                    << " decode_ms=" << decoded.decodeMs
                    << " hw_xfer=" << (decoded.hwTransfer ? 1 : 0)
                    << " path=" << outPath << std::endl;
            }
            std::cout.flush();
            continue;
        }

        replyError("unknown_command");
    }

    return 0;
}
