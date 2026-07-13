#pragma once

struct AVCodecContext;
struct AVFrame;
struct AVBufferRef;
struct AVCodec;

namespace media::common {

/// FFmpeg 视频硬解上下文（Windows x64：D3D11VA）
struct HwAccelContext {
    bool requested = false;
    bool active = false;
    int hw_pix_fmt = -1;
    AVBufferRef* hw_device_ctx = nullptr;
};

#if defined(MUSIC_FFMPEG_HWACCEL) && MUSIC_FFMPEG_HWACCEL

bool prepareVideoHwAccel(AVCodecContext* ctx, const AVCodec* codec, HwAccelContext* hw);
void releaseVideoHwAccel(HwAccelContext* hw);
bool isHwAcceleratedFrame(const AVFrame* frame, const HwAccelContext* hw);
bool transferHwFrameToSoftware(const AVFrame* hw_frame, AVFrame* sw_frame);
const char* hwAccelDisplayName(const HwAccelContext* hw);

#else

inline bool prepareVideoHwAccel(AVCodecContext*, const AVCodec*, HwAccelContext*) { return false; }
inline void releaseVideoHwAccel(HwAccelContext*) {}
inline bool isHwAcceleratedFrame(const AVFrame*, const HwAccelContext*) { return false; }
inline bool transferHwFrameToSoftware(const AVFrame*, AVFrame*) { return false; }
inline const char* hwAccelDisplayName(const HwAccelContext*) { return "cpu"; }

#endif

} // namespace media::common
