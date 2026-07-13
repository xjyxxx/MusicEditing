#include "core/llm_engine.h"

#include "common/logger.h"

#include "llama.h"

#include <mutex>
#include <vector>

namespace media::core {

struct LlmEngine::Impl {
    llama_model* model = nullptr;
    llama_context* ctx = nullptr;
    llama_sampler* sampler = nullptr;
    const llama_vocab* vocab = nullptr;
    bool ready = false;
    int n_predict = 512;
    std::mutex mutex;
};

LlmEngine::LlmEngine(const LlmConfig& config) : impl_(std::make_unique<Impl>()) {
    impl_->n_predict = config.n_predict;

    if (config.model_path.empty()) {
        LOG_WARN("未配置 LLM 模型路径");
        return;
    }

    LOG_INFO("正在加载 LLM: " + config.model_path);
    ggml_backend_load_all();

    llama_model_params model_params = llama_model_default_params();
    model_params.n_gpu_layers = config.n_gpu_layers;

    impl_->model = llama_model_load_from_file(config.model_path.c_str(), model_params);
    if (!impl_->model) {
        LOG_ERROR("LLM 模型加载失败");
        return;
    }

    impl_->vocab = llama_model_get_vocab(impl_->model);

    llama_context_params ctx_params = llama_context_default_params();
    ctx_params.n_ctx = config.n_ctx;
    ctx_params.n_batch = config.n_ctx;
    ctx_params.no_perf = true;

    impl_->ctx = llama_init_from_model(impl_->model, ctx_params);
    if (!impl_->ctx) {
        LOG_ERROR("LLM 上下文创建失败");
        llama_model_free(impl_->model);
        impl_->model = nullptr;
        return;
    }

    auto sparams = llama_sampler_chain_default_params();
    sparams.no_perf = true;
    impl_->sampler = llama_sampler_chain_init(sparams);
    llama_sampler_chain_add(impl_->sampler, llama_sampler_init_greedy());

    impl_->ready = true;
    LOG_INFO("LLM 加载成功");
}

LlmEngine::~LlmEngine() {
    if (impl_->sampler) llama_sampler_free(impl_->sampler);
    if (impl_->ctx) llama_free(impl_->ctx);
    if (impl_->model) llama_model_free(impl_->model);
}

bool LlmEngine::isReady() const {
    return impl_->ready;
}

std::string LlmEngine::generate(const std::string& prompt) {
    if (!impl_->ready) return "";

    std::lock_guard<std::mutex> lock(impl_->mutex);
    llama_memory_clear(llama_get_memory(impl_->ctx), true);

    const int n_prompt = -llama_tokenize(
        impl_->vocab, prompt.c_str(), static_cast<int32_t>(prompt.size()),
        nullptr, 0, true, true);
    if (n_prompt <= 0) return "";

    std::vector<llama_token> tokens(static_cast<size_t>(n_prompt));
    if (llama_tokenize(impl_->vocab, prompt.c_str(), static_cast<int32_t>(prompt.size()),
            tokens.data(), n_prompt, true, true) < 0) {
        return "";
    }

    llama_batch batch = llama_batch_get_one(tokens.data(), n_prompt);

    if (llama_model_has_encoder(impl_->model)) {
        if (llama_encode(impl_->ctx, batch)) return "";
        llama_token start = llama_model_decoder_start_token(impl_->model);
        if (start == LLAMA_TOKEN_NULL) start = llama_vocab_bos(impl_->vocab);
        batch = llama_batch_get_one(&start, 1);
    }

    std::string result;
    result.reserve(1024);

    for (int i = 0; i < impl_->n_predict; ++i) {
        if (llama_decode(impl_->ctx, batch)) break;

        llama_token tok = llama_sampler_sample(impl_->sampler, impl_->ctx, -1);
        if (llama_vocab_is_eog(impl_->vocab, tok)) break;

        char buf[256];
        int n = llama_token_to_piece(impl_->vocab, tok, buf, sizeof(buf), 0, true);
        if (n > 0) result.append(buf, static_cast<size_t>(n));

        batch = llama_batch_get_one(&tok, 1);
    }

    return result;
}

} // namespace media::core
