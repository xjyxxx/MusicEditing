#include "core/highlight_analyzer.h"
#include "core/llm_engine.h"

#include "common/logger.h"
#include "common/utils.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <sstream>

namespace media::core {

namespace {

std::string trim(const std::string& s) {
    size_t b = 0, e = s.size();
    while (b < e && std::isspace(static_cast<unsigned char>(s[b]))) ++b;
    while (e > b && std::isspace(static_cast<unsigned char>(s[e - 1]))) --e;
    return s.substr(b, e - b);
}

double parseJsonNumber(const std::string& json, const std::string& key, size_t from, size_t* pos) {
    const std::string pat = "\"" + key + "\":";
    size_t p = json.find(pat, from);
    if (p == std::string::npos) return 0.0;
    p += pat.size();
    while (p < json.size() && std::isspace(static_cast<unsigned char>(json[p]))) ++p;
    size_t end = p;
    while (end < json.size() && (std::isdigit(static_cast<unsigned char>(json[end]))
           || json[end] == '.' || json[end] == '-')) ++end;
    if (pos) *pos = end;
    try {
        return std::stod(json.substr(p, end - p));
    } catch (...) {
        return 0.0;
    }
}

std::string parseJsonString(const std::string& json, const std::string& key, size_t from) {
    const std::string pat = "\"" + key + "\"";
    size_t p = json.find(pat, from);
    if (p == std::string::npos) return "";
    p += pat.size();
    while (p < json.size() && std::isspace(static_cast<unsigned char>(json[p]))) ++p;
    if (p >= json.size() || json[p] != ':') return "";
    ++p;
    while (p < json.size() && std::isspace(static_cast<unsigned char>(json[p]))) ++p;
    if (p >= json.size() || json[p] != '"') return "";
    ++p;
    std::string out;
    while (p < json.size() && json[p] != '"') {
        if (json[p] == '\\' && p + 1 < json.size()) {
            out += json[p + 1];
            p += 2;
        } else {
            out += json[p++];
        }
    }
    return out;
}

std::string buildPrompt(const std::vector<TranscriptSegment>& transcript,
                        const HighlightAnalyzeParams& params) {
    std::ostringstream oss;
    oss << "你是本地视频剪辑助手。请从以下带时间戳的语音识别文稿中，选出"
        << params.scene << "的精彩片段。\n"
        << "要求：每段时长在 " << params.min_duration << "～" << params.max_duration
        << " 秒之间；敏感度 " << params.sensitivity
        << "（越高选出越多）。优先选观点鲜明、情绪饱满、信息密度高的句子。\n\n"
        << "文稿：\n";
    for (size_t i = 0; i < transcript.size(); ++i) {
        oss << i + 1 << ". [" << transcript[i].start_sec << "s-" << transcript[i].end_sec
            << "s] " << transcript[i].text << "\n";
    }
    oss << "\n请只输出多行，每行格式：HIGHLIGHT|开始秒|结束秒|0-1得分|简短理由\n"
        << "不要输出其他内容。\n";
    return oss.str();
}

} // namespace

HighlightAnalyzer::HighlightAnalyzer(const std::string& llmModelPath)
    : llm_model_path_(llmModelPath) {}

LlmEngine* HighlightAnalyzer::getLlm() {
    if (llm_model_path_.empty() || llm_model_path_ == "none") {
        return nullptr;
    }
    if (!media::common::fileExists(llm_model_path_)) {
        return nullptr;
    }
    if (!llm_) {
        LlmConfig cfg;
        cfg.model_path = llm_model_path_;
        cfg.n_predict = 512;
        llm_ = std::make_unique<LlmEngine>(cfg);
    }
    return llm_ ? llm_.get() : nullptr;
}

std::vector<TranscriptSegment> HighlightAnalyzer::parseTranscriptJson(
    const std::string& jsonPath) const {
    std::ifstream file(jsonPath);
    if (!file.is_open()) {
        LOG_ERROR("无法打开 transcript: " + jsonPath);
        return {};
    }
    std::ostringstream ss;
    ss << file.rdbuf();
    const std::string json = ss.str();

    std::vector<TranscriptSegment> segments;
    size_t pos = json.find("\"segments\"");
    if (pos == std::string::npos) pos = 0;

    size_t search = pos;
    while (search < json.size()) {
        size_t obj = json.find("{", search);
        if (obj == std::string::npos) break;

        size_t endObj = json.find("}", obj);
        if (endObj == std::string::npos) break;

        const std::string block = json.substr(obj, endObj - obj + 1);
        if (block.find("\"start\"") == std::string::npos) {
            search = obj + 1;
            continue;
        }

        size_t p = 0;
        double start = parseJsonNumber(block, "start", 0, &p);
        double end = parseJsonNumber(block, "end", 0, &p);
        std::string text = parseJsonString(block, "text", 0);

        if (end > start && !text.empty()) {
            TranscriptSegment seg;
            seg.start_sec = start;
            seg.end_sec = end;
            seg.text = text;
            segments.push_back(seg);
        }
        search = endObj + 1;
        if (segments.size() > 500) break;
    }

    if (segments.empty()) {
        LOG_WARN("transcript JSON 未解析到有效片段");
    }
    return segments;
}

std::vector<TranscriptSegment> HighlightAnalyzer::parseLlmResponse(
    const std::string& response,
    const HighlightAnalyzeParams& params) const {
    std::vector<TranscriptSegment> out;
    std::istringstream iss(response);
    std::string line;
    while (std::getline(iss, line)) {
        line = trim(line);
        if (line.rfind("HIGHLIGHT|", 0) != 0) continue;
        const std::string body = line.substr(10);
        std::vector<std::string> parts;
        std::istringstream ps(body);
        std::string part;
        while (std::getline(ps, part, '|')) parts.push_back(trim(part));
        if (parts.size() < 3) continue;

        TranscriptSegment seg;
        try {
            seg.start_sec = std::stod(parts[0]);
            seg.end_sec = std::stod(parts[1]);
            seg.score = parts.size() > 2 ? std::stof(parts[2]) : 0.7f;
        } catch (...) {
            continue;
        }
        if (seg.end_sec - seg.start_sec < params.min_duration) continue;
        if (seg.end_sec - seg.start_sec > params.max_duration) {
            seg.end_sec = seg.start_sec + params.max_duration;
        }
        out.push_back(seg);
    }
    return out;
}

std::vector<TranscriptSegment> HighlightAnalyzer::fallbackAnalyze(
    const std::vector<TranscriptSegment>& transcript,
    const HighlightAnalyzeParams& params) const {
    std::vector<TranscriptSegment> scored = transcript;
    for (auto& seg : scored) {
        const double dur = seg.end_sec - seg.start_sec;
        const double lenScore = std::min(1.0, seg.text.size() / 80.0);
        const double durScore = (dur >= params.min_duration && dur <= params.max_duration) ? 1.0 : 0.3;
        seg.score = static_cast<float>((lenScore * 0.6 + durScore * 0.4) * (0.5 + params.sensitivity * 0.5));
    }

    std::sort(scored.begin(), scored.end(),
        [](const TranscriptSegment& a, const TranscriptSegment& b) {
            return a.score > b.score;
        });

    const size_t maxCount = static_cast<size_t>(3 + params.sensitivity * 12);
    if (scored.size() > maxCount) scored.resize(maxCount);
    return scored;
}

std::vector<TranscriptSegment> HighlightAnalyzer::analyzeHighlights(
    const std::vector<TranscriptSegment>& transcript,
    const HighlightAnalyzeParams& params,
    std::string* debugInfo) {
    if (transcript.empty()) return {};

    LlmEngine* llm = getLlm();
    if (llm && llm->isReady()) {
        const std::string prompt = buildPrompt(transcript, params);
        const std::string response = llm->generate(prompt);
        if (debugInfo) *debugInfo = response;

        auto highlights = parseLlmResponse(response, params);
        if (!highlights.empty()) {
            LOG_INFO("LLM 识别高光 " + std::to_string(highlights.size()) + " 段");
            return highlights;
        }
        LOG_WARN("LLM 输出无法解析，使用规则兜底");
    } else {
        LOG_WARN("LLM 未就绪，使用规则兜底分析");
    }

    return fallbackAnalyze(transcript, params);
}

bool HighlightAnalyzer::isLlmReady() const {
    return llm_ && llm_->isReady();
}

} // namespace media::core
