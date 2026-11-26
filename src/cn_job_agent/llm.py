"""Which language model the agents use: the local model or a mainstream API.

Chosen with CN_LLM_PROVIDER (default "local"). Every cloud provider below is
reached through its OpenAI-compatible endpoint, so one client covers them all:

  JSON tasks   JD requirement extraction and evidence judgment go through
               job_rag_starter's adapter (attempt budget, schema checks,
               verbatim-quote validation, correction messages)
  tool calling the search planner uses a LangChain ChatOpenAI on the same endpoint

Privacy: with a cloud provider, JD text, the search profile and excerpts of
the experiences library are sent to that provider. Nothing falls back from
the local model to a cloud API on its own; the provider is always explicit.
"""
import os
from dataclasses import dataclass
from urllib.parse import urlsplit

from .rag import bridge


@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    base_url: str
    key_env: tuple            # standard environment variables for the key, after CN_LLM_API_KEY
    response_format: str      # json_object | json_schema | none, as the endpoint supports
    context_budget: int       # conservative default, tokens; override with CN_LLM_CONTEXT_BUDGET


# Base URLs are the providers' documented OpenAI-compatible endpoints; override with CN_LLM_BASE_URL
# if a provider moves or you use another region. Model names change often, so none is assumed.
PROVIDERS = {p.key: p for p in [
    Provider("openai", "OpenAI", "https://api.openai.com/v1", ("OPENAI_API_KEY",), "json_object", 128_000),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1", ("DEEPSEEK_API_KEY",), "json_object", 64_000),
    Provider("qwen", "通义千问（阿里云百炼）", "https://dashscope.aliyuncs.com/compatible-mode/v1",
             ("DASHSCOPE_API_KEY",), "json_object", 128_000),
    Provider("zhipu", "智谱 GLM", "https://open.bigmodel.cn/api/paas/v4", ("ZHIPUAI_API_KEY",), "json_object", 128_000),
    Provider("moonshot", "Kimi（月之暗面）", "https://api.moonshot.cn/v1", ("MOONSHOT_API_KEY",), "json_object", 128_000),
    Provider("doubao", "豆包（火山方舟）", "https://ark.cn-beijing.volces.com/api/v3", ("ARK_API_KEY",), "json_object",
             128_000),
    Provider("siliconflow", "硅基流动", "https://api.siliconflow.cn/v1", ("SILICONFLOW_API_KEY",), "json_object",
             64_000),
    Provider("anthropic", "Claude（Anthropic，OpenAI 兼容接口）", "https://api.anthropic.com/v1",
             ("ANTHROPIC_API_KEY",), "none", 200_000),
    Provider("gemini", "Gemini（Google，OpenAI 兼容接口）", "https://generativelanguage.googleapis.com/v1beta/openai",
             ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "none", 128_000),
    Provider("openai_compatible", "其他 OpenAI 兼容服务", "", (), "json_object", 32_000),
]}
LOCAL = "local"
CHOICES = [LOCAL, *PROVIDERS]
CLOUD_ADAPTER = "cn_cloud_openai"


class LLMConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Resolved:
    provider: str
    label: str
    model: str
    base_url: str
    cloud: bool
    config: dict              # job_rag_starter adapter config

    @property
    def host(self):
        return urlsplit(self.base_url).netloc or self.base_url

    def privacy_note(self):
        if not self.cloud:
            return f"本机模型 {self.model}（{self.host}）：数据不出本机"
        return (f"云端 API {self.label} · {self.model}：JD、求职画像和经历库片段会发送到 {self.host}；"
                f"该服务商的数据保留政策以其条款为准")


def _api_key(settings, provider):
    if settings.llm_api_key is not None and settings.llm_api_key.get_secret_value().strip():
        return settings.llm_api_key.get_secret_value().strip()
    for name in provider.key_env:
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    return ""


def resolve(settings):
    """The model settings for the configured provider, in job_rag_starter's adapter format."""
    name = (settings.llm_provider or LOCAL).strip().lower()
    if name == LOCAL:
        local_llm = bridge.load(settings.job_rag_home, "local_llm")
        config = local_llm.load_config(settings.llm_config_file)   # probes the configured local endpoints
        config["diagnostics_dir"] = str(settings.state_dir / "llm_diagnostics")
        return Resolved(LOCAL, "本机模型", config["model"], config["base_url"], False, config)

    provider = PROVIDERS.get(name)
    if provider is None:
        raise LLMConfigError(f"未知的 CN_LLM_PROVIDER={name!r}；可用：{'、'.join(CHOICES)}")
    model = (settings.llm_model or "").strip()
    if not model:
        raise LLMConfigError(f"使用 {provider.label} 需要在 .env 里设置 CN_LLM_MODEL（模型名以服务商文档为准）")
    base_url = (settings.llm_base_url or provider.base_url).strip().rstrip("/")
    if not base_url:
        raise LLMConfigError("openai_compatible 需要在 .env 里设置 CN_LLM_BASE_URL")
    if not base_url.startswith("https://") and urlsplit(base_url).hostname not in ("127.0.0.1", "localhost", "::1"):
        raise LLMConfigError("云端 API 地址必须是 https://")
    api_key = _api_key(settings, provider)
    if not api_key:
        names = "、".join(("CN_LLM_API_KEY",) + provider.key_env)
        raise LLMConfigError(f"使用 {provider.label} 需要 API key：在 .env 里设置 {names} 之一")
    budget = settings.llm_context_budget or provider.context_budget
    max_output = settings.llm_max_output_tokens or 8192
    if max_output >= budget:
        raise LLMConfigError("CN_LLM_MAX_OUTPUT_TOKENS 必须小于上下文窗口")
    config = {
        "adapter": CLOUD_ADAPTER,
        "model": model,
        # The full endpoint path, so providers whose base does not end in /v1 (Zhipu, Doubao) work too.
        "base_url": base_url + "/chat/completions",
        "api_key": api_key,
        "temperature": settings.llm_temperature,
        "context_budget": budget,
        "max_output_tokens": max_output,
        "chars_per_token": 1,
        "timeout_seconds": settings.llm_timeout_seconds,
        "response_format": settings.llm_response_format or provider.response_format,
        "extra_body": {},
        "diagnostics_dir": str(settings.state_dir / "llm_diagnostics"),
    }
    return Resolved(provider.key, provider.label, model, base_url, True, config)


def register_cloud_adapter(job_rag_home):
    """job_rag_starter's LangChain adapter, minus the local-server workaround of
    also sending the old max_tokens field, which some cloud models reject.
    Registered once under CLOUD_ADAPTER."""
    local_llm = bridge.load(job_rag_home, "local_llm")
    if CLOUD_ADAPTER in local_llm.ADAPTERS:
        return local_llm.ADAPTERS[CLOUD_ADAPTER]
    base = bridge.load(job_rag_home, "langchain_client").LangChainOpenAIAdapter

    class CloudOpenAIAdapter(base):
        name = CLOUD_ADAPTER

        def chat_model(self, timeout):
            endpoint = self._endpoint()[: -len("/chat/completions")]
            return self._chat_class(model=self.model, base_url=endpoint, api_key=self.api_key,
                                    temperature=self.temperature, max_tokens=self.max_output_tokens,
                                    timeout=timeout, max_retries=0, extra_body=dict(self.extra_body) or None)

    return local_llm.register_adapter(CloudOpenAIAdapter)


def build_json_llm(settings, resolved=None):
    """The adapter jd_parser and EvidenceMatcher call (generate_json and friends)."""
    resolved = resolved or resolve(settings)
    local_llm = bridge.load(settings.job_rag_home, "local_llm")
    if resolved.cloud:
        register_cloud_adapter(settings.job_rag_home)
    return local_llm.build_llm(resolved.config)


def tracing_off():
    """Prompts carry personal material; LangSmith tracing must never upload them."""
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGCHAIN_TRACING"):
        os.environ[name] = "false"


def build_chat_model(settings, resolved=None):
    """A LangChain chat model with tool calling, on the same provider."""
    from langchain_openai import ChatOpenAI
    tracing_off()
    resolved = resolved or resolve(settings)
    config = resolved.config
    base = config["base_url"]
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return ChatOpenAI(model=config["model"], base_url=base, api_key=config.get("api_key") or "local",
                      temperature=config.get("temperature", 0), timeout=config.get("timeout_seconds", 300),
                      max_retries=2, extra_body=config.get("extra_body") or None)
