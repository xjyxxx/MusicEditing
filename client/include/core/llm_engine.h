#pragma once

#include <memory>
#include <mutex>
#include <string>

namespace media::core {

struct LlmConfig {
    std::string model_path;
    int n_gpu_layers = 0;
    int n_ctx = 4096;
    int n_predict = 512;
};

/// 基于 llama.cpp 的本地 LLM 引擎
class LlmEngine {
public:
    explicit LlmEngine(const LlmConfig& config);
    ~LlmEngine();

    LlmEngine(const LlmEngine&) = delete;
    LlmEngine& operator=(const LlmEngine&) = delete;

    bool isReady() const;
    std::string generate(const std::string& prompt);

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace media::core
