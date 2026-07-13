#pragma once

#include <cstdint>

struct AVCodecContext;
struct AVFormatContext;
struct AVFrame;
struct AVPacket;
struct AVStream;

namespace media::common {

struct HwAccelContext;

/// 初始化 FFmpeg（旧版需 av_register_all）
void ffmpegInit();

enum class AVMediaKind { Video, Audio };

bool streamIsType(const AVStream* stream, AVMediaKind kind);

/// 打开视频解码器；hw 非空且 requested 时尝试 D3D11VA 硬解，失败自动回退 CPU
bool openVideoDecoder(AVFormatContext* fmt, int& videoStreamIndex, AVCodecContext** codecCtx,
    HwAccelContext* hw = nullptr);

bool openAudioDecoder(AVFormatContext* fmt, int& audioStreamIndex, AVCodecContext** codecCtx);

void freeCodecContext(AVCodecContext** codecCtx);

void flushCodec(AVCodecContext* codecCtx);

/// 送入一个视频 packet，尝试取出一帧；返回 true 表示 *frame 有效
bool decodeVideoPacket(AVCodecContext* ctx, AVPacket* packet, AVFrame* frame);

bool decodeAudioPacket(AVCodecContext* ctx, AVPacket* packet, AVFrame* frame);

void packetUnref(AVPacket* packet);

double frameTimestampSec(const AVFrame* frame, const AVStream* stream, double fallbackSec);

} // namespace media::common
