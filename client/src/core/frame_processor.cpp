#include "core/frame_processor.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <vector>

#ifdef MUSIC_HAS_OPENCV
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#endif

namespace media::core {

namespace {

std::string toLower(std::string s) {
    for (char& c : s) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return s;
}

} // namespace

bool FrameProcessor::setModeFromString(const std::string& name) {
    const std::string k = toLower(name);
    if (k.empty() || k == "off" || k == "none" || k == "passthrough") {
        mode_ = FrameFilterMode::Passthrough;
        return true;
    }
    if (k == "clahe" || k == "enhance") {
        mode_ = FrameFilterMode::Clahe;
        return true;
    }
    if (k == "denoise") {
        mode_ = FrameFilterMode::Denoise;
        return true;
    }
    if (k == "sharpen") {
        mode_ = FrameFilterMode::Sharpen;
        return true;
    }
    if (k == "film" || k == "sepia") {
        mode_ = FrameFilterMode::Film;
        return true;
    }
    if (k == "neon") {
        mode_ = FrameFilterMode::Neon;
        return true;
    }
    if (k == "comic" || k == "manga" || k == "cartoon") {
        mode_ = FrameFilterMode::Comic;
        return true;
    }
    if (k == "pixel" || k == "pixelate") {
        mode_ = FrameFilterMode::Pixel;
        return true;
    }
    return false;
}

std::string FrameProcessor::modeName() const {
    switch (mode_) {
    case FrameFilterMode::Clahe: return "clahe";
    case FrameFilterMode::Denoise: return "denoise";
    case FrameFilterMode::Sharpen: return "sharpen";
    case FrameFilterMode::Film: return "film";
    case FrameFilterMode::Neon: return "neon";
    case FrameFilterMode::Comic: return "comic";
    case FrameFilterMode::Pixel: return "pixel";
    default: return "off";
    }
}

bool FrameProcessor::processRgbFrame(uint8_t* rgb, int width, int height, int strideBytes) {
    if (!enabled_ || !rgb || width <= 0 || height <= 0) {
        return false;
    }

    const int step = strideBytes > 0 ? strideBytes : width * 3;
    if (mode_ == FrameFilterMode::Passthrough) {
        return true;
    }

#ifdef MUSIC_HAS_OPENCV
    cv::Mat frame(height, width, CV_8UC3, rgb, static_cast<size_t>(step));

    switch (mode_) {
    case FrameFilterMode::Clahe: {
        cv::Mat lab;
        cv::cvtColor(frame, lab, cv::COLOR_RGB2Lab);
        std::vector<cv::Mat> channels;
        cv::split(lab, channels);
        cv::Ptr<cv::CLAHE> clahe = cv::createCLAHE(2.0, cv::Size(8, 8));
        clahe->apply(channels[0], channels[0]);
        cv::merge(channels, lab);
        cv::cvtColor(lab, frame, cv::COLOR_Lab2RGB);
        break;
    }
    case FrameFilterMode::Denoise: {
        cv::Mat tmp;
        cv::bilateralFilter(frame, tmp, 5, 50, 50);
        tmp.copyTo(frame);
        break;
    }
    case FrameFilterMode::Sharpen: {
        cv::Mat blurred;
        cv::GaussianBlur(frame, blurred, cv::Size(0, 0), 1.2);
        cv::addWeighted(frame, 1.4, blurred, -0.4, 0, frame);
        break;
    }
    case FrameFilterMode::Film: {
        // 暖色胶片调色（加重，预览分辨率下也明显）
        cv::Mat f;
        frame.convertTo(f, CV_32FC3, 1.0 / 255.0);
        std::vector<cv::Mat> ch;
        cv::split(f, ch);
        cv::Mat r = ch[0] * 0.45f + ch[1] * 0.85f + ch[2] * 0.20f;
        cv::Mat g = ch[0] * 0.30f + ch[1] * 0.70f + ch[2] * 0.15f;
        cv::Mat b = ch[0] * 0.15f + ch[1] * 0.40f + ch[2] * 0.12f;
        cv::merge(std::vector<cv::Mat>{r, g, b}, f);
        f.convertTo(frame, CV_8UC3, 255.0);
        const float cx = (width - 1) * 0.5f;
        const float cy = (height - 1) * 0.5f;
        const float maxD = std::sqrt(cx * cx + cy * cy) + 1e-3f;
        for (int y = 0; y < height; ++y) {
            uint8_t* row = frame.ptr<uint8_t>(y);
            for (int x = 0; x < width; ++x) {
                const float dx = x - cx;
                const float dy = y - cy;
                const float d = std::sqrt(dx * dx + dy * dy) / maxD;
                const float vig = std::clamp(1.0f - 0.65f * d * d, 0.4f, 1.0f);
                row[x * 3 + 0] = static_cast<uint8_t>(row[x * 3 + 0] * vig);
                row[x * 3 + 1] = static_cast<uint8_t>(row[x * 3 + 1] * vig);
                row[x * 3 + 2] = static_cast<uint8_t>(row[x * 3 + 2] * vig);
            }
        }
        break;
    }
    case FrameFilterMode::Neon: {
        cv::Mat gray, edges, glow, dark;
        cv::cvtColor(frame, gray, cv::COLOR_RGB2GRAY);
        cv::Canny(gray, edges, 40, 120);
        cv::cvtColor(edges, glow, cv::COLOR_GRAY2RGB);
        for (int y = 0; y < height; ++y) {
            uint8_t* er = glow.ptr<uint8_t>(y);
            for (int x = 0; x < width; ++x) {
                if (er[x * 3] == 0) {
                    continue;
                }
                er[x * 3 + 0] = 40;
                er[x * 3 + 1] = 255;
                er[x * 3 + 2] = 255;
            }
        }
        frame.convertTo(dark, CV_8UC3, 0.35, 0);
        cv::addWeighted(dark, 1.0, glow, 1.2, 0, frame);
        break;
    }
    case FrameFilterMode::Comic: {
        cv::Mat smooth, gray, edges, edges3;
        cv::bilateralFilter(frame, smooth, 9, 80, 80);
        cv::cvtColor(smooth, gray, cv::COLOR_RGB2GRAY);
        cv::medianBlur(gray, gray, 7);
        cv::adaptiveThreshold(
            gray, edges, 255,
            cv::ADAPTIVE_THRESH_MEAN_C, cv::THRESH_BINARY, 11, 2);
        cv::cvtColor(edges, edges3, cv::COLOR_GRAY2RGB);
        cv::bitwise_and(smooth, edges3, frame);
        break;
    }
    case FrameFilterMode::Pixel: {
        const int block = std::max(12, std::min(width, height) / 28);
        const int sw = std::max(1, width / block);
        const int sh = std::max(1, height / block);
        cv::Mat small;
        cv::resize(frame, small, cv::Size(sw, sh), 0, 0, cv::INTER_LINEAR);
        cv::resize(small, frame, cv::Size(width, height), 0, 0, cv::INTER_NEAREST);
        break;
    }
    default:
        break;
    }
    return true;
#else
    (void)step;
    return true;
#endif
}

} // namespace media::core
