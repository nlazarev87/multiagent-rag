import sys
import types

import llm


def test_complete_uses_cpu_settings_and_roles(monkeypatch):
    captured = {}

    class Fake:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def set_cache(self, cache):
            captured["cache"] = cache

        def tokenize(self, text, add_bos=True):
            return text.split()

        def create_chat_completion(self, messages, max_tokens, temperature):
            captured["messages"] = messages
            captured["max_tokens"] = max_tokens
            return {"choices": [{"message": {"content": " Ответ [1]. "}}]}

    module = types.ModuleType("llama_cpp")
    module.Llama = Fake
    module.LlamaRAMCache = lambda capacity_bytes: ("cache", capacity_bytes)
    monkeypatch.setattr(llm, "_llm", None)
    monkeypatch.setenv("LLM_MODEL_PATH", "model.gguf")
    monkeypatch.setenv("LLM_THREADS", "2")
    monkeypatch.setitem(sys.modules, "llama_cpp", module)
    assert llm.complete("правила", "вопрос", examples=[("пример", "ответ")]) == "Ответ [1]."
    assert captured["n_ctx"] == 4096
    assert captured["n_threads"] == 2
    assert captured["n_gpu_layers"] == 0
    assert captured["cache"][0] == "cache"
    assert [message["role"] for message in captured["messages"]] == ["system", "user", "assistant", "user"]
    assert captured["max_tokens"] == 200
    assert llm.count_tokens("три слова здесь") == 3
