#include "core/audio_extractor.h"

#include "common/ffmpeg_compat.h"
#include "common/logger.h"

#define __STDC_CONSTANT_MACROS

#ifdef _WIN32
extern "C" {
#include "libavcodec/avcodec.h"
#include "libavformat/avformat.h"
#include "libswresample/swresample.h"
#include "libavutil/opt.h"
}
#else
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libswresample/swresample.h>
#include <libavutil/opt.h>
}
#endif

#include <cstdio>
#include <cstring>
#include <vector>

namespace media::core {

namespace {
    void writeWavHeader(FILE* fp, int sampleRate, int channels, int dataSize) {
        const int byteRate = sampleRate * channels * 2;
        const int blockAlign = channels * 2;
        const int chunkSize = 36 + dataSize;

        std::fwrite("RIFF", 1, 4, fp);
        std::fwrite(&chunkSize, 4, 1, fp);
        std::fwrite("WAVE", 1, 4, fp);
        std::fwrite("fmt ", 1, 4, fp);
        int subchunk1 = 16;
        short audioFormat = 1;
        short numChannels = static_cast<short>(channels);
        std::fwrite(&subchunk1, 4, 1, fp);
        std::fwrite(&audioFormat, 2, 1, fp);
        std::fwrite(&numChannels, 2, 1, fp);
        std::fwrite(&sampleRate, 4, 1, fp);
        std::fwrite(&byteRate, 4, 1, fp);
        std::fwrite(&blockAlign, 2, 1, fp);
        short bitsPerSample = 16;
        std::fwrite(&bitsPerSample, 2, 1, fp);
        std::fwrite("data", 1, 4, fp);
        std::fwrite(&dataSize, 4, 1, fp);
    }
}

bool extractAudioToWav(const std::string& videoPath, const std::string& wavPath) {
    common::ffmpegInit();

    AVFormatContext* fmtCtx = nullptr;
    if (avformat_open_input(&fmtCtx, videoPath.c_str(), nullptr, nullptr) != 0) {
        LOG_ERROR("无法打开视频提取音频: " + videoPath);
        return false;
    }
    if (avformat_find_stream_info(fmtCtx, nullptr) < 0) {
        avformat_close_input(&fmtCtx);
        return false;
    }

    int audioIdx = -1;
    AVCodecContext* codecCtx = nullptr;
    if (!common::openAudioDecoder(fmtCtx, audioIdx, &codecCtx)) {
        LOG_ERROR("未找到音频流");
        avformat_close_input(&fmtCtx);
        return false;
    }

    const int outRate = 16000;
    const int outChannels = 1;
    AVSampleFormat outFmt = AV_SAMPLE_FMT_S16;

    SwrContext* swr = nullptr;
#if LIBAVCODEC_VERSION_INT >= AV_VERSION_INT(59, 0, 0)
    AVChannelLayout outLayout = AV_CHANNEL_LAYOUT_MONO;
    if (swr_alloc_set_opts2(&swr, &outLayout, outFmt, outRate,
            &codecCtx->ch_layout, codecCtx->sample_fmt, codecCtx->sample_rate,
            0, nullptr) < 0) {
        swr = nullptr;
    }
#else
    swr = swr_alloc_set_opts(
        nullptr,
        av_get_default_channel_layout(outChannels), outFmt, outRate,
        codecCtx->channel_layout ? static_cast<int64_t>(codecCtx->channel_layout)
            : av_get_default_channel_layout(codecCtx->channels),
        codecCtx->sample_fmt, codecCtx->sample_rate,
        0, nullptr);
#endif
    if (!swr || swr_init(swr) < 0) {
        LOG_ERROR("音频重采样初始化失败");
        if (swr) swr_free(&swr);
        common::freeCodecContext(&codecCtx);
        avformat_close_input(&fmtCtx);
        return false;
    }

    std::vector<uint8_t> pcmData;
    pcmData.reserve(1024 * 1024);

    AVPacket packet;
    std::memset(&packet, 0, sizeof(packet));
    AVFrame* frame = av_frame_alloc();

    while (av_read_frame(fmtCtx, &packet) >= 0) {
        if (packet.stream_index == audioIdx) {
            if (common::decodeAudioPacket(codecCtx, &packet, frame)) {
                const int outSamples = av_rescale_rnd(
                    swr_get_delay(swr, codecCtx->sample_rate) + frame->nb_samples,
                    outRate, codecCtx->sample_rate, AV_ROUND_UP);

                std::vector<uint8_t> outBuf(static_cast<size_t>(outSamples) * outChannels * 2);
                uint8_t* outPtr = outBuf.data();
                int converted = swr_convert(swr, &outPtr, outSamples,
                    const_cast<const uint8_t**>(frame->data), frame->nb_samples);
                if (converted > 0) {
                    pcmData.insert(pcmData.end(), outBuf.begin(),
                        outBuf.begin() + static_cast<size_t>(converted) * outChannels * 2);
                }
            }
        }
        common::packetUnref(&packet);
    }

    av_frame_free(&frame);
    swr_free(&swr);
    common::freeCodecContext(&codecCtx);
    avformat_close_input(&fmtCtx);

    if (pcmData.empty()) {
        LOG_ERROR("未解码到音频数据");
        return false;
    }

    FILE* fp = std::fopen(wavPath.c_str(), "wb");
    if (!fp) {
        LOG_ERROR("无法写入 WAV: " + wavPath);
        return false;
    }

    const int dataSize = static_cast<int>(pcmData.size());
    writeWavHeader(fp, outRate, outChannels, dataSize);
    std::fwrite(pcmData.data(), 1, pcmData.size(), fp);
    std::fclose(fp);

    LOG_INFO("音频已导出: " + wavPath + " (" + std::to_string(dataSize) + " bytes)");
    return true;
}

} // namespace media::core
