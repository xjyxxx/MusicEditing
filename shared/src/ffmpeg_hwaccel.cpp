#include "common/ffmpeg_hwaccel.h"

#include "common/logger.h"

#define __STDC_CONSTANT_MACROS

#ifdef _WIN32
extern "C" {
#include "libavcodec/avcodec.h"
#include "libavutil/frame.h"
#include "libavutil/hwcontext.h"
#include "libavutil/pixfmt.h"
}
#else
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavutil/frame.h>
#include <libavutil/hwcontext.h>
#include <libavutil/pixfmt.h>
}
#endif

namespace media::common {

namespace {

enum AVPixelFormat getHwFormat(AVCodecContext* ctx, const enum AVPixelFormat* pix_fmts) {
    auto* hw = static_cast<HwAccelContext*>(ctx->opaque);
    if (!hw || hw->hw_pix_fmt < 0) {
        return AV_PIX_FMT_NONE;
    }
    const auto want = static_cast<enum AVPixelFormat>(hw->hw_pix_fmt);
    for (const enum AVPixelFormat* p = pix_fmts; *p != AV_PIX_FMT_NONE; ++p) {
        if (*p == want) {
            return *p;
        }
    }
    LOG_WARN("硬解：无匹配的 hw pixel format，回退软件解码");
    return AV_PIX_FMT_NONE;
}

void clearCodecHwFields(AVCodecContext* ctx) {
    if (!ctx) return;
    ctx->get_format = nullptr;
    ctx->opaque = nullptr;
    if (ctx->hw_device_ctx) {
        av_buffer_unref(&ctx->hw_device_ctx);
        ctx->hw_device_ctx = nullptr;
    }
}

} // namespace

bool prepareVideoHwAccel(AVCodecContext* ctx, const AVCodec* codec, HwAccelContext* hw) {
    if (!ctx || !codec || !hw || !hw->requested) {
        return false;
    }

    enum AVPixelFormat hw_pix_fmt = AV_PIX_FMT_NONE;
    for (int i = 0;; ++i) {
        const AVCodecHWConfig* config = avcodec_get_hw_config(codec, i);
        if (!config) {
            break;
        }
        if ((config->methods & AV_CODEC_HW_CONFIG_METHOD_HW_DEVICE_CTX) &&
            config->device_type == AV_HWDEVICE_TYPE_D3D11VA) {
            hw_pix_fmt = config->pix_fmt;
            break;
        }
    }
    if (hw_pix_fmt == AV_PIX_FMT_NONE) {
        LOG_WARN("硬解：当前编码器不支持 D3D11VA");
        return false;
    }

    if (av_hwdevice_ctx_create(&hw->hw_device_ctx, AV_HWDEVICE_TYPE_D3D11VA,
            nullptr, nullptr, 0) < 0) {
        LOG_WARN("硬解：D3D11VA 设备创建失败");
        return false;
    }

    hw->hw_pix_fmt = static_cast<int>(hw_pix_fmt);
    ctx->opaque = hw;
    ctx->get_format = getHwFormat;
    ctx->hw_device_ctx = av_buffer_ref(hw->hw_device_ctx);
    return true;
}

void releaseVideoHwAccel(HwAccelContext* hw) {
    if (!hw) return;
    if (hw->hw_device_ctx) {
        av_buffer_unref(&hw->hw_device_ctx);
        hw->hw_device_ctx = nullptr;
    }
    hw->active = false;
    hw->hw_pix_fmt = -1;
}

bool isHwAcceleratedFrame(const AVFrame* frame, const HwAccelContext* hw) {
    if (!frame || !hw || !hw->active || hw->hw_pix_fmt < 0) {
        return false;
    }
    return frame->format == hw->hw_pix_fmt;
}

bool transferHwFrameToSoftware(const AVFrame* hw_frame, AVFrame* sw_frame) {
    if (!hw_frame || !sw_frame) {
        return false;
    }
    if (av_hwframe_transfer_data(sw_frame, hw_frame, 0) < 0) {
        LOG_WARN("硬解：GPU→CPU 帧传输失败");
        return false;
    }
    if (av_frame_copy_props(sw_frame, hw_frame) < 0) {
        LOG_WARN("硬解：帧属性复制失败");
    }
    return true;
}

const char* hwAccelDisplayName(const HwAccelContext* hw) {
    if (hw && hw->active) {
        return "D3D11VA";
    }
    return "cpu";
}

} // namespace media::common
