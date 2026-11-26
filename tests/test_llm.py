"""Provider selection: local model or a mainstream API (no network)."""
import pytest
from langchain_core.messages import AIMessage

from cn_job_agent import llm
from cn_job_agent.config import Settings



@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "ZHIPUAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def settings(**values):
    return Settings(_env_file=None, **values)


def test_deepseek_resolves_to_its_openai_compatible_endpoint():
    r = llm.resolve(settings(llm_provider="deepseek", llm_model="deepseek-chat", llm_api_key="sk-test"))
    assert r.cloud and r.model == "deepseek-chat" and r.host == "api.deepseek.com"
    assert r.config["base_url"] == "https://api.deepseek.com/v1/chat/completions"
    assert r.config["adapter"] == llm.CLOUD_ADAPTER and r.config["response_format"] == "json_object"
    assert "api.deepseek.com" in r.privacy_note() and "经历库片段" in r.privacy_note()


def test_key_from_the_providers_standard_variable(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env")
    r = llm.resolve(settings(llm_provider="deepseek", llm_model="deepseek-chat"))
    assert r.config["api_key"] == "sk-env"


def test_provider_defaults_and_overrides():
    claude = llm.resolve(settings(llm_provider="anthropic", llm_model="m", llm_api_key="k"))
    assert claude.config["response_format"] == "none"           # prompt-based JSON, validated by the adapter
    zhipu = llm.resolve(settings(llm_provider="zhipu", llm_model="m", llm_api_key="k"))
    assert zhipu.config["base_url"] == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    custom = llm.resolve(settings(llm_provider="openai_compatible", llm_model="m", llm_api_key="k",
                                  llm_base_url="https://llm.example.com/v1/", llm_response_format="none",
                                  llm_context_budget=50_000, llm_max_output_tokens=4000))
    assert custom.config["base_url"] == "https://llm.example.com/v1/chat/completions"
    assert (custom.config["context_budget"], custom.config["max_output_tokens"]) == (50_000, 4000)


@pytest.mark.parametrize("values, message", [
    ({"llm_provider": "nope"}, "未知"),
    ({"llm_provider": "deepseek", "llm_api_key": "k"}, "CN_LLM_MODEL"),
    ({"llm_provider": "deepseek", "llm_model": "m"}, "API key"),
    ({"llm_provider": "openai_compatible", "llm_model": "m", "llm_api_key": "k"}, "CN_LLM_BASE_URL"),
    ({"llm_provider": "openai_compatible", "llm_model": "m", "llm_api_key": "k",
      "llm_base_url": "http://llm.example.com/v1"}, "https"),
    ({"llm_provider": "deepseek", "llm_model": "m", "llm_api_key": "k", "llm_max_output_tokens": 70_000}, "小于"),
])
def test_configuration_errors(values, message):
    with pytest.raises(llm.LLMConfigError, match=message):
        llm.resolve(settings(**values))


def test_the_key_is_not_printed():
    assert "sk-secret" not in repr(settings(llm_api_key="sk-secret"))


def test_json_tasks_go_through_job_rag_starters_adapter(job_rag_home):
    s = settings(llm_provider="deepseek", llm_model="deepseek-chat", llm_api_key="sk-test", job_rag_home=job_rag_home)
    adapter = llm.build_json_llm(s)
    assert adapter.name == llm.CLOUD_ADAPTER and adapter.prompt_char_budget > 0
    chat = adapter.chat_model(30)
    assert chat.model_name == "deepseek-chat" and chat.openai_api_base == "https://api.deepseek.com/v1"
    assert not chat.extra_body                      # no max_tokens duplicate for cloud models

    class Reply:
        def __init__(self, contents):
            self.contents = contents

        def invoke(self, messages, **kwargs):
            assert kwargs["response_format"] == {"type": "json_object"}
            return AIMessage(content=self.contents.pop(0), response_metadata={"finish_reason": "stop"})

    replies = Reply(["不是 JSON", '{"ok": true}'])          # the first answer is retried with a correction
    adapter.chat_model = lambda timeout: replies
    schema = {"type": "object", "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
    assert adapter.generate_json("ping", "只输出 JSON。", {"say": "ok"}, schema) == {"ok": True}


def test_planner_chat_model_uses_the_same_provider():
    chat = llm.build_chat_model(settings(llm_provider="moonshot", llm_model="kimi-model", llm_api_key="k"))
    assert chat.model_name == "kimi-model" and chat.openai_api_base == "https://api.moonshot.cn/v1"
