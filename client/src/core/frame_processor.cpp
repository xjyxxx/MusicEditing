#include "core/frame_processor.h"

#include <algorithm>
#include <cctype>

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
    return false;
}

std::string FrameProcessor::modeName() const {
    switch (mode_) {
    case FrameFilterMode::Clahe: return "clahe";
    case FrameFilterMode::Denoise: return "denoise";
    case FrameFilterMode::Sharpen: return "sharpen";
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
    case FrameFilterMode::Denoise:
        cv::bilateralFilter(frame, frame, 5, 50, 50);
        break;
    case FrameFilterMode::Sharpen: {
        cv::Mat blurred;
        cv::GaussianBlur(frame, blurred, cv::Size(0, 0), 1.2);
        cv::addWeighted(frame, 1.4, blurred, -0.4, 0, frame);
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
