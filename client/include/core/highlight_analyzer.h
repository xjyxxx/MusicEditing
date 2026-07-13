#pragma once

#include "core/llm_engine.h"

#include <memory>
#include <string>
#include <vector>

namespace media::core {

struct TranscriptSegment {
    double start_sec = 0.0;
    double end_sec = 0.0;
    std::string text;
    float score = 0.0f;
};

struct HighlightAnalyzeParams {
    std::string scene = "演讲金句";
    double min_duration = 3.0;
    double max_duration = 60.0;
    float sensitivity = 0.5f;
};

/// 从 ASR 文稿中识别高光片段（优先 llama，无模型时用规则兜底）
class HighlightAnalyzer {
public:
    explicit HighlightAnalyzer(const std::string& llmModelPath);

    std::vector<TranscriptSegment> parseTranscriptJson(const std::string& jsonPath) const;

    std::vector<TranscriptSegment> analyzeHighlights(
        const std::vector<TranscriptSegment>& transcript,
        const HighlightAnalyzeParams& params,
        std::string* debugInfo = nullptr);

    bool isLlmReady() const;

private:
    std::string llm_model_path_;
    std::unique_ptr<LlmEngine> llm_;

    LlmEngine* getLlm();

    std::vector<TranscriptSegment> fallbackAnalyze(
        const std::vector<TranscriptSegment>& transcript,
        const HighlightAnalyzeParams& params) const;

    std::vector<TranscriptSegment> parseLlmResponse(
        const std::string& response,
        const HighlightAnalyzeParams& params) const;
};

} // namespace media::core
