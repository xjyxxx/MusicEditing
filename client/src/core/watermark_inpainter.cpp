#include "core/watermark_inpainter.h"

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
#include <vector>

#if defined(MUSIC_HAS_ONNXRUNTIME) && defined(MUSIC_HAS_OPENCV)

#include <onnxruntime_cxx_api.h>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/photo.hpp>

namespace media::core {

namespace {

constexpr int kPad = 16;

int alignUp(int v, int align) {
    if (align <= 1) return v;
    return ((v + align - 1) / align) * align;
}

void fillMaskRect(cv::Mat& mask, const WatermarkRegion& r, int ox, int oy) {
    const int x0 = std::max(0, r.x - ox);
    const int y0 = std::max(0, r.y - oy);
    const int x1 = std::min(mask.cols, x0 + r.w);
    const int y1 = std::min(mask.rows, y0 + r.h);
    if (x1 > x0 && y1 > y0) {
        mask(cv::Rect(x0, y0, x1 - x0, y1 - y0)).setTo(255);
    }
}

cv::Rect unionRegions(const std::vector<WatermarkRegion>& regions, int frameW, int frameH, int pad) {
    if (regions.empty()) return {};
    int x0 = frameW, y0 = frameH, x1 = 0, y1 = 0;
    for (const auto& r : regions) {
        if (r.w <= 0 || r.h <= 0) continue;
        x0 = std::min(x0, r.x);
        y0 = std::min(y0, r.y);
        x1 = std::max(x1, r.x + r.w);
        y1 = std::max(y1, r.y + r.h);
    }
    x0 = std::max(0, x0 - pad);
    y0 = std::max(0, y0 - pad);
    x1 = std::min(frameW, x1 + pad);
    y1 = std::min(frameH, y1 + pad);
    return cv::Rect(x0, y0, std::max(0, x1 - x0), std::max(0, y1 - y0));
}

void imageToNchw(const cv::Mat& bgr, std::vector<float>& out) {
    cv::Mat rgb;
    cv::cvtColor(bgr, rgb, cv::COLOR_BGR2RGB);
    const int h = rgb.rows;
    const int w = rgb.cols;
    out.resize(static_cast<size_t>(3 * h * w));
    for (int y = 0; y < h; ++y) {
        const uint8_t* row = rgb.ptr<uint8_t>(y);
        for (int x = 0; x < w; ++x) {
            for (int c = 0; c < 3; ++c) {
                out[static_cast<size_t>(c * h * w + y * w + x)] =
                    row[x * 3 + c] / 255.0f;
            }
        }
    }
}

void maskToNchw(const cv::Mat& mask, std::vector<float>& out) {
    const int h = mask.rows;
    const int w = mask.cols;
    out.resize(static_cast<size_t>(h * w));
    for (int y = 0; y < h; ++y) {
        const uint8_t* row = mask.ptr<uint8_t>(y);
        for (int x = 0; x < w; ++x) {
            out[static_cast<size_t>(y * w + x)] = row[x] > 127 ? 1.0f : 0.0f;
        }
    }
}

void nchwToBgr(const std::vector<float>& nchw, int h, int w, cv::Mat& bgr) {
    const size_t plane = static_cast<size_t>(h * w);
    const size_t total = plane * 3;
    float maxV = 0.0f;
    for (size_t i = 0; i < total && i < nchw.size(); ++i) {
        maxV = std::max(maxV, nchw[i]);
    }
    // Carve LaMa ONNX 直接输出 0~255 float，而非 PyTorch 版的 0~1
    const bool outputIs255 = maxV > 1.5f;

    cv::Mat rgb(h, w, CV_8UC3);
    for (int y = 0; y < h; ++y) {
        uint8_t* row = rgb.ptr<uint8_t>(y);
        for (int x = 0; x < w; ++x) {
            for (int c = 0; c < 3; ++c) {
                float v = nchw[static_cast<size_t>(c * plane + y * w + x)];
                if (outputIs255) {
                    v = std::clamp(v, 0.0f, 255.0f);
                    row[x * 3 + c] = static_cast<uint8_t>(v + 0.5f);
                } else {
                    v = std::clamp(v, 0.0f, 1.0f);
                    row[x * 3 + c] = static_cast<uint8_t>(v * 255.0f + 0.5f);
                }
            }
        }
    }
    cv::cvtColor(rgb, bgr, cv::COLOR_RGB2BGR);
}

void fillMaskRectFull(cv::Mat& mask, const WatermarkRegion& r) {
    const int x0 = std::max(0, r.x);
    const int y0 = std::max(0, r.y);
    const int x1 = std::min(mask.cols, x0 + r.w);
    const int y1 = std::min(mask.rows, y0 + r.h);
    if (x1 > x0 && y1 > y0) {
        mask(cv::Rect(x0, y0, x1 - x0, y1 - y0)).setTo(255);
    }
}

bool inpaintWithOpenCv(cv::Mat& bgr, const std::vector<WatermarkRegion>& regions) {
    cv::Mat mask = cv::Mat::zeros(bgr.rows, bgr.cols, CV_8UC1);
    for (const auto& r : regions) {
        fillMaskRectFull(mask, r);
    }
    if (cv::countNonZero(mask) == 0) {
        return false;
    }
    cv::Mat result;
    cv::inpaint(bgr, mask, result, 5, cv::INPAINT_TELEA);
    result.copyTo(bgr);
    return true;
}

bool preferCudaFromEnv() {
    // 默认 CPU：项目不再捆绑 third_party/cuda_runtime
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

/// MUSIC_WATERMARK_BACKEND=opencv|lama|auto（默认 auto）
bool preferOpenCvBackend() {
    const char* v = std::getenv("MUSIC_WATERMARK_BACKEND");
    if (!v || !*v) {
        return false;
    }
    std::string s(v);
    for (char& c : s) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return s == "opencv" || s == "cv" || s == "fast";
}

} // namespace

struct WatermarkInpainter::Impl {
    Ort::Env env{ORT_LOGGING_LEVEL_WARNING, "MusicEditing"};
    std::unique_ptr<Ort::Session> session;
    std::string inputImageName = "image";
    std::string inputMaskName = "mask";
    std::string outputName = "inpainted";
    bool ready = false;
    bool useOpenCvFallback = false;
    bool useCuda = false;
};

WatermarkInpainter::~WatermarkInpainter() {
    delete impl_;
    impl_ = nullptr;
}

bool WatermarkInpainter::loadModel(const std::string& modelPath) {
    lastError_.clear();

    if (!impl_) impl_ = new Impl();
    impl_->useOpenCvFallback = false;
    impl_->useCuda = false;
    impl_->session.reset();

    // 快速模式：跳过 LaMa，直接 OpenCV inpaint（视频默认）
    if (preferOpenCvBackend()) {
        impl_->useOpenCvFallback = true;
        impl_->useCuda = false;
        impl_->ready = true;
        LOG_INFO("去水印后端: OpenCV inpaint（快速模式，跳过 LaMa）");
        return true;
    }

    if (!media::common::fileExists(modelPath)) {
        lastError_ = "模型文件不存在: " + modelPath;
        return false;
    }

    const std::wstring wpath = media::common::utf8PathToWide(modelPath);

    const bool wantCuda = preferCudaFromEnv();
    bool cudaAttempted = false;
    std::string onnxError;

    auto tryCreate = [&](bool useCuda, GraphOptimizationLevel level) -> bool {
        Ort::SessionOptions opts;
        opts.SetIntraOpNumThreads(useCuda ? 1 : 4);
        opts.SetGraphOptimizationLevel(level);
        if (useCuda) {
            OrtCUDAProviderOptions cudaOpts{};
            cudaOpts.device_id = 0;
            opts.AppendExecutionProvider_CUDA(cudaOpts);
            cudaAttempted = true;
        }
#ifdef _WIN32
        impl_->session = std::make_unique<Ort::Session>(
            impl_->env, wpath.c_str(), opts);
#else
        impl_->session = std::make_unique<Ort::Session>(
            impl_->env, modelPath.c_str(), opts);
#endif
        Ort::AllocatorWithDefaultOptions allocator;
        if (impl_->session->GetInputCount() >= 2) {
            impl_->inputImageName = impl_->session->GetInputNameAllocated(0, allocator).get();
            impl_->inputMaskName = impl_->session->GetInputNameAllocated(1, allocator).get();
        }
        if (impl_->session->GetOutputCount() >= 1) {
            impl_->outputName = impl_->session->GetOutputNameAllocated(0, allocator).get();
        }
        impl_->useCuda = useCuda;
        impl_->useOpenCvFallback = false;
        impl_->ready = true;
        return true;
    };

    // LaMa ONNX 的 DFT 节点在 ORT_ENABLE_ALL 下常失败，CUDA 时优先 DISABLE_ALL
    const GraphOptimizationLevel cudaLevels[] = {
        GraphOptimizationLevel::ORT_DISABLE_ALL,
        GraphOptimizationLevel::ORT_ENABLE_ALL,
    };
    const GraphOptimizationLevel cpuLevels[] = {
        GraphOptimizationLevel::ORT_ENABLE_ALL,
        GraphOptimizationLevel::ORT_DISABLE_ALL,
    };

    const bool cudaModes[] = {true, false};
    for (bool useCuda : cudaModes) {
        if (useCuda && !wantCuda) {
            continue;
        }
        const GraphOptimizationLevel* levels = useCuda ? cudaLevels : cpuLevels;
        const int levelCount = 2;
        for (int li = 0; li < levelCount; ++li) {
            try {
                if (!tryCreate(useCuda, levels[li])) {
                    continue;
                }
                LOG_INFO(std::string("LaMa ONNX 模型已加载: ") + modelPath
                    + (useCuda ? " [CUDA EP]" : " [CPU EP]"));
                return true;
            } catch (const Ort::Exception& e) {
                onnxError = e.what();
                impl_->session.reset();
                impl_->useCuda = false;
                if (useCuda) {
                    LOG_WARN(std::string("ONNX Session 创建失败（")
                        + (li == 0 ? "DISABLE_ALL" : "ENABLE_ALL")
                        + "），尝试下一配置: " + e.what());
                }
            }
        }
    }

    if (wantCuda && !cudaAttempted) {
        LOG_WARN("已请求 CUDA，但未能启用 CUDA EP");
    }
    LOG_WARN("LaMa ONNX 不可用 (" + onnxError + ")，回退 OpenCV inpaint");
    impl_->useOpenCvFallback = true;
    impl_->useCuda = false;
    impl_->ready = true;
    return true;
}

void WatermarkInpainter::unload() {
    if (impl_) {
        impl_->session.reset();
        impl_->ready = false;
        impl_->useOpenCvFallback = false;
        impl_->useCuda = false;
    }
    lastError_.clear();
}

bool WatermarkInpainter::isReady() const {
    return impl_ && impl_->ready;
}

bool WatermarkInpainter::usesOpenCvFallback() const {
    return impl_ && impl_->ready && impl_->useOpenCvFallback;
}

bool WatermarkInpainter::usesCuda() const {
    return impl_ && impl_->ready && impl_->useCuda && !impl_->useOpenCvFallback;
}

const char* WatermarkInpainter::executionProvider() const {
    if (!impl_ || !impl_->ready) {
        return "none";
    }
    if (impl_->useOpenCvFallback) {
        return "opencv";
    }
    return impl_->useCuda ? "cuda" : "cpu";
}

bool WatermarkInpainter::inpaintRgbFrame(
    uint8_t* rgb,
    int width,
    int height,
    int strideBytes,
    const std::vector<WatermarkRegion>& regions)
{
    lastError_.clear();
    if (!isReady()) {
        lastError_ = "LaMa 模型未加载";
        return false;
    }
    if (!rgb || width <= 0 || height <= 0 || regions.empty()) {
        lastError_ = "参数无效";
        return false;
    }

    const int step = strideBytes > 0 ? strideBytes : width * 3;
    cv::Mat frame(height, width, CV_8UC3, rgb, static_cast<size_t>(step));
    cv::Mat bgr;
    cv::cvtColor(frame, bgr, cv::COLOR_RGB2BGR);

    if (impl_->useOpenCvFallback) {
        if (!inpaintWithOpenCv(bgr, regions)) {
            lastError_ = "OpenCV 修复失败";
            return false;
        }
        cv::Mat rgbOut;
        cv::cvtColor(bgr, rgbOut, cv::COLOR_BGR2RGB);
        rgbOut.copyTo(frame);
        return true;
    }

    const cv::Rect roi = unionRegions(regions, width, height, kPad);
    if (roi.width <= 0 || roi.height <= 0) {
        lastError_ = "水印区域无效";
        return false;
    }

    cv::Mat crop = bgr(roi).clone();
    cv::Mat mask = cv::Mat::zeros(roi.height, roi.width, CV_8UC1);
    for (const auto& r : regions) {
        fillMaskRect(mask, r, roi.x, roi.y);
    }

    int modelH = 512;
    int modelW = 512;
    if (impl_->session) {
        auto inShape = impl_->session->GetInputTypeInfo(0)
            .GetTensorTypeAndShapeInfo().GetShape();
        if (inShape.size() >= 4) {
            if (inShape[2] > 0) modelH = static_cast<int>(inShape[2]);
            if (inShape[3] > 0) modelW = static_cast<int>(inShape[3]);
        }
    }

    cv::Mat modelImage;
    cv::Mat modelMask;
    cv::resize(crop, modelImage, cv::Size(modelW, modelH));
    cv::resize(mask, modelMask, cv::Size(modelW, modelH));

    std::vector<float> imageTensor;
    std::vector<float> maskTensor;
    imageToNchw(modelImage, imageTensor);
    maskToNchw(modelMask, maskTensor);

    try {
        auto memoryInfo = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
        std::vector<int64_t> imageShape = {1, 3, modelH, modelW};
        std::vector<int64_t> maskShape = {1, 1, modelH, modelW};

        Ort::Value imageValue = Ort::Value::CreateTensor<float>(
            memoryInfo, imageTensor.data(), imageTensor.size(),
            imageShape.data(), imageShape.size());
        Ort::Value maskValue = Ort::Value::CreateTensor<float>(
            memoryInfo, maskTensor.data(), maskTensor.size(),
            maskShape.data(), maskShape.size());

        const char* inputNames[] = {impl_->inputImageName.c_str(), impl_->inputMaskName.c_str()};
        const char* outputNames[] = {impl_->outputName.c_str()};
        std::array<Ort::Value, 2> inputs = {std::move(imageValue), std::move(maskValue)};

        auto outputs = impl_->session->Run(
            Ort::RunOptions{nullptr},
            inputNames, inputs.data(), inputs.size(),
            outputNames, 1);

        float* outData = outputs[0].GetTensorMutableData<float>();
        auto outInfo = outputs[0].GetTensorTypeAndShapeInfo();
        auto outShape = outInfo.GetShape();
        int outH = static_cast<int>(outShape[2]);
        int outW = static_cast<int>(outShape[3]);
        if (outH <= 0 || outW <= 0) {
            throw Ort::Exception("invalid output shape", ORT_INVALID_ARGUMENT);
        }
        const size_t elemCount = outInfo.GetElementCount();
        const size_t expected = static_cast<size_t>(3) * static_cast<size_t>(outH) * static_cast<size_t>(outW);
        if (elemCount < expected) {
            throw Ort::Exception("output tensor too small", ORT_INVALID_ARGUMENT);
        }

        std::vector<float> outVec(outData, outData + expected);
        cv::Mat resultBgr;
        nchwToBgr(outVec, outH, outW, resultBgr);
        cv::resize(resultBgr, resultBgr, cv::Size(roi.width, roi.height));
        resultBgr.copyTo(bgr(roi));

        cv::Mat rgbOut;
        cv::cvtColor(bgr, rgbOut, cv::COLOR_BGR2RGB);
        rgbOut.copyTo(frame);
        return true;
    } catch (const Ort::Exception& e) {
        LOG_WARN(std::string("LaMa 推理失败，回退 OpenCV: ") + e.what());
        if (!inpaintWithOpenCv(bgr, regions)) {
            lastError_ = std::string("ONNX 推理失败: ") + e.what();
            LOG_ERROR(lastError_);
            return false;
        }
        cv::Mat rgbOut;
        cv::cvtColor(bgr, rgbOut, cv::COLOR_BGR2RGB);
        rgbOut.copyTo(frame);
        return true;
    }
}

bool WatermarkInpainter::inpaintImageFile(
    const std::string& inputPath,
    const std::string& outputPath,
    const std::vector<WatermarkRegion>& regions)
{
    const std::string nativeIn = media::common::pathUtf8ToNative(inputPath);
    const std::string nativeOut = media::common::pathUtf8ToNative(outputPath);
    cv::Mat bgr = cv::imread(nativeIn, cv::IMREAD_COLOR);
    if (bgr.empty()) {
        lastError_ = "无法读取图像: " + inputPath;
        return false;
    }

    cv::Mat rgb;
    cv::cvtColor(bgr, rgb, cv::COLOR_BGR2RGB);
    if (!inpaintRgbFrame(rgb.data, rgb.cols, rgb.rows, 0, regions)) {
        return false;
    }

    cv::Mat outBgr;
    cv::cvtColor(rgb, outBgr, cv::COLOR_RGB2BGR);
    if (!cv::imwrite(nativeOut, outBgr)) {
        lastError_ = "无法写入: " + outputPath;
        return false;
    }
    return true;
}

} // namespace media::core

#else // !ONNX || !OPENCV

namespace media::core {

struct WatermarkInpainter::Impl {};

WatermarkInpainter::~WatermarkInpainter() = default;

bool WatermarkInpainter::loadModel(const std::string&) {
    lastError_ = "未启用 ONNX Runtime 或 OpenCV，请运行 setup_onnxruntime_x64.bat 并重新编译";
    return false;
}

void WatermarkInpainter::unload() {}

bool WatermarkInpainter::isReady() const { return false; }

bool WatermarkInpainter::usesOpenCvFallback() const { return false; }

bool WatermarkInpainter::usesCuda() const { return false; }

const char* WatermarkInpainter::executionProvider() const { return "none"; }

bool WatermarkInpainter::inpaintRgbFrame(
    uint8_t*, int, int, int, const std::vector<WatermarkRegion>&)
{
    lastError_ = "去水印模块未编译";
    return false;
}

bool WatermarkInpainter::inpaintImageFile(
    const std::string&, const std::string&, const std::vector<WatermarkRegion>&)
{
    lastError_ = "去水印模块未编译";
    return false;
}

} // namespace media::core

#endif
