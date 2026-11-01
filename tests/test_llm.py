import os
import sys
import threading
import time
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
            captured["add_bos"] = add_bos
            return text.split()

        def create_chat_completion(self, messages, max_tokens, temperature):
            captured["messages"] = messages
            captured["max_tokens"] = max_tokens
            captured["temperature"] = temperature
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
    assert captured["temperature"] == 0.0
    assert llm.count_tokens("три слова здесь") == 3
    assert captured["add_bos"] is False


def _llama(monkeypatch, factory):
    module = types.ModuleType("llama_cpp")
    module.Llama = factory
    module.LlamaRAMCache = lambda capacity_bytes: ("cache", capacity_bytes)
    monkeypatch.setitem(sys.modules, "llama_cpp", module)
    monkeypatch.setenv("LLM_MODEL_PATH", "model.gguf")
    monkeypatch.setattr(llm, "_llm", None)
    monkeypatch.setattr(llm, "loaded", False)


def test_load_builds_one_cpu_model(monkeypatch):
    monkeypatch.delenv("LLM_THREADS", raising=False)
    monkeypatch.setattr(llm, "runtime", lambda: {"n_ctx": 2048})
    created = []
    arrived = []
    release = threading.Event()

    class Fake:
        def __init__(self, **kwargs):
            created.append(kwargs)
            if len(created) == 1:
                release.wait(3)

        def set_cache(self, _cache):
            created.append("cache")

    _llama(monkeypatch, Fake)
    errors = []

    def run():
        try:
            arrived.append(threading.get_ident())
            llm.load()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    try:
        for thread in threads:
            thread.start()
        deadline = time.time() + 2
        while len(arrived) < 4 and time.time() < deadline:
            time.sleep(0.01)
        assert len(arrived) == 4
        time.sleep(0.05)
        assert [item for item in created if isinstance(item, dict)] == [{
            "model_path": "model.gguf",
            "n_ctx": 2048,
            "n_threads": max(1, (os.cpu_count() or 2) // 2),
            "n_gpu_layers": 0,
            "verbose": False,
        }]
        release.set()
        for thread in threads:
            thread.join(3)
        assert errors == []
        assert not any(thread.is_alive() for thread in threads)
        assert created.count("cache") == 1
        assert llm.loaded is True
    finally:
        release.set()
        for thread in threads:
            thread.join(3)


def test_complete_follows_runtime_limits_one_call_at_a_time(monkeypatch):
    monkeypatch.setattr(llm, "runtime", lambda: {"n_ctx": 1536, "max_tokens": 40, "temperature": 0.3})
    calls = []
    release = threading.Event()
    entered = threading.Event()
    second_entered = threading.Event()
    active = {"n": 0, "max": 0}

    class Fake:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def set_cache(self, _cache):
            pass

        def create_chat_completion(self, messages, max_tokens, temperature):
            calls.append({"max_tokens": max_tokens, "temperature": temperature, "roles": [item["role"] for item in messages]})
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
            try:
                if sum(1 for item in calls if "max_tokens" in item) == 1:
                    entered.set()
                    assert release.wait(3)
                else:
                    second_entered.set()
                return {"choices": [{"message": {"content": " да "}}]}
            finally:
                active["n"] -= 1

    _llama(monkeypatch, Fake)
    results = []
    started = threading.Event()

    def first():
        results.append(llm.complete("система", "вопрос"))

    def second():
        started.set()
        results.append(llm.complete("система", "ещё", max_tokens=9))

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    try:
        threads[0].start()
        assert entered.wait(2)
        threads[1].start()
        assert started.wait(2)
        assert not second_entered.wait(0.3)
        assert [item for item in calls if "max_tokens" in item] == [{"max_tokens": 40, "temperature": 0.3, "roles": ["system", "user"]}]
        release.set()
        for thread in threads:
            thread.join(3)
        assert results == ["да", "да"]
        assert active["max"] == 1
        assert llm.complete("система", "снова") == "да"
        answers = [item for item in calls if "max_tokens" in item]
        assert answers[1]["max_tokens"] == 9
        assert answers[1]["temperature"] == 0.3
        assert answers[2] == {"max_tokens": 40, "temperature": 0.3, "roles": ["system", "user"]}
        assert calls[0]["n_ctx"] == 1536
        assert calls[0]["n_gpu_layers"] == 0
    finally:
        release.set()
        for thread in threads:
            thread.join(3)
