#include "common/ffmpeg_compat.h"
#include "common/ffmpeg_hwaccel.h"

#define __STDC_CONSTANT_MACROS

#ifdef _WIN32
extern "C" {
#include "libavcodec/avcodec.h"
#include "libavformat/avformat.h"
#include "libavutil/avutil.h"
}
#else
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/avutil.h>
}
#endif

namespace media::common {

#if LIBAVCODEC_VERSION_INT >= AV_VERSION_INT(59, 0, 0)
#define MUSIC_FFMPEG_MODERN 1
#else
#define MUSIC_FFMPEG_MODERN 0
#endif

void ffmpegInit() {
#if !MUSIC_FFMPEG_MODERN
    av_register_all();
#endif
    avformat_network_init();
}

bool streamIsType(const AVStream* stream, AVMediaKind kind) {
    if (!stream) return false;
    const AVMediaType want = kind == AVMediaKind::Video ? AVMEDIA_TYPE_VIDEO : AVMEDIA_TYPE_AUDIO;
#if MUSIC_FFMPEG_MODERN
    return stream->codecpar && stream->codecpar->codec_type == want;
#else
    return stream->codec && stream->codec->codec_type == want;
#endif
}

static bool openDecoderFromStream(AVStream* stream, AVCodecContext** outCtx, HwAccelContext* hw) {
    if (!stream || !outCtx) return false;
    *outCtx = nullptr;

#if MUSIC_FFMPEG_MODERN
    const AVCodecParameters* par = stream->codecpar;
    if (!par) return false;
    const AVCodec* codec = avcodec_find_decoder(par->codec_id);
    if (!codec) return false;
    AVCodecContext* ctx = avcodec_alloc_context3(codec);
    if (!ctx) return false;
    if (avcodec_parameters_to_context(ctx, par) < 0) {
        avcodec_free_context(&ctx);
        return false;
    }

    const bool wantHw = hw && hw->requested;
    if (wantHw) {
        prepareVideoHwAccel(ctx, codec, hw);
        ctx->extra_hw_frames = 8;
        ctx->thread_count = 1;
    }

    if (avcodec_open2(ctx, codec, nullptr) < 0) {
        if (wantHw && hw->hw_device_ctx) {
            ctx->get_format = nullptr;
            ctx->opaque = nullptr;
            if (ctx->hw_device_ctx) {
                av_buffer_unref(&ctx->hw_device_ctx);
            }
            releaseVideoHwAccel(hw);
            if (avcodec_open2(ctx, codec, nullptr) < 0) {
                avcodec_free_context(&ctx);
                return false;
            }
        } else {
            avcodec_free_context(&ctx);
            return false;
        }
    }

    if (wantHw && hw->hw_device_ctx) {
        hw->active = true;
    }
    *outCtx = ctx;
    return true;
#else
    (void)hw;
    AVCodecContext* ctx = stream->codec;
    const AVCodec* codec = avcodec_find_decoder(ctx->codec_id);
    if (!codec || avcodec_open2(ctx, codec, nullptr) < 0) return false;
    *outCtx = ctx;
    return true;
#endif
}

bool openVideoDecoder(AVFormatContext* fmt, int& videoStreamIndex, AVCodecContext** codecCtx,
    HwAccelContext* hw) {
    videoStreamIndex = -1;
    if (!fmt || !codecCtx) return false;

    for (unsigned i = 0; i < fmt->nb_streams; ++i) {
        if (streamIsType(fmt->streams[i], AVMediaKind::Video)) {
            videoStreamIndex = static_cast<int>(i);
            return openDecoderFromStream(fmt->streams[videoStreamIndex], codecCtx, hw);
        }
    }
    return false;
}

bool openAudioDecoder(AVFormatContext* fmt, int& audioStreamIndex, AVCodecContext** codecCtx) {
    audioStreamIndex = -1;
    if (!fmt || !codecCtx) return false;

    for (unsigned i = 0; i < fmt->nb_streams; ++i) {
        if (streamIsType(fmt->streams[i], AVMediaKind::Audio)) {
            audioStreamIndex = static_cast<int>(i);
            return openDecoderFromStream(fmt->streams[audioStreamIndex], codecCtx, nullptr);
        }
    }
    return false;
}

void freeCodecContext(AVCodecContext** codecCtx) {
    if (!codecCtx || !*codecCtx) return;
#if MUSIC_FFMPEG_MODERN
    avcodec_free_context(codecCtx);
#else
    avcodec_close(*codecCtx);
    *codecCtx = nullptr;
#endif
}

void flushCodec(AVCodecContext* codecCtx) {
    if (codecCtx) avcodec_flush_buffers(codecCtx);
}

#if MUSIC_FFMPEG_MODERN
static bool receiveOneFrame(AVCodecContext* ctx, AVFrame* frame) {
    return avcodec_receive_frame(ctx, frame) == 0;
}

bool decodeVideoPacket(AVCodecContext* ctx, AVPacket* packet, AVFrame* frame) {
    if (!ctx || !frame) return false;

    if (packet) {
        const int ret = avcodec_send_packet(ctx, packet);
        if (ret < 0 && ret != AVERROR(EAGAIN) && ret != AVERROR_EOF) {
            return false;
        }
    } else {
        avcodec_send_packet(ctx, nullptr);
    }

    return receiveOneFrame(ctx, frame);
}

bool decodeAudioPacket(AVCodecContext* ctx, AVPacket* packet, AVFrame* frame) {
    return decodeVideoPacket(ctx, packet, frame);
}
#else
bool decodeVideoPacket(AVCodecContext* ctx, AVPacket* packet, AVFrame* frame) {
    if (!ctx || !packet || !frame) return false;
    int got = 0;
    if (avcodec_decode_video2(ctx, frame, &got, packet) < 0) return false;
    return got != 0;
}

bool decodeAudioPacket(AVCodecContext* ctx, AVPacket* packet, AVFrame* frame) {
    if (!ctx || !packet || !frame) return false;
    int got = 0;
    if (avcodec_decode_audio4(ctx, frame, &got, packet) < 0) return false;
    return got != 0;
}
#endif

void packetUnref(AVPacket* packet) {
    if (!packet) return;
#if MUSIC_FFMPEG_MODERN
    av_packet_unref(packet);
#else
    av_free_packet(packet);
    av_init_packet(packet);
#endif
}

double frameTimestampSec(const AVFrame* frame, const AVStream* stream, double fallbackSec) {
    if (frame && frame->pts != AV_NOPTS_VALUE && stream) {
        return frame->pts * av_q2d(stream->time_base);
    }
    return fallbackSec;
}

} // namespace media::common

#undef MUSIC_FFMPEG_MODERN
