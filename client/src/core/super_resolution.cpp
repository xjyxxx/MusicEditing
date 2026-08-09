#include "core/super_resolution.h"

#include "common/file_path.h"
#include "common/logger.h"
#include "common/utils.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#if defined(MUSIC_HAS_ONNXRUNTIME) && defined(MUSIC_HAS_OPENCV)

#include <onnxruntime_cxx_api.h>

#include <opencv2/dnn.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

namespace media::core {

namespace {

/// 更大 tile → 更少 Session::Run；CUDA 下尤其受益。可用 MUSIC_UPSCALE_TILE 覆盖（128–1024）
constexpr int kTileSizeDefault = 384;
constexpr int kTilePad = 10;
constexpr int kModelScale = 4;

int tileSizeFromEnv() {
    const char* v = std::getenv("MUSIC_UPSCALE_TILE");
    if (!v || !*v) {
        return kTileSizeDefault;
    }
    try {
        int n = std::stoi(v);
        if (n <= 0) {
            return kTileSizeDefault;
        }
        return std::clamp(n, 128, 1024);
    } catch (...) {
        return kTileSizeDefault;
    }
}

bool preferCudaFromEnv() {
    const char* v = std::getenv("MUSIC_ORT_CUDA");
    if (!v || !*v) {
        return false;
    }
    std::string s(v);
    for (char& c : s) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return s == "1" || s == "true" || s == "on" || s == "yes" || s == "cuda";
}

/// MUSIC_UPSCALE_BACKEND=opencv|realesrgan|ai（默认 auto：有模型用 AI）
bool preferOpenCvBackend() {
    const char* v = std::getenv("MUSIC_UPSCALE_BACKEND");
    if (!v || !*v) {
        return false;
    }
    std::string s(v);
    for (char& c : s) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return s == "opencv" || s == "cv" || s == "fast" || s == "bicubic";
}

int clampScale(int scale) {
    if (scale <= 2) return 2;
    return 4;
}

float clampStrength(float s) {
    if (s < 0.0f) return 0.0f;
    if (s > 1.0f) return 1.0f;
    return s;
}

/// 默认强度：略保守，减轻 Real-ESRGAN「假锐/塑料感」
float strengthFromEnvOrDefault(float fallback) {
    const char* v = std::getenv("MUSIC_UPSCALE_STRENGTH");
    if (!v || !*v) return fallback;
    try {
        return clampStrength(std::stof(v));
    } catch (...) {
        return fallback;
    }
}

void imageToNchw01(const cv::Mat& bgr, std::vector<float>& out) {
    // OpenCV DNN：BGR→RGB、/255、NCHW，比手写三重循环快
    cv::Mat blob = cv::dnn::blobFromImage(
        bgr, 1.0 / 255.0, cv::Size(), cv::Scalar(), true /*swapRB*/, false);
    const size_t n = blob.total();
    out.resize(n);
    std::memcpy(out.data(), blob.ptr<float>(), n * sizeof(float));
}

void nchw01ToBgr(const float* nchw, int h, int w, cv::Mat& bgr) {
    // OpenCV imagesFromBlob：NCHW float[0,1] → RGB Mat，再转 BGR（避免三重手写循环）
    const int sizes[4] = {1, 3, h, w};
    cv::Mat blob(4, sizes, CV_32F, const_cast<float*>(nchw));
    std::vector<cv::Mat> images;
    cv::dnn::imagesFromBlob(blob, images);
    if (images.empty() || images[0].empty()) {
        bgr.release();
        return;
    }
    cv::Mat rgb8;
    images[0].convertTo(rgb8, CV_8UC3, 255.0);
    cv::cvtColor(rgb8, bgr, cv::COLOR_RGB2BGR);
}

/// 对 work 图跑 4× 模型（分块），写出 out（尺寸 = work * 4）
bool runTiledX4(
    Ort::Session& session,
    const std::string& inputName,
    const std::string& outputName,
    const cv::Mat& work,
    cv::Mat& out,
    std::string& err)
{
    const int inH = work.rows;
    const int inW = work.cols;
    out = cv::Mat::zeros(inH * kModelScale, inW * kModelScale, CV_8UC3);

    const int kTileSize = tileSizeFromEnv();
    auto memoryInfo = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
    const char* inNames[] = {inputName.c_str()};
    const char* outNames[] = {outputName.c_str()};
    std::vector<float> tensor;
    tensor.reserve(static_cast<size_t>(3 * (kTileSize + 2 * kTilePad) * (kTileSize + 2 * kTilePad)));

    for (int y0 = 0; y0 < inH; y0 += kTileSize) {
        for (int x0 = 0; x0 < inW; x0 += kTileSize) {
            const int tileW = std::min(kTileSize, inW - x0);
            const int tileH = std::min(kTileSize, inH - y0);

            const int x1 = std::max(0, x0 - kTilePad);
            const int y1 = std::max(0, y0 - kTilePad);
            const int x2 = std::min(inW, x0 + tileW + kTilePad);
            const int y2 = std::min(inH, y0 + tileH + kTilePad);

            cv::Mat patch = work(cv::Rect(x1, y1, x2 - x1, y2 - y1)).clone();
            imageToNchw01(patch, tensor);

            const int ph = patch.rows;
            const int pw = patch.cols;
            std::vector<int64_t> shape = {1, 3, ph, pw};
            Ort::Value inputValue = Ort::Value::CreateTensor<float>(
                memoryInfo, tensor.data(), tensor.size(),
                shape.data(), shape.size());

            auto outputs = session.Run(
                Ort::RunOptions{nullptr},
                inNames, &inputValue, 1,
                outNames, 1);

            const float* outData = outputs[0].GetTensorData<float>();
            auto outShape = outputs[0].GetTensorTypeAndShapeInfo().GetShape();
            int oh = ph * kModelScale;
            int ow = pw * kModelScale;
            if (outShape.size() >= 4) {
                if (outShape[2] > 0) oh = static_cast<int>(outShape[2]);
                if (outShape[3] > 0) ow = static_cast<int>(outShape[3]);
            }

            cv::Mat patchOut;
            nchw01ToBgr(outData, oh, ow, patchOut);

            const int padL = (x0 - x1) * kModelScale;
            const int padT = (y0 - y1) * kModelScale;
            const int copyW = tileW * kModelScale;
            const int copyH = tileH * kModelScale;
            if (padL + copyW > patchOut.cols || padT + copyH > patchOut.rows) {
                err = "超分输出尺寸异常";
                return false;
            }
            patchOut(cv::Rect(padL, padT, copyW, copyH)).copyTo(
                out(cv::Rect(x0 * kModelScale, y0 * kModelScale, copyW, copyH)));
        }
    }
    return true;
}

bool upscaleOpenCv(const cv::Mat& bgr, int scale, cv::Mat& out) {
    if (bgr.empty() || scale < 2) return false;
    static bool once = false;
    if (!once) {
        once = true;
        const int n = static_cast<int>(std::max(2u, std::thread::hardware_concurrency()));
        cv::setNumThreads(n);
    }
    cv::resize(bgr, out, cv::Size(), scale, scale, cv::INTER_CUBIC);
    return !out.empty();
}

} // namespace

struct SuperResolution::Impl {
    Ort::Env env{ORT_LOGGING_LEVEL_WARNING, "MusicEditingUpscale"};
    std::unique_ptr<Ort::Session> session;
    std::string inputName = "input";
    std::string outputName = "output";
    bool ready = false;
    bool useOpenCvFallback = false;
    bool useCuda = false;
    int modelScale = kModelScale;
};

SuperResolution::~SuperResolution() {
    delete impl_;
    impl_ = nullptr;
}

bool SuperResolution::loadModel(const std::string& modelPath) {
    lastError_.clear();

    if (!impl_) impl_ = new Impl();
    impl_->useOpenCvFallback = false;
    impl_->useCuda = false;
    impl_->session.reset();
    impl_->modelScale = kModelScale;

    if (preferOpenCvBackend() || modelPath.empty() || modelPath == "-") {
        impl_->useOpenCvFallback = true;
        impl_->ready = true;
        LOG_INFO("超分后端: OpenCV 双三次（快速模式）");
        return true;
    }

    if (!media::common::fileExists(modelPath)) {
        lastError_ = "模型文件不存在: " + modelPath;
        return false;
    }

    const std::wstring wpath = media::common::utf8PathToWide(modelPath);
    const bool wantCuda = preferCudaFromEnv();
    std::string onnxError;

    auto tryCreate = [&](bool useCuda, GraphOptimizationLevel level) -> bool {
        Ort::SessionOptions opts;
        const int cpuThreads = static_cast<int>(std::max(2u, std::thread::hardware_concurrency()));
        opts.SetIntraOpNumThreads(useCuda ? 1 : cpuThreads);
        opts.SetGraphOptimizationLevel(level);
        if (useCuda) {
            OrtCUDAProviderOptions cudaOpts{};
            cudaOpts.device_id = 0;
            opts.AppendExecutionProvider_CUDA(cudaOpts);
        }
#ifdef _WIN32
        impl_->session = std::make_unique<Ort::Session>(
            impl_->env, wpath.c_str(), opts);
#else
        impl_->session = std::make_unique<Ort::Session>(
            impl_->env, modelPath.c_str(), opts);
#endif
        Ort::AllocatorWithDefaultOptions allocator;
        if (impl_->session->GetInputCount() >= 1) {
            impl_->inputName = impl_->session->GetInputNameAllocated(0, allocator).get();
        }
        if (impl_->session->GetOutputCount() >= 1) {
            impl_->outputName = impl_->session->GetOutputNameAllocated(0, allocator).get();
        }
        impl_->useCuda = useCuda;
        impl_->useOpenCvFallback = false;
        impl_->ready = true;
        return true;
    };

    const GraphOptimizationLevel levels[] = {
        GraphOptimizationLevel::ORT_ENABLE_ALL,
        GraphOptimizationLevel::ORT_DISABLE_ALL,
    };
    const bool cudaModes[] = {true, false};
    for (bool useCuda : cudaModes) {
        if (useCuda && !wantCuda) continue;
        for (auto level : levels) {
            try {
                if (!tryCreate(useCuda, level)) continue;
                LOG_INFO(std::string("Real-ESRGAN ONNX 已加载: ") + modelPath
                    + (useCuda ? " [CUDA EP]" : " [CPU EP]"));
                return true;
            } catch (const Ort::Exception& e) {
                onnxError = e.what();
                impl_->session.reset();
                impl_->useCuda = false;
            }
        }
    }

    LOG_WARN("Real-ESRGAN 不可用 (" + onnxError + ")，回退 OpenCV 双三次");
    impl_->useOpenCvFallback = true;
    impl_->useCuda = false;
    impl_->ready = true;
    return true;
}

void SuperResolution::unload() {
    if (impl_) {
        impl_->session.reset();
        impl_->ready = false;
        impl_->useOpenCvFallback = false;
        impl_->useCuda = false;
    }
    lastError_.clear();
}

bool SuperResolution::isReady() const {
    return impl_ && impl_->ready;
}

bool SuperResolution::usesOpenCvFallback() const {
    return impl_ && impl_->ready && impl_->useOpenCvFallback;
}

bool SuperResolution::usesCuda() const {
    return impl_ && impl_->ready && impl_->useCuda && !impl_->useOpenCvFallback;
}

const char* SuperResolution::executionProvider() const {
    if (!impl_ || !impl_->ready) return "none";
    if (impl_->useOpenCvFallback) return "opencv";
    return impl_->useCuda ? "cuda" : "cpu";
}

int SuperResolution::modelScale() const {
    return impl_ ? impl_->modelScale : kModelScale;
}

bool SuperResolution::upscaleImageFile(
    const std::string& inputPath,
    const std::string& outputPath,
    int scale,
    float strength)
{
    lastError_.clear();
    if (!isReady()) {
        lastError_ = "超分模型未加载";
        return false;
    }

    scale = clampScale(scale);
    strength = clampStrength(strengthFromEnvOrDefault(strength));
    const std::string nativeIn = media::common::pathUtf8ToNative(inputPath);
    const std::string nativeOut = media::common::pathUtf8ToNative(outputPath);
    cv::Mat bgr = cv::imread(nativeIn, cv::IMREAD_COLOR);
    if (bgr.empty()) {
        lastError_ = "无法读取图像: " + inputPath;
        return false;
    }

    cv::Mat outBgr;

    if (impl_->useOpenCvFallback || !impl_->session) {
        if (!upscaleOpenCv(bgr, scale, outBgr)) {
            lastError_ = "OpenCV 放大失败";
            return false;
        }
    } else {
        try {
            // 2×：先把原图缩到 1/2，再跑 4× 模型 → 等价 2×，推理像素量约 1/4
            cv::Mat work = bgr;
            if (scale == 2) {
                cv::resize(bgr, work, cv::Size(bgr.cols / 2, bgr.rows / 2), 0, 0, cv::INTER_AREA);
                LOG_INFO("超分 2× 快路径: 输入 "
                    + std::to_string(bgr.cols) + "x" + std::to_string(bgr.rows)
                    + " → 半分辨率推理 "
                    + std::to_string(work.cols) + "x" + std::to_string(work.rows));
            }

            if (!runTiledX4(
                    *impl_->session, impl_->inputName, impl_->outputName,
                    work, outBgr, lastError_)) {
                return false;
            }

            if (scale == 4 && (outBgr.cols != bgr.cols * 4 || outBgr.rows != bgr.rows * 4)) {
                cv::resize(outBgr, outBgr, cv::Size(bgr.cols * 4, bgr.rows * 4), 0, 0, cv::INTER_LINEAR);
            } else if (scale == 2 && (outBgr.cols != bgr.cols * 2 || outBgr.rows != bgr.rows * 2)) {
                cv::resize(outBgr, outBgr, cv::Size(bgr.cols * 2, bgr.rows * 2), 0, 0, cv::INTER_LINEAR);
            }

            // 与双三次混合：降低「假细节 / 过锐」观感
            if (strength < 0.999f) {
                cv::Mat soft;
                cv::resize(bgr, soft, outBgr.size(), 0, 0, cv::INTER_CUBIC);
                cv::Mat blended;
                cv::addWeighted(outBgr, static_cast<double>(strength), soft,
                    1.0 - static_cast<double>(strength), 0.0, blended);
                outBgr = blended;
                LOG_INFO("超分强度混合 strength=" + std::to_string(strength));
            }
        } catch (const Ort::Exception& e) {
            lastError_ = std::string("Real-ESRGAN 推理失败: ") + e.what();
            return false;
        } catch (const cv::Exception& e) {
            lastError_ = std::string("OpenCV 异常: ") + e.what();
            return false;
        }
    }

    if (!cv::imwrite(nativeOut, outBgr)) {
        lastError_ = "无法写入: " + outputPath;
        return false;
    }
    return true;
}

} // namespace media::core

#else // !ONNX || !OPENCV

namespace media::core {

struct SuperResolution::Impl {};

SuperResolution::~SuperResolution() = default;

bool SuperResolution::loadModel(const std::string&) {
    lastError_ = "未启用 ONNX Runtime 或 OpenCV，请运行 setup_onnxruntime_x64.bat 并重新编译";
    return false;
}

void SuperResolution::unload() {}

bool SuperResolution::isReady() const { return false; }

bool SuperResolution::usesOpenCvFallback() const { return false; }

bool SuperResolution::usesCuda() const { return false; }

const char* SuperResolution::executionProvider() const { return "none"; }

int SuperResolution::modelScale() const { return 4; }

bool SuperResolution::upscaleImageFile(
    const std::string&, const std::string&, int, float)
{
    lastError_ = "超分模块未编译";
    return false;
}

} // namespace media::core

#endif
