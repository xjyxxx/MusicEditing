#include "core/media_engine.h"

#ifdef MUSIC_HAS_LLAMA
#include "core/audio_extractor.h"
#include "core/highlight_analyzer.h"
#endif

#include <cstdio>
#include <cstring>
#include <string>

static void printUsage() {
    printf("用法:\n");
    printf("  media_cli version\n");
    printf("  media_cli probe <视频路径>\n");
    printf("  media_cli iterate <视频路径> [最大帧数]\n");
#ifdef MUSIC_HAS_LLAMA
    printf("  media_cli extract-audio <视频路径> <输出wav>\n");
    printf("  media_cli analyze-speech <transcript.json> <model.gguf> <场景> <最短秒> <最长秒> <敏感度0-1>\n");
#endif
}

static int cmdVersion() {
    media_engine_init();
    printf("%s\n", media_engine_ffmpeg_version());
    media_engine_shutdown();
    return 0;
}

static int cmdProbe(const char* path) {
    media_engine_init();

    int w = 0, h = 0;
    double dur = 0, fps = 0;
    int64_t total = 0;
    char codec[64] = {};
    char fmt[64] = {};

    int ret = media_probe_video(path, &w, &h, &dur, &fps, &total,
        codec, sizeof(codec), fmt, sizeof(fmt));

    if (ret != 0) {
        fprintf(stderr, "PROBE_ERROR:%d\n", ret);
        media_engine_shutdown();
        return ret;
    }

    printf("PROBE_OK\n");
    printf("width=%d\n", w);
    printf("height=%d\n", h);
    printf("duration=%.6f\n", dur);
    printf("fps=%.6f\n", fps);
    printf("total_frames=%lld\n", static_cast<long long>(total));
    printf("codec=%s\n", codec);
    printf("format=%s\n", fmt);

    media_engine_shutdown();
    return 0;
}

struct IterateCtx {
    int maxFrames;
    int count;
};

static int iterateCallback(int64_t idx, int64_t total, double ts, void* user) {
    auto* ctx = static_cast<IterateCtx*>(user);
    printf("PROGRESS:%lld:%lld:%.6f\n",
        static_cast<long long>(idx),
        static_cast<long long>(total), ts);
    fflush(stdout);
    ctx->count++;
    if (ctx->maxFrames > 0 && ctx->count >= ctx->maxFrames) {
        return 1;
    }
    return 0;
}

static int cmdIterate(const char* path, int maxFrames) {
    media_engine_init();

    IterateCtx ctx{maxFrames, 0};
    int ret = media_iterate_frames(path, iterateCallback, &ctx);

    if (ret != 0) {
        fprintf(stderr, "ITERATE_ERROR:%d\n", ret);
        media_engine_shutdown();
        return ret;
    }

    printf("ITERATE_OK:%d\n", ctx.count);
    media_engine_shutdown();
    return 0;
}

#ifdef MUSIC_HAS_LLAMA
static int cmdExtractAudio(const char* video, const char* wav) {
    media_engine_init();
    bool ok = media::core::extractAudioToWav(video, wav);
    media_engine_shutdown();
    if (!ok) {
        fprintf(stderr, "EXTRACT_AUDIO_ERROR\n");
        return -1;
    }
    printf("EXTRACT_AUDIO_OK\n");
    printf("wav=%s\n", wav);
    return 0;
}

static int cmdAnalyzeSpeech(int argc, char* argv[]) {
    if (argc < 8) {
        printUsage();
        return 1;
    }

    const char* jsonPath = argv[2];
    const char* modelPath = argv[3];
    const char* scene = argv[4];
    double minDur = atof(argv[5]);
    double maxDur = atof(argv[6]);
    float sens = static_cast<float>(atof(argv[7]));

    media_engine_init();

    media::core::HighlightAnalyzer analyzer(modelPath);
    auto transcript = analyzer.parseTranscriptJson(jsonPath);
    if (transcript.empty()) {
        fprintf(stderr, "ANALYZE_SPEECH_ERROR:empty_transcript\n");
        media_engine_shutdown();
        return -2;
    }

    media::core::HighlightAnalyzeParams params;
    params.scene = scene;
    params.min_duration = minDur;
    params.max_duration = maxDur;
    params.sensitivity = sens;

    std::string debug;
    auto highlights = analyzer.analyzeHighlights(transcript, params, &debug);

    printf("HIGHLIGHTS_OK\n");
    printf("count=%zu\n", highlights.size());
    printf("llm_used=%d\n", analyzer.isLlmReady() ? 1 : 0);
    for (const auto& h : highlights) {
        printf("HIGHLIGHT|%.3f|%.3f|%.3f\n", h.start_sec, h.end_sec, h.score);
    }

    media_engine_shutdown();
    return 0;
}
#endif

int main(int argc, char* argv[]) {
    if (argc < 2) {
        printUsage();
        return 1;
    }

    const char* cmd = argv[1];

    if (strcmp(cmd, "version") == 0) {
        return cmdVersion();
    }

    if (strcmp(cmd, "probe") == 0) {
        if (argc < 3) { printUsage(); return 1; }
        return cmdProbe(argv[2]);
    }

    if (strcmp(cmd, "iterate") == 0) {
        if (argc < 3) { printUsage(); return 1; }
        int maxFrames = (argc >= 4) ? atoi(argv[3]) : 0;
        return cmdIterate(argv[2], maxFrames);
    }

#ifdef MUSIC_HAS_LLAMA
    if (strcmp(cmd, "extract-audio") == 0) {
        if (argc < 4) { printUsage(); return 1; }
        return cmdExtractAudio(argv[2], argv[3]);
    }

    if (strcmp(cmd, "analyze-speech") == 0) {
        return cmdAnalyzeSpeech(argc, argv);
    }
#endif

    printUsage();
    return 1;
}
