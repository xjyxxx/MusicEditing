#include "core/video_player_engine.h"

#include "core/frame_processor.h"

#include "common/file_path.h"
#include "common/ffmpeg_compat.h"
#include "common/ffmpeg_hwaccel.h"
#include "common/logger.h"

#define __STDC_CONSTANT_MACROS

#ifdef _WIN32
extern "C" {
#include "libavcodec/avcodec.h"
#include "libavformat/avformat.h"
#include "libswscale/swscale.h"
#include "libavutil/imgutils.h"
#include "libavutil/pixfmt.h"
}
#else
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libswscale/swscale.h>
#include <libavutil/imgutils.h>
#include <libavutil/mathematics.h>
#include <libavutil/pixfmt.h>
}
#endif

#include <chrono>
#include <cstdio>
#include <cstring>
#include <vector>

namespace media::core {

struct VideoPlayerEngine::Impl {
    AVFormatContext* formatCtx = nullptr;
    AVCodecContext* codecCtx = nullptr;
    SwsContext* swsCtx = nullptr;
    int swsSrcFmt = -1;
    int videoStreamIndex = -1;
    bool hasAudioStream = false;
    common::VideoInfo info;
    common::HwAccelContext hw;
    FrameProcessor frameProcessor;
    AVFrame* swTransferFrame = nullptr;
    bool opened = false;
    bool eof = false;
    double lastTimestamp = 0.0;
    int framesOutput = 0;
    int slowFrameCount = 0;
    int playbackScaleW = 0;
    int playbackScaleH = 0;
    int swsDstW = 0;
    int swsDstH = 0;
    bool needKeyFrameAfterSeek = false;
    double seekTargetSec = 0.0;
    bool seekTargetPending = false;
};

VideoPlayerEngine::VideoPlayerEngine() : impl_(std::make_unique<Impl>()) {}

VideoPlayerEngine::~VideoPlayerEngine() {
    close();
}

void VideoPlayerEngine::ensureSwsContext(int srcW, int srcH, int srcPixFmt) {
    if (!impl_) return;
    const int dstW = impl_->playbackScaleW > 0 ? impl_->playbackScaleW : srcW;
    const int dstH = impl_->playbackScaleH > 0 ? impl_->playbackScaleH : srcH;
    if (impl_->swsCtx && impl_->swsSrcFmt == srcPixFmt
        && impl_->swsDstW == dstW && impl_->swsDstH == dstH) {
        return;
    }
    if (impl_->swsCtx) {
        sws_freeContext(impl_->swsCtx);
        impl_->swsCtx = nullptr;
    }
    impl_->swsCtx = sws_getContext(
        srcW, srcH, static_cast<AVPixelFormat>(srcPixFmt),
        dstW, dstH, AV_PIX_FMT_RGB24, SWS_FAST_BILINEAR, nullptr, nullptr, nullptr);
    impl_->swsSrcFmt = srcPixFmt;
    impl_->swsDstW = dstW;
    impl_->swsDstH = dstH;
}

void VideoPlayerEngine::setPlaybackScale(int width, int height) {
    if (!impl_) return;
    impl_->playbackScaleW = width > 0 ? width : 0;
    impl_->playbackScaleH = height > 0 ? height : 0;
    if (impl_->swsCtx) {
        sws_freeContext(impl_->swsCtx);
        impl_->swsCtx = nullptr;
    }
    impl_->swsSrcFmt = -1;
    impl_->swsDstW = 0;
    impl_->swsDstH = 0;
    if (width > 0 && height > 0) {
        LOG_INFO("playback scale " + std::to_string(width) + "x" + std::to_string(height));
    } else {
        LOG_INFO("playback scale 原始分辨率");
    }
}

bool VideoPlayerEngine::open(const std::string& filePath) {
    close();

    common::ffmpegInit();
    LOG_INFO("open 开始 path=" + filePath);

    AVFormatContext* fmtCtx = nullptr;
    const std::string nativePath = common::pathForFfmpeg(filePath);
    if (avformat_open_input(&fmtCtx, nativePath.c_str(), nullptr, nullptr) != 0) {
        LOG_ERROR("播放器无法打开: " + filePath);
        return false;
    }
    if (avformat_find_stream_info(fmtCtx, nullptr) < 0) {
        avformat_close_input(&fmtCtx);
        LOG_ERROR("find_stream_info 失败");
        return false;
    }

    bool hasAudio = false;
    for (unsigned i = 0; i < fmtCtx->nb_streams; ++i) {
        if (common::streamIsType(fmtCtx->streams[i], common::AVMediaKind::Audio)) {
            hasAudio = true;
        }
    }

    impl_->hw = {};
    impl_->hw.requested = hwAccelPreferred_;
    LOG_INFO(std::string("硬解请求=") + (hwAccelPreferred_ ? "on" : "off"));

    int videoIdx = -1;
    AVCodecContext* codecCtx = nullptr;
    if (!common::openVideoDecoder(fmtCtx, videoIdx, &codecCtx, &impl_->hw)) {
        avformat_close_input(&fmtCtx);
        LOG_ERROR("openVideoDecoder 失败");
        return false;
    }

    const AVCodec* codec = codecCtx->codec;
    const int w = codecCtx->width;
    const int h = codecCtx->height;

    AVRational frameRate = fmtCtx->streams[videoIdx]->avg_frame_rate;
    double fps = 25.0;
    if (frameRate.num > 0 && frameRate.den > 0) {
        fps = av_q2d(frameRate);
    }

    impl_->formatCtx = fmtCtx;
    impl_->codecCtx = codecCtx;
    impl_->videoStreamIndex = videoIdx;
    impl_->hasAudioStream = hasAudio;
    impl_->swsCtx = nullptr;
    impl_->swsSrcFmt = -1;
    impl_->swTransferFrame = av_frame_alloc();
    impl_->opened = true;
    impl_->eof = false;
    impl_->lastTimestamp = 0.0;
    impl_->framesOutput = 0;
    impl_->slowFrameCount = 0;

    impl_->info.filePath = filePath;
    impl_->info.width = w;
    impl_->info.height = h;
    impl_->info.durationSec = fmtCtx->duration > 0
        ? fmtCtx->duration / static_cast<double>(AV_TIME_BASE) : 0.0;
    impl_->info.fps = fps;
    impl_->info.codecName = codec ? codec->name : "unknown";
    impl_->info.formatName = fmtCtx->iformat ? fmtCtx->iformat->name : "unknown";

    if (impl_->hw.active) {
        LOG_INFO("播放器硬解已启用: D3D11VA codec=" + impl_->info.codecName);
    } else if (impl_->hw.requested) {
        LOG_WARN("播放器硬解不可用，使用 CPU 解码 codec=" + impl_->info.codecName);
    } else {
        LOG_INFO("播放器 CPU 解码 codec=" + impl_->info.codecName);
    }
    LOG_INFO("open 成功 " + std::to_string(w) + "x" + std::to_string(h)
        + " fps=" + std::to_string(fps) + " duration=" + std::to_string(impl_->info.durationSec));
    return true;
}

void VideoPlayerEngine::close() {
    if (!impl_) return;
    LOG_DEBUG("close 播放器");
    if (impl_->swsCtx) {
        sws_freeContext(impl_->swsCtx);
        impl_->swsCtx = nullptr;
    }
    if (impl_->codecCtx) {
        impl_->codecCtx->opaque = nullptr;
    }
    if (impl_->swTransferFrame) {
        av_frame_free(&impl_->swTransferFrame);
        impl_->swTransferFrame = nullptr;
    }
    common::releaseVideoHwAccel(&impl_->hw);
    common::freeCodecContext(&impl_->codecCtx);
    if (impl_->formatCtx) {
        avformat_close_input(&impl_->formatCtx);
        impl_->formatCtx = nullptr;
    }
    impl_->videoStreamIndex = -1;
    impl_->hasAudioStream = false;
    impl_->swsSrcFmt = -1;
    impl_->opened = false;
    impl_->eof = false;
    impl_->playbackScaleW = 0;
    impl_->playbackScaleH = 0;
    impl_->info = {};
}

bool VideoPlayerEngine::isOpen() const {
    return impl_ && impl_->opened;
}

const common::VideoInfo& VideoPlayerEngine::info() const {
    return impl_->info;
}

bool VideoPlayerEngine::hasAudioStream() const {
    return impl_ && impl_->hasAudioStream;
}

bool VideoPlayerEngine::isHwAccelActive() const {
    return impl_ && impl_->hw.active;
}

std::string VideoPlayerEngine::hwAccelName() const {
    if (!impl_) return "cpu";
    return common::hwAccelDisplayName(&impl_->hw);
}

bool VideoPlayerEngine::seek(double timestampSec) {
    if (!isOpen()) return false;
    impl_->eof = false;

    LOG_INFO("seek -> " + std::to_string(timestampSec));
    const AVStream* vstream = impl_->formatCtx->streams[impl_->videoStreamIndex];
    const int64_t ts = av_rescale_q(
        static_cast<int64_t>(timestampSec * AV_TIME_BASE),
        AV_TIME_BASE_Q, vstream->time_base);
    if (av_seek_frame(impl_->formatCtx, impl_->videoStreamIndex, ts, AVSEEK_FLAG_BACKWARD) < 0) {
        LOG_WARN("seek 失败 ts=" + std::to_string(timestampSec));
        return false;
    }
    common::flushCodec(impl_->codecCtx);
    impl_->needKeyFrameAfterSeek = true;
    impl_->seekTargetSec = timestampSec;
    impl_->seekTargetPending = timestampSec > 0.001;
    impl_->lastTimestamp = timestampSec;
    return true;
}

bool VideoPlayerEngine::decodeNextFrameToFile(
    const std::string& rgbFilePath, DecodeFrameResult* result,
    double minTimestampSec, bool applyFilter) {
    if (!isOpen() || impl_->eof) {
        return false;
    }

    const auto t0 = std::chrono::steady_clock::now();
    const int srcW = impl_->info.width;
    const int srcH = impl_->info.height;
    const int dstW = impl_->playbackScaleW > 0 ? impl_->playbackScaleW : srcW;
    const int dstH = impl_->playbackScaleH > 0 ? impl_->playbackScaleH : srcH;
    const int bufSize = av_image_get_buffer_size(AV_PIX_FMT_RGB24, dstW, dstH, 1);
    if (bufSize <= 0) {
        return false;
    }
    const bool catchUp = minTimestampSec >= 0.0;

    AVPacket packet;
    std::memset(&packet, 0, sizeof(packet));
    AVFrame* frame = av_frame_alloc();
    AVFrame* rgbFrame = av_frame_alloc();
    if (!frame || !rgbFrame) {
        av_frame_free(&frame);
        av_frame_free(&rgbFrame);
        return false;
    }

    std::vector<uint8_t> rgbBuf(static_cast<size_t>(bufSize));
    av_image_fill_arrays(rgbFrame->data, rgbFrame->linesize, rgbBuf.data(),
        AV_PIX_FMT_RGB24, dstW, dstH, 1);
    const int rgbStride = rgbFrame->linesize[0];
    const int rowBytes = dstW * 3;

    int skipped = 0;
    bool gotFrame = false;
    bool hwTransfer = false;
    double ts = impl_->lastTimestamp;
    const AVStream* vstream = impl_->formatCtx->streams[impl_->videoStreamIndex];
    const double frameStep = impl_->info.fps > 0 ? 1.0 / impl_->info.fps : 0.04;

    bool writeFailed = false;
    auto tryOutputFrame = [&](AVFrame* decoded) -> bool {
        ts = common::frameTimestampSec(decoded, vstream, ts + frameStep);

        if (impl_->needKeyFrameAfterSeek) {
            const bool isKey = (decoded->flags & AV_FRAME_FLAG_KEY) != 0
                || decoded->pict_type == AV_PICTURE_TYPE_I;
            if (!isKey) {
                ++skipped;
                impl_->lastTimestamp = ts;
                return false;
            }
            impl_->needKeyFrameAfterSeek = false;
        }

        if (impl_->seekTargetPending && ts + frameStep * 0.5 < impl_->seekTargetSec) {
            ++skipped;
            impl_->lastTimestamp = ts;
            return false;
        }
        impl_->seekTargetPending = false;

        if (catchUp && ts + frameStep * 0.15 < minTimestampSec) {
            ++skipped;
            impl_->lastTimestamp = ts;
            return false;
        }

        const AVFrame* scaleFrame = decoded;
        if (common::isHwAcceleratedFrame(decoded, &impl_->hw)) {
            hwTransfer = true;
            if (!impl_->swTransferFrame) {
                impl_->swTransferFrame = av_frame_alloc();
            }
            av_frame_unref(impl_->swTransferFrame);
            if (!common::transferHwFrameToSoftware(decoded, impl_->swTransferFrame)) {
                return false;
            }
            scaleFrame = impl_->swTransferFrame;
        }

        ensureSwsContext(srcW, srcH, scaleFrame->format);
        if (!impl_->swsCtx) {
            return false;
        }

        sws_scale(impl_->swsCtx, scaleFrame->data, scaleFrame->linesize, 0, srcH,
            rgbFrame->data, rgbFrame->linesize);

        const bool doFilter = applyFilter && impl_->frameProcessor.isEnabled();
        if (doFilter) {
            if (!impl_->frameProcessor.processRgbFrame(
                    rgbFrame->data[0], dstW, dstH, rgbStride)) {
                return false;
            }
        }

        const std::string tmpPath = rgbFilePath + ".part";
        FILE* fp = std::fopen(tmpPath.c_str(), "wb");
        if (!fp) {
            LOG_ERROR("无法写入帧文件: " + tmpPath);
            writeFailed = true;
            return false;
        }
        for (int y = 0; y < dstH; ++y) {
            const uint8_t* row = rgbFrame->data[0] + static_cast<ptrdiff_t>(y) * rgbStride;
            if (std::fwrite(row, 1, static_cast<size_t>(rowBytes), fp) != static_cast<size_t>(rowBytes)) {
                LOG_ERROR("写入帧行失败 y=" + std::to_string(y));
                std::fclose(fp);
                std::remove(tmpPath.c_str());
                writeFailed = true;
                return false;
            }
        }
        std::fflush(fp);
        std::fclose(fp);
        std::remove(rgbFilePath.c_str());
        if (std::rename(tmpPath.c_str(), rgbFilePath.c_str()) != 0) {
            LOG_ERROR("帧文件替换失败: " + rgbFilePath);
            writeFailed = true;
            return false;
        }

        impl_->lastTimestamp = ts;
        return true;
    };

    while (!gotFrame && !writeFailed) {
        const int recvRet = avcodec_receive_frame(impl_->codecCtx, frame);
        if (recvRet == 0) {
            if (tryOutputFrame(frame)) {
                gotFrame = true;
            }
            av_frame_unref(frame);
            continue;
        }
        if (recvRet == AVERROR_EOF) {
            break;
        }
        if (recvRet != AVERROR(EAGAIN)) {
            break;
        }

        if (av_read_frame(impl_->formatCtx, &packet) < 0) {
            break;
        }
        if (packet.stream_index != impl_->videoStreamIndex) {
            common::packetUnref(&packet);
            continue;
        }

        const int sendRet = avcodec_send_packet(impl_->codecCtx, &packet);
        common::packetUnref(&packet);
        if (sendRet < 0 && sendRet != AVERROR(EAGAIN)) {
            continue;
        }
    }

    if (writeFailed) {
        av_frame_free(&frame);
        av_frame_free(&rgbFrame);
        return false;
    }

    av_frame_free(&frame);
    av_frame_free(&rgbFrame);

    if (!gotFrame) {
        impl_->eof = true;
        LOG_DEBUG("decode 到达 EOF");
        return false;
    }

    const int decodeMs = static_cast<int>(
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - t0).count());

    if (result) {
        result->timestampSec = ts;
        result->skippedFrames = skipped;
        result->decodeMs = decodeMs;
        result->hwTransfer = hwTransfer;
        result->width = dstW;
        result->height = dstH;
    }

    ++impl_->framesOutput;
    if (decodeMs > 40) {
        ++impl_->slowFrameCount;
    }

    if (impl_->framesOutput <= 3 || impl_->framesOutput % 120 == 0 || decodeMs > 40) {
        LOG_DEBUG("decode ts=" + std::to_string(ts)
            + " ms=" + std::to_string(decodeMs)
            + " skipped=" + std::to_string(skipped)
            + " hw=" + (hwTransfer ? "1" : "0")
            + " filter=" + (applyFilter ? impl_->frameProcessor.modeName() : "off"));
    }

    if (impl_->hw.active && impl_->framesOutput == 60 && impl_->slowFrameCount > 20) {
        LOG_WARN("硬解+渲染偏慢: 60帧中 " + std::to_string(impl_->slowFrameCount)
            + " 帧>40ms，建议 opencv_filter_playback=off 或 HWACCEL off");
    }

    return true;
}

bool VideoPlayerEngine::setFrameFilter(const std::string& name) {
    if (!impl_) return false;
    const bool ok = impl_->frameProcessor.setModeFromString(name);
    if (ok) {
        LOG_INFO("帧滤镜 -> " + impl_->frameProcessor.modeName());
    } else {
        LOG_WARN("无效帧滤镜: " + name);
    }
    return ok;
}

std::string VideoPlayerEngine::frameFilterName() const {
    if (!impl_) return "off";
    return impl_->frameProcessor.modeName();
}

} // namespace media::core
