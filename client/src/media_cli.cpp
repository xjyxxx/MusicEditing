#include "core/media_engine.h"

#ifdef MUSIC_HAS_LLAMA
#include "core/audio_extractor.h"
#include "core/highlight_analyzer.h"
#endif

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <string>
#include <vector>

static void printUsage() {
    printf("用法:\n");
    printf("  media_cli version\n");
    printf("  media_cli probe <视频路径>\n");
    printf("  media_cli iterate <视频路径> [最大帧数]\n");
#ifdef MUSIC_HAS_LLAMA
    printf("  media_cli extract-audio <视频路径> <输出wav>\n");
    printf("  media_cli analyze-speech <transcript.json> <model.gguf> <场景> <最短秒> <最长秒> <敏感度0-1>\n");
#endif
#if defined(MUSIC_HAS_ONNXRUNTIME) && defined(MUSIC_HAS_OPENCV)
    printf("  media_cli watermark-inpaint <model.onnx> <输入图> <输出图> <x> <y> <w> <h> [x2 y2 w2 h2 ...]\n");
    printf("  media_cli watermark-inpaint-frames <model.onnx> <输入帧目录> <输出帧目录> <x> <y> <w> <h> [x2 y2 w2 h2 ...]\n");
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

#if defined(MUSIC_HAS_ONNXRUNTIME) && defined(MUSIC_HAS_OPENCV)
static void printWatermarkError(int code) {
    const char* detail = media_engine_last_error();
    if (detail && *detail) {
        fprintf(stderr, "WATERMARK_ERROR:%d:%s\n", code, detail);
    } else {
        fprintf(stderr, "WATERMARK_ERROR:%d\n", code);
    }
    fflush(stderr);
}

static int cmdWatermarkInpaint(int argc, char* argv[]) {
    if (argc < 9 || ((argc - 5) % 4) != 0) {
        printUsage();
        return 1;
    }

    media_engine_init();

    int ret = media_watermark_load_model(argv[2]);
    if (ret != 0) {
        printWatermarkError(ret);
        media_engine_shutdown();
        return ret;
    }
    fprintf(stderr, "WATERMARK_BACKEND:%s\n",
        media_watermark_uses_opencv_fallback() ? "opencv" : "lama");

    const int numRegions = (argc - 5) / 4;
    std::vector<int> regions(static_cast<size_t>(numRegions * 4));
    for (int i = 0; i < numRegions; ++i) {
        regions[static_cast<size_t>(i * 4 + 0)] = atoi(argv[5 + i * 4]);
        regions[static_cast<size_t>(i * 4 + 1)] = atoi(argv[5 + i * 4 + 1]);
        regions[static_cast<size_t>(i * 4 + 2)] = atoi(argv[5 + i * 4 + 2]);
        regions[static_cast<size_t>(i * 4 + 3)] = atoi(argv[5 + i * 4 + 3]);
    }
    ret = media_watermark_inpaint_image(argv[3], argv[4], regions.data(), numRegions);
    if (ret != 0) {
        printWatermarkError(ret);
        media_engine_shutdown();
        return ret;
    }

    printf("WATERMARK_OK\n");
    printf("output=%s\n", argv[4]);
    media_engine_shutdown();
    return 0;
}

static std::vector<std::string> collectPngFrames(const char* dirPath) {
    namespace fs = std::filesystem;
    std::vector<std::string> files;
    std::error_code ec;
    if (!fs::is_directory(dirPath, ec)) {
        return files;
    }
    for (const auto& entry : fs::directory_iterator(dirPath, ec)) {
        if (ec || !entry.is_regular_file()) continue;
        const auto ext = entry.path().extension().string();
        if (ext == ".png" || ext == ".PNG") {
            files.push_back(entry.path().string());
        }
    }
    std::sort(files.begin(), files.end());
    return files;
}

static int cmdWatermarkInpaintFrames(int argc, char* argv[]) {
    if (argc < 9 || ((argc - 5) % 4) != 0) {
        printUsage();
        return 1;
    }

    const char* modelPath = argv[2];
    const char* inDir = argv[3];
    const char* outDir = argv[4];

    std::error_code ec;
    std::filesystem::create_directories(outDir, ec);

    auto frameFiles = collectPngFrames(inDir);
    if (frameFiles.empty()) {
        fprintf(stderr, "WATERMARK_ERROR:no_frames\n");
        return -3;
    }

    media_engine_init();

    int ret = media_watermark_load_model(modelPath);
    if (ret != 0) {
        printWatermarkError(ret);
        media_engine_shutdown();
        return ret;
    }
    fprintf(stderr, "WATERMARK_BACKEND:%s\n",
        media_watermark_uses_opencv_fallback() ? "opencv" : "lama");

    const int numRegions = (argc - 5) / 4;
    std::vector<int> regions(static_cast<size_t>(numRegions * 4));
    for (int i = 0; i < numRegions; ++i) {
        regions[static_cast<size_t>(i * 4 + 0)] = atoi(argv[5 + i * 4]);
        regions[static_cast<size_t>(i * 4 + 1)] = atoi(argv[5 + i * 4 + 1]);
        regions[static_cast<size_t>(i * 4 + 2)] = atoi(argv[5 + i * 4 + 2]);
        regions[static_cast<size_t>(i * 4 + 3)] = atoi(argv[5 + i * 4 + 3]);
    }

    const int total = static_cast<int>(frameFiles.size());
    for (int i = 0; i < total; ++i) {
        const std::string& inPath = frameFiles[static_cast<size_t>(i)];
        const std::string outPath =
            (std::filesystem::path(outDir) / std::filesystem::path(inPath).filename()).string();

        ret = media_watermark_inpaint_image(
            inPath.c_str(), outPath.c_str(), regions.data(), numRegions);
        if (ret != 0) {
            printWatermarkError(ret);
            fprintf(stderr, "frame=%s\n", inPath.c_str());
            fflush(stderr);
            media_engine_shutdown();
            return ret;
        }

        printf("PROGRESS:%d:%d\n", i + 1, total);
        fflush(stdout);
    }

    printf("WATERMARK_FRAMES_OK\n");
    printf("count=%d\n", total);
    media_engine_shutdown();
    return 0;
}
#endif

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <vector>

static std::string wideToUtf8(const wchar_t* wstr) {
    if (!wstr || !*wstr) return {};
    const int len = WideCharToMultiByte(CP_UTF8, 0, wstr, -1, nullptr, 0, nullptr, nullptr);
    if (len <= 0) return {};
    std::string out(static_cast<size_t>(len - 1), '\0');
    WideCharToMultiByte(CP_UTF8, 0, wstr, -1, out.data(), len, nullptr, nullptr);
    return out;
}

static int runCli(int argc, char* argv[]);
#else
static int runCli(int argc, char* argv[]);
#endif

static int runCli(int argc, char* argv[]) {
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

#if defined(MUSIC_HAS_ONNXRUNTIME) && defined(MUSIC_HAS_OPENCV)
    if (strcmp(cmd, "watermark-inpaint") == 0) {
        return cmdWatermarkInpaint(argc, argv);
    }

    if (strcmp(cmd, "watermark-inpaint-frames") == 0) {
        return cmdWatermarkInpaintFrames(argc, argv);
    }
#endif

    printUsage();
    return 1;
}

#ifdef _WIN32
int wmain(int argc, wchar_t* argv[]) {
    std::vector<std::string> utf8Args;
    utf8Args.reserve(static_cast<size_t>(argc));
    for (int i = 0; i < argc; ++i) {
        utf8Args.push_back(wideToUtf8(argv[i]));
    }
    std::vector<char*> ptrs;
    ptrs.reserve(utf8Args.size());
    for (auto& s : utf8Args) {
        ptrs.push_back(s.data());
    }
    return runCli(static_cast<int>(ptrs.size()), ptrs.data());
}
#else
int main(int argc, char* argv[]) {
    return runCli(argc, argv);
}
#endif
