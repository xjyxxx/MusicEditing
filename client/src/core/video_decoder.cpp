#include "core/video_decoder.h"

#include "common/ffmpeg_compat.h"
#include "common/ffmpeg_hwaccel.h"
#include "common/file_path.h"
#include "common/logger.h"
#include "common/utils.h"
#include "core/frame_processor.h"

#define __STDC_CONSTANT_MACROS

#ifdef _WIN32
extern "C" {
#include "libavcodec/avcodec.h"
#include "libavformat/avformat.h"
#include "libswscale/swscale.h"
#include "libavutil/imgutils.h"
#include "libavutil/rational.h"
}
#else
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libswscale/swscale.h>
#include <libavutil/imgutils.h>
#include <libavutil/rational.h>
}
#endif

#include <cmath>
#include <cstring>

namespace media::core {

struct VideoDecoder::Impl {
    AVFormatContext* formatCtx = nullptr;
    AVCodecContext* codecCtx = nullptr;
    int videoStreamIndex = -1;
    common::VideoInfo info;
    bool opened = false;
    common::HwAccelContext hw{};
    AVFrame* swTransferFrame = nullptr;
    FrameProcessor frameProcessor;
};

VideoDecoder::VideoDecoder() : impl_(std::make_unique<Impl>()) {}

VideoDecoder::~VideoDecoder() {
    close();
}

bool VideoDecoder::open(const std::string& filePath, bool preferHwaccel) {
    close();

    if (!common::fileExists(filePath)) {
        LOG_ERROR("视频文件不存在: " + filePath);
        return false;
    }

    const std::string ext = common::getFileExtension(filePath);
    static const char* kSupported[] = {"mp4", "mov", "avi", "flv", "mkv", "wmv", "webm"};
    bool supported = false;
    for (const char* s : kSupported) {
        if (ext == s) {
            supported = true;
            break;
        }
    }
    if (!supported) {
        LOG_WARN("文件格式可能不受支持: " + ext);
    }

    common::ffmpegInit();

    AVFormatContext* fmtCtx = nullptr;
    if (avformat_open_input(&fmtCtx, common::pathForFfmpeg(filePath).c_str(), nullptr, nullptr) != 0) {
        LOG_ERROR("无法打开视频: " + filePath);
        return false;
    }

    if (avformat_find_stream_info(fmtCtx, nullptr) < 0) {
        LOG_ERROR("无法读取流信息: " + filePath);
        avformat_close_input(&fmtCtx);
        return false;
    }

    impl_->hw = {};
    impl_->hw.requested = preferHwaccel;
    LOG_INFO(std::string("VideoDecoder 硬解请求=") + (preferHwaccel ? "on" : "off"));

    int videoIdx = -1;
    AVCodecContext* codecCtx = nullptr;
    if (!common::openVideoDecoder(fmtCtx, videoIdx, &codecCtx, &impl_->hw)) {
        LOG_ERROR("未找到视频流或无法打开解码器: " + filePath);
        avformat_close_input(&fmtCtx);
        return false;
    }

    const AVCodec* codec = codecCtx->codec;
    AVRational frameRate = fmtCtx->streams[videoIdx]->avg_frame_rate;
    double fps = 25.0;
    if (frameRate.num > 0 && frameRate.den > 0) {
        fps = av_q2d(frameRate);
    }

    int64_t totalFrames = 0;
    if (fmtCtx->streams[videoIdx]->nb_frames > 0) {
        totalFrames = fmtCtx->streams[videoIdx]->nb_frames;
    } else if (fmtCtx->duration > 0 && fps > 0) {
        totalFrames = static_cast<int64_t>(
            (fmtCtx->duration / static_cast<double>(AV_TIME_BASE)) * fps);
    }

    impl_->formatCtx = fmtCtx;
    impl_->codecCtx = codecCtx;
    impl_->videoStreamIndex = videoIdx;
    impl_->swTransferFrame = av_frame_alloc();
    impl_->opened = true;

    impl_->info.filePath = filePath;
    impl_->info.width = codecCtx->width;
    impl_->info.height = codecCtx->height;
    impl_->info.durationSec = fmtCtx->duration > 0
        ? fmtCtx->duration / static_cast<double>(AV_TIME_BASE) : 0.0;
    impl_->info.fps = fps;
    impl_->info.totalFrames = totalFrames;
    impl_->info.codecName = codec ? codec->name : "unknown";
    impl_->info.formatName = fmtCtx->iformat ? fmtCtx->iformat->name : "unknown";

    if (impl_->hw.active) {
        LOG_INFO("VideoDecoder 硬解已启用: "
            + std::string(common::hwAccelDisplayName(&impl_->hw))
            + " codec=" + impl_->info.codecName);
    } else if (impl_->hw.requested) {
        LOG_WARN("VideoDecoder 硬解不可用，使用 CPU 解码 codec=" + impl_->info.codecName);
    } else {
        LOG_INFO("VideoDecoder CPU 解码 codec=" + impl_->info.codecName);
    }

    LOG_INFO("已打开视频: " + filePath
        + " [" + std::to_string(impl_->info.width) + "x" + std::to_string(impl_->info.height)
        + ", " + std::to_string(impl_->info.durationSec) + "s]");

    return true;
}

void VideoDecoder::close() {
    if (!impl_) return;

    if (impl_->swTransferFrame) {
        av_frame_free(&impl_->swTransferFrame);
    }
    if (impl_->codecCtx) {
        impl_->codecCtx->opaque = nullptr;
    }
    common::freeCodecContext(&impl_->codecCtx);
    common::releaseVideoHwAccel(&impl_->hw);
    if (impl_->formatCtx) {
        avformat_close_input(&impl_->formatCtx);
        impl_->formatCtx = nullptr;
    }
    impl_->videoStreamIndex = -1;
    impl_->opened = false;
    impl_->info = {};
}

bool VideoDecoder::isOpen() const {
    return impl_ && impl_->opened;
}

bool VideoDecoder::isHwAccelActive() const {
    return impl_ && impl_->opened && impl_->hw.active;
}

const common::VideoInfo& VideoDecoder::info() const {
    return impl_->info;
}

bool VideoDecoder::iterateFrames(FrameCallback callback) {
    if (!isOpen() || !callback) return false;

    AVPacket packet;
    std::memset(&packet, 0, sizeof(packet));
    AVFrame* frame = av_frame_alloc();
    if (!frame) return false;

    int64_t frameIndex = 0;
    bool success = true;
    const AVStream* vstream = impl_->formatCtx->streams[impl_->videoStreamIndex];

    while (av_read_frame(impl_->formatCtx, &packet) >= 0) {
        if (packet.stream_index == impl_->videoStreamIndex) {
            if (common::decodeVideoPacket(impl_->codecCtx, &packet, frame)) {
                // 硬解帧仅需时间戳即可，unref 会释放 GPU 表面，无需 download
                const double ts = common::frameTimestampSec(
                    frame, vstream, frameIndex / impl_->info.fps);

                if (!callback(frameIndex, ts)) {
                    common::packetUnref(&packet);
                    break;
                }
                ++frameIndex;
            }
        }
        common::packetUnref(&packet);
    }

    av_frame_free(&frame);
    return success;
}

bool VideoDecoder::extractThumbnail(double timestampSec, unsigned char* rgbBuffer, int bufferSize) {
    if (!isOpen() || !rgbBuffer) return false;

    const int w = impl_->info.width;
    const int h = impl_->info.height;
    const int required = w * h * 3;
    if (bufferSize < required) return false;

    av_seek_frame(impl_->formatCtx, impl_->videoStreamIndex,
        static_cast<int64_t>(timestampSec * AV_TIME_BASE), AVSEEK_FLAG_BACKWARD);

    common::flushCodec(impl_->codecCtx);

    AVPacket packet;
    std::memset(&packet, 0, sizeof(packet));
    AVFrame* frame = av_frame_alloc();
    AVFrame* rgbFrame = av_frame_alloc();
    if (!frame || !rgbFrame) {
        av_frame_free(&frame);
        av_frame_free(&rgbFrame);
        return false;
    }

    unsigned char* outBuf = static_cast<unsigned char*>(
        av_malloc(static_cast<size_t>(av_image_get_buffer_size(AV_PIX_FMT_RGB24, w, h, 1))));
    av_image_fill_arrays(rgbFrame->data, rgbFrame->linesize, outBuf,
        AV_PIX_FMT_RGB24, w, h, 1);

    SwsContext* swsCtx = nullptr;
    bool found = false;

    while (av_read_frame(impl_->formatCtx, &packet) >= 0) {
        if (packet.stream_index == impl_->videoStreamIndex) {
            if (common::decodeVideoPacket(impl_->codecCtx, &packet, frame)) {
                const AVFrame* scaleFrame = frame;
                if (common::isHwAcceleratedFrame(frame, &impl_->hw)) {
                    if (!impl_->swTransferFrame) {
                        impl_->swTransferFrame = av_frame_alloc();
                    }
                    av_frame_unref(impl_->swTransferFrame);
                    if (!common::transferHwFrameToSoftware(frame, impl_->swTransferFrame)) {
                        common::packetUnref(&packet);
                        break;
                    }
                    scaleFrame = impl_->swTransferFrame;
                }

                const AVPixelFormat srcFmt = static_cast<AVPixelFormat>(scaleFrame->format);
                if (!swsCtx) {
                    swsCtx = sws_getContext(w, h, srcFmt,
                        w, h, AV_PIX_FMT_RGB24, SWS_BILINEAR, nullptr, nullptr, nullptr);
                    if (!swsCtx) {
                        common::packetUnref(&packet);
                        break;
                    }
                }

                sws_scale(swsCtx, scaleFrame->data, scaleFrame->linesize, 0, h,
                    rgbFrame->data, rgbFrame->linesize);

                impl_->frameProcessor.processRgbFrame(outBuf, w, h, w * 3);
                std::memcpy(rgbBuffer, outBuf, static_cast<size_t>(required));
                found = true;
                common::packetUnref(&packet);
                break;
            }
        }
        common::packetUnref(&packet);
    }

    if (swsCtx) {
        sws_freeContext(swsCtx);
    }
    av_free(outBuf);
    av_frame_free(&frame);
    av_frame_free(&rgbFrame);
    return found;
}

} // namespace media::core
