#include "core/audio_player_engine.h"



#include "common/file_path.h"

#include "common/logger.h"



#define MINIAUDIO_IMPLEMENTATION

#include "miniaudio.h"



#define __STDC_CONSTANT_MACROS



#ifdef _WIN32

#ifndef WIN32_LEAN_AND_MEAN

#define WIN32_LEAN_AND_MEAN

#endif

#include <windows.h>

#include <objbase.h>

extern "C" {

#include "libavcodec/avcodec.h"

#include "libavformat/avformat.h"

#include "libswresample/swresample.h"

}

#else

extern "C" {

#include <libavcodec/avcodec.h>

#include <libavformat/avformat.h>

#include <libswresample/swresample.h>

}

#endif



#include <atomic>

#include <algorithm>

#include <chrono>

#include <cstring>

#include <mutex>

#include <thread>

#include <vector>



namespace media::core {



namespace {



constexpr int kOutRate = 44100;

constexpr int kOutChannels = 2;

constexpr AVSampleFormat kOutFmt = AV_SAMPLE_FMT_S16;

constexpr size_t kRingBytes = 44100 * kOutChannels * 2 * 2; // ~2s PCM



struct AudioContext {

    AVFormatContext* formatCtx = nullptr;

    AVCodecContext* codecCtx = nullptr;

    SwrContext* swrCtx = nullptr;

    int audioStreamIndex = -1;

};



void dataCallback(ma_device* device, void* output, const void* /*input*/, ma_uint32 frameCount) {

    auto* rb = static_cast<ma_rb*>(device->pUserData);

    if (!rb || !output) {

        return;

    }



    auto* outBytes = static_cast<uint8_t*>(output);

    const ma_uint32 bytesNeeded = frameCount * kOutChannels * static_cast<ma_uint32>(sizeof(int16_t));

    ma_uint32 bytesFilled = 0;



    while (bytesFilled < bytesNeeded) {

        size_t avail = 0;

        void* pRead = nullptr;

        if (ma_rb_acquire_read(rb, &avail, &pRead) != MA_SUCCESS || avail == 0 || !pRead) {

            break;

        }

        const size_t toCopy = (std::min)(avail, static_cast<size_t>(bytesNeeded - bytesFilled));

        std::memcpy(outBytes + bytesFilled, pRead, toCopy);

        ma_rb_commit_read(rb, toCopy);

        bytesFilled += static_cast<ma_uint32>(toCopy);

    }



    if (bytesFilled < bytesNeeded) {

        std::memset(outBytes + bytesFilled, 0, bytesNeeded - bytesFilled);

    }

}



bool writePcmToRing(ma_rb* rb, const uint8_t* data, size_t bytes) {

    size_t written = 0;

    while (written < bytes) {

        size_t avail = 0;

        void* pWrite = nullptr;

        if (ma_rb_acquire_write(rb, &avail, &pWrite) != MA_SUCCESS || avail == 0 || !pWrite) {

            return written > 0;

        }

        const size_t chunk = (std::min)(avail, bytes - written);

        std::memcpy(pWrite, data + written, chunk);

        ma_rb_commit_write(rb, chunk);

        written += chunk;

    }

    return true;

}



} // namespace



struct AudioPlayerEngine::Impl {

    AudioContext audio;

    ma_context context{};

    ma_device device{};

    ma_rb ringBuffer{};

    bool contextInited = false;

    bool deviceStarted = false;

    bool hasAudioStream = false;

    bool comInited = false;



    std::thread decodeThread;

    std::atomic<bool> running{false};

    std::atomic<bool> paused{true};

    std::atomic<bool> seekPending{false};

    std::atomic<double> seekTarget{0.0};

    std::atomic<float> volume{0.7f};



    std::mutex audioMutex;

    std::mutex ringMutex;

};



AudioPlayerEngine::AudioPlayerEngine() : impl_(std::make_unique<Impl>()) {}



AudioPlayerEngine::~AudioPlayerEngine() {

    close();

}



bool AudioPlayerEngine::hasAudio() const {

    return impl_ && impl_->hasAudioStream;

}



void AudioPlayerEngine::setVolume(float volume01) {

    if (!impl_) return;

    if (volume01 < 0.f) volume01 = 0.f;

    if (volume01 > 1.f) volume01 = 1.f;

    impl_->volume.store(volume01);

    if (impl_->device.pContext) {

        ma_device_set_master_volume(&impl_->device, volume01);

    }

}



bool AudioPlayerEngine::open(const std::string& filePath) {

    close();



    av_register_all();



#ifdef _WIN32

    if (CoInitializeEx(nullptr, COINIT_MULTITHREADED) == S_OK

        || CoInitializeEx(nullptr, COINIT_MULTITHREADED) == S_FALSE) {

        impl_->comInited = true;

    }

#endif



    const std::string nativePath = common::pathForFfmpeg(filePath);



    AVFormatContext* fmtCtx = nullptr;

    if (avformat_open_input(&fmtCtx, nativePath.c_str(), nullptr, nullptr) != 0) {

        LOG_WARN("音频：无法打开 " + filePath);

        close();

        return false;

    }

    if (avformat_find_stream_info(fmtCtx, nullptr) < 0) {

        avformat_close_input(&fmtCtx);

        close();

        return false;

    }



    int audioIdx = -1;

    for (unsigned i = 0; i < fmtCtx->nb_streams; ++i) {

        if (fmtCtx->streams[i]->codec->codec_type == AVMEDIA_TYPE_AUDIO) {

            audioIdx = static_cast<int>(i);

            break;

        }

    }

    if (audioIdx < 0) {

        LOG_WARN("音频：未找到音频流");

        avformat_close_input(&fmtCtx);

        close();

        return false;

    }



    AVCodecContext* codecCtx = fmtCtx->streams[audioIdx]->codec;

    AVCodec* codec = avcodec_find_decoder(codecCtx->codec_id);

    if (!codec || avcodec_open2(codecCtx, codec, nullptr) < 0) {

        avformat_close_input(&fmtCtx);

        close();

        return false;

    }



    const int inChannels = codecCtx->channels > 0 ? codecCtx->channels : 2;

    const int64_t inLayout = codecCtx->channel_layout

        ? static_cast<int64_t>(codecCtx->channel_layout)

        : av_get_default_channel_layout(inChannels);



    SwrContext* swr = swr_alloc_set_opts(

        nullptr,

        av_get_default_channel_layout(kOutChannels), kOutFmt, kOutRate,

        inLayout, codecCtx->sample_fmt, codecCtx->sample_rate,

        0, nullptr);

    if (!swr || swr_init(swr) < 0) {

        if (swr) swr_free(&swr);

        avcodec_close(codecCtx);

        avformat_close_input(&fmtCtx);

        close();

        return false;

    }



    impl_->audio.formatCtx = fmtCtx;

    impl_->audio.codecCtx = codecCtx;

    impl_->audio.swrCtx = swr;

    impl_->audio.audioStreamIndex = audioIdx;

    impl_->hasAudioStream = true;



    if (ma_rb_init(kRingBytes, nullptr, nullptr, &impl_->ringBuffer) != MA_SUCCESS) {

        close();

        return false;

    }



    ma_backend backends[] = {

        ma_backend_wasapi,

        ma_backend_dsound,

        ma_backend_winmm,

    };

    ma_context_config ctxCfg = ma_context_config_init();

    if (ma_context_init(backends, sizeof(backends) / sizeof(backends[0]), &ctxCfg, &impl_->context)

        != MA_SUCCESS) {

        if (ma_context_init(nullptr, 0, nullptr, &impl_->context) != MA_SUCCESS) {

            LOG_ERROR("音频：miniaudio context 初始化失败");

            close();

            return false;

        }

    }

    impl_->contextInited = true;



    ma_device_config devCfg = ma_device_config_init(ma_device_type_playback);

    devCfg.playback.format = ma_format_s16;

    devCfg.playback.channels = kOutChannels;

    devCfg.sampleRate = kOutRate;

    devCfg.dataCallback = dataCallback;

    devCfg.pUserData = &impl_->ringBuffer;



    if (ma_device_init(&impl_->context, &devCfg, &impl_->device) != MA_SUCCESS) {

        LOG_ERROR("音频：miniaudio 设备初始化失败");

        close();

        return false;

    }



    ma_device_set_master_volume(&impl_->device, impl_->volume.load());



    impl_->running = true;

    impl_->paused = true;

    impl_->decodeThread = std::thread([this]() {

        AVPacket packet;

        av_init_packet(&packet);

        AVFrame* frame = av_frame_alloc();

        std::vector<uint8_t> convertBuf(kOutRate * kOutChannels * 2);



        while (impl_->running) {

            if (impl_->seekPending.load()) {

                const double target = impl_->seekTarget.load();

                {

                    std::lock_guard<std::mutex> lock(impl_->audioMutex);

                    {

                        std::lock_guard<std::mutex> ringLock(impl_->ringMutex);

                        ma_rb_reset(&impl_->ringBuffer);

                    }



                    const int64_t ts = static_cast<int64_t>(target * AV_TIME_BASE);

                    if (impl_->audio.formatCtx) {

                        av_seek_frame(impl_->audio.formatCtx, -1, ts, AVSEEK_FLAG_BACKWARD);

                    }

                    if (impl_->audio.codecCtx) {

                        avcodec_flush_buffers(impl_->audio.codecCtx);

                    }

                }

                impl_->seekPending = false;

            }



            if (impl_->paused.load()) {

                std::this_thread::sleep_for(std::chrono::milliseconds(5));

                continue;

            }



            int readRet = 0;

            {

                std::lock_guard<std::mutex> lock(impl_->audioMutex);

                if (!impl_->audio.formatCtx) break;

                readRet = av_read_frame(impl_->audio.formatCtx, &packet);

            }



            if (readRet < 0) {

                std::this_thread::sleep_for(std::chrono::milliseconds(10));

                continue;

            }



            if (packet.stream_index != impl_->audio.audioStreamIndex) {

                av_free_packet(&packet);

                av_init_packet(&packet);

                continue;

            }



            int got = 0;

            {

                std::lock_guard<std::mutex> lock(impl_->audioMutex);

                avcodec_decode_audio4(impl_->audio.codecCtx, frame, &got, &packet);

            }

            av_free_packet(&packet);

            av_init_packet(&packet);



            if (!got) continue;



            int outSamples = 0;

            {

                std::lock_guard<std::mutex> lock(impl_->audioMutex);

                outSamples = av_rescale_rnd(

                    swr_get_delay(impl_->audio.swrCtx, impl_->audio.codecCtx->sample_rate)

                        + frame->nb_samples,

                    kOutRate, impl_->audio.codecCtx->sample_rate, AV_ROUND_UP);

            }



            if (outSamples <= 0) continue;

            convertBuf.resize(static_cast<size_t>(outSamples) * kOutChannels * 2);

            uint8_t* outPtr = convertBuf.data();



            int converted = 0;

            {

                std::lock_guard<std::mutex> lock(impl_->audioMutex);

                converted = swr_convert(

                    impl_->audio.swrCtx, &outPtr, outSamples,

                    const_cast<const uint8_t**>(frame->data), frame->nb_samples);

            }



            if (converted > 0) {

                const size_t bytes = static_cast<size_t>(converted) * kOutChannels * 2;

                std::lock_guard<std::mutex> ringLock(impl_->ringMutex);

                writePcmToRing(&impl_->ringBuffer, convertBuf.data(), bytes);

            }

        }



        av_frame_free(&frame);

    });



    LOG_INFO("音频播放器已就绪: " + std::string(codec ? codec->name : "?")

        + " " + std::to_string(codecCtx->sample_rate) + "Hz");

    return true;

}



void AudioPlayerEngine::close() {
    if (!impl_) return;

    impl_->running = false;

    if (impl_->deviceStarted) {
        ma_device_stop(&impl_->device);
        impl_->deviceStarted = false;
    }

    {
        std::lock_guard<std::mutex> lock(impl_->audioMutex);
        if (impl_->audio.codecCtx) {
            avcodec_close(impl_->audio.codecCtx);
            impl_->audio.codecCtx = nullptr;
        }
        if (impl_->audio.formatCtx) {
            avformat_close_input(&impl_->audio.formatCtx);
            impl_->audio.formatCtx = nullptr;
        }
        if (impl_->audio.swrCtx) {
            swr_free(&impl_->audio.swrCtx);
            impl_->audio.swrCtx = nullptr;
        }
    }

    if (impl_->decodeThread.joinable()) {
        impl_->decodeThread.join();
    }

    if (impl_->device.pContext) {
        ma_device_uninit(&impl_->device);
        std::memset(&impl_->device, 0, sizeof(impl_->device));
    }

    {
        std::lock_guard<std::mutex> ringLock(impl_->ringMutex);
        if (impl_->hasAudioStream) {
            ma_rb_uninit(&impl_->ringBuffer);
        }
    }

    if (impl_->contextInited) {
        ma_context_uninit(&impl_->context);
        impl_->contextInited = false;
    }

    impl_->audio.audioStreamIndex = -1;
    impl_->hasAudioStream = false;
    impl_->paused = true;

#ifdef _WIN32
    if (impl_->comInited) {
        CoUninitialize();
        impl_->comInited = false;
    }
#endif
}



bool AudioPlayerEngine::seek(double timestampSec) {

    if (!impl_ || !impl_->hasAudioStream) return false;

    impl_->seekTarget = timestampSec;

    impl_->seekPending = true;

    return true;

}



void AudioPlayerEngine::pause() {
    if (!impl_) return;
    impl_->paused = true;
    if (!impl_->hasAudioStream) return;

    if (impl_->deviceStarted) {
        ma_device_stop(&impl_->device);
        impl_->deviceStarted = false;
    }
    std::lock_guard<std::mutex> ringLock(impl_->ringMutex);
    ma_rb_reset(&impl_->ringBuffer);
}

bool AudioPlayerEngine::resume() {
    if (!impl_ || !impl_->hasAudioStream) return true;



    impl_->paused = false;



    for (int i = 0; i < 100; ++i) {

        {

            std::lock_guard<std::mutex> ringLock(impl_->ringMutex);

            if (ma_rb_available_read(&impl_->ringBuffer) >= 4096) {

                break;

            }

        }

        std::this_thread::sleep_for(std::chrono::milliseconds(5));

    }



    if (impl_->deviceStarted) {

        return true;

    }



    const ma_result result = ma_device_start(&impl_->device);

    if (result != MA_SUCCESS) {

        LOG_ERROR("音频设备启动失败, code=" + std::to_string(static_cast<int>(result)));

        return false;

    }



    impl_->deviceStarted = true;

    ma_device_set_master_volume(&impl_->device, impl_->volume.load());

    return true;

}



bool AudioPlayerEngine::isPaused() const {

    return !impl_ || impl_->paused.load();

}



} // namespace media::core


