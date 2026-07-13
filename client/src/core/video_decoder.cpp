#include "core/video_decoder.h"



#include "common/ffmpeg_compat.h"
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

    FrameProcessor frameProcessor;

};



VideoDecoder::VideoDecoder() : impl_(std::make_unique<Impl>()) {}



VideoDecoder::~VideoDecoder() {

    close();

}



bool VideoDecoder::open(const std::string& filePath) {

    close();



    if (!common::fileExists(filePath)) {

        LOG_ERROR("视频文件不存在: " + filePath);

        return false;

    }



    const std::string ext = common::getFileExtension(filePath);

    static const char* kSupported[] = {"mp4", "mov", "avi", "flv", "mkv", "wmv", "webm"};

    bool supported = false;

    for (const char* s : kSupported) {

        if (ext == s) { supported = true; break; }

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



    int videoIdx = -1;

    AVCodecContext* codecCtx = nullptr;

    if (!common::openVideoDecoder(fmtCtx, videoIdx, &codecCtx)) {

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



    LOG_INFO("已打开视频: " + filePath

        + " [" + std::to_string(impl_->info.width) + "x" + std::to_string(impl_->info.height)

        + ", " + std::to_string(impl_->info.durationSec) + "s]");



    return true;

}



void VideoDecoder::close() {

    if (!impl_) return;

    common::freeCodecContext(&impl_->codecCtx);

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



    SwsContext* swsCtx = sws_getContext(w, h, impl_->codecCtx->pix_fmt,

        w, h, AV_PIX_FMT_RGB24, SWS_BILINEAR, nullptr, nullptr, nullptr);



    bool found = false;

    while (av_read_frame(impl_->formatCtx, &packet) >= 0) {

        if (packet.stream_index == impl_->videoStreamIndex) {

            if (common::decodeVideoPacket(impl_->codecCtx, &packet, frame)) {

                sws_scale(swsCtx, frame->data, frame->linesize, 0, h,

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



    sws_freeContext(swsCtx);

    av_free(outBuf);

    av_frame_free(&frame);

    av_frame_free(&rgbFrame);

    return found;

}



} // namespace media::core

