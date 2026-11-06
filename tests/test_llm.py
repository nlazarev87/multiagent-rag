import os
import sys
import threading
import time
import types
from pathlib import Path

import pytest

import llm


@pytest.fixture(autouse=True)
def _isolate_model_persistence(monkeypatch):
    """load_model теперь сохраняет выбор; в тестах запись выключена по умолчанию."""
    monkeypatch.setattr(llm.model_registry, "save_selected_model", lambda model_id: None)


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
    assert [message["role"] for message in captured["messages"]] == [
        "system",
        "user",
        "assistant",
        "user",
    ]
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
    monkeypatch.setattr(llm, "_state", llm.UNLOADED)
    monkeypatch.setattr(llm, "_model_id", None)
    monkeypatch.setattr(llm, "_model_name", "")
    monkeypatch.setattr(llm, "_model_path", "")


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
        assert [item for item in created if isinstance(item, dict)] == [
            {
                "model_path": "model.gguf",
                "n_ctx": 2048,
                "n_threads": max(1, (os.cpu_count() or 2) // 2),
                "n_gpu_layers": 0,
                "verbose": False,
            }
        ]
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
    monkeypatch.setattr(
        llm, "runtime", lambda: {"n_ctx": 1536, "max_tokens": 40, "temperature": 0.3}
    )
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
            calls.append(
                {
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "roles": [item["role"] for item in messages],
                }
            )
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
        assert [item for item in calls if "max_tokens" in item] == [
            {"max_tokens": 40, "temperature": 0.3, "roles": ["system", "user"]}
        ]
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


def test_status_starts_unloaded(monkeypatch):
    monkeypatch.setattr(llm, "_llm", None)
    monkeypatch.setattr(llm, "loaded", False)
    monkeypatch.setattr(llm, "_state", llm.UNLOADED)
    monkeypatch.setattr(llm, "_model_id", None)
    monkeypatch.setattr(llm, "_model_name", "")
    monkeypatch.setattr(llm, "_model_path", "")
    assert llm.status()["state"] == "unloaded"
    assert llm.current_model_id() is None


def test_load_model_sets_identity(monkeypatch):
    class Fake:
        def __init__(self, **kwargs):
            pass

        def set_cache(self, cache):
            pass

        def close(self):
            pass

    _llama(monkeypatch, Fake)
    llm.load_model(path="other.gguf", model_id="qvikhr")
    assert llm.status()["state"] == "ready"
    assert llm.current_model_id() == "qvikhr"
    assert llm.model_name() == "other"
    assert llm.status()["model_path"] == "other.gguf"


def test_switch_closes_old_and_loads_new(monkeypatch):
    built = []
    closed = []

    class Fake:
        def __init__(self, **kwargs):
            built.append(kwargs["model_path"])

        def set_cache(self, cache):
            pass

        def close(self):
            closed.append(1)

    _llama(monkeypatch, Fake)
    llm.load()
    llm.switch_model(path="other.gguf")
    assert built == ["model.gguf", "other.gguf"]
    assert closed == [1]
    assert llm.status()["state"] == "ready"


def test_switch_error_rolls_back(monkeypatch):
    built = []
    closed = []

    class Good:
        def __init__(self, **kwargs):
            built.append(kwargs["model_path"])

        def set_cache(self, cache):
            pass

        def close(self):
            closed.append(1)

    def bad_factory(**kwargs):
        built.append(kwargs["model_path"])
        raise RuntimeError("no memory")

    _llama(monkeypatch, Good)
    llm.load()
    monkeypatch.setattr(sys.modules["llama_cpp"], "Llama", bad_factory)
    with pytest.raises(llm.ModelError):
        llm.load_model(path="bad.gguf")
    assert llm.status()["state"] == "ready"
    assert llm.model_name() == "model"
    assert closed == []
    assert built == ["model.gguf", "bad.gguf"]


def test_unload_closes_model(monkeypatch):
    closed = []

    class Fake:
        def __init__(self, **kwargs):
            pass

        def set_cache(self, cache):
            pass

        def close(self):
            closed.append(1)

    _llama(monkeypatch, Fake)
    llm.load()
    llm.unload()
    assert closed == [1]
    assert llm.status()["state"] == "unloaded"
    assert llm._llm is None


def test_switch_busy_during_generation(monkeypatch):
    monkeypatch.setattr(llm, "_BUSY_TIMEOUT", 0.1)
    release = threading.Event()
    entered = threading.Event()

    class Fake:
        def __init__(self, **kwargs):
            pass

        def set_cache(self, cache):
            pass

        def close(self):
            pass

        def create_chat_completion(self, messages, max_tokens, temperature):
            entered.set()
            release.wait(3)
            return {"choices": [{"message": {"content": "x"}}]}

    _llama(monkeypatch, Fake)
    thread = threading.Thread(target=lambda: llm.complete("s", "u"))
    thread.start()
    try:
        assert entered.wait(2)
        with pytest.raises(llm.ModelBusy):
            llm.switch_model(path="other.gguf")
    finally:
        release.set()
        thread.join(3)


def test_complete_during_loading_raises_modelbusy(monkeypatch):
    class Fake:
        def __init__(self, **kwargs):
            pass

        def set_cache(self, cache):
            pass

        def close(self):
            pass

    _llama(monkeypatch, Fake)
    llm.load()
    llm._set_state(llm.LOADING)
    with pytest.raises(llm.ModelBusy):
        llm.complete("s", "u")


def test_count_tokens_remote_does_not_build_model(monkeypatch):
    monkeypatch.setattr(llm.model_registry, "selected_backend", lambda: "remote")
    monkeypatch.setattr(llm, "_estimate_tokens", lambda text: 7)
    built = []
    monkeypatch.setattr(llm, "_build_model", lambda path: built.append(path))
    assert llm.count_tokens("любой текст") == 7
    assert built == []


def test_complete_remote_calls_llm_remote(monkeypatch):
    monkeypatch.setattr(llm.model_registry, "selected_backend", lambda: "remote")
    monkeypatch.setattr(
        llm, "_remote_settings", lambda: {"model": "Qwen", "max_tokens": 200, "temperature": 0.0}
    )
    captured = {}

    def fake_complete(settings, messages):
        captured["messages"] = messages
        return {
            "text": " Ответ ",
            "reasoning": None,
            "finish_reason": "stop",
            "tokens_in": 5,
            "tokens_out": 2,
        }

    monkeypatch.setattr(llm.llm_remote, "complete", fake_complete)
    sink = {}
    assert llm.complete("правила", "вопрос", usage_sink=sink) == "Ответ"
    assert sink == {"tokens_in": 5, "tokens_out": 2}
    assert captured["messages"][-1] == {"role": "user", "content": "вопрос"}


def test_complete_remote_empty_after_strip_raises(monkeypatch):
    monkeypatch.setattr(llm.model_registry, "selected_backend", lambda: "remote")
    monkeypatch.setattr(llm, "_remote_settings", lambda: {"model": "Qwen"})
    monkeypatch.setattr(
        llm.llm_remote,
        "complete",
        lambda s, m: {"text": "  ", "reasoning": None, "finish_reason": "stop"},
    )
    with pytest.raises(llm.ProviderError) as info:
        llm.complete("правила", "вопрос")
    assert "пустой ответ" in info.value.text


def test_switch_remote_saves_selection_once(monkeypatch):
    saved = []
    monkeypatch.setattr(
        llm.model_registry,
        "save_selected_model",
        lambda *a, **k: saved.append((a, k)),
    )
    monkeypatch.setattr(llm, "_llm", None)
    llm.switch_model(
        model_id="Qwen/Qwen2.5-72B-Instruct",
        backend="remote",
        provider_id="hyperbolic",
        base_url="https://api.hyperbolic.xyz/v1",
    )
    assert len(saved) == 1
    args, kwargs = saved[0]
    assert args == ("Qwen/Qwen2.5-72B-Instruct",)
    assert kwargs == {
        "backend": "remote",
        "provider_id": "hyperbolic",
        "base_url": "https://api.hyperbolic.xyz/v1",
    }


def test_load_remote_marks_ready(monkeypatch):
    monkeypatch.setattr(llm.model_registry, "selected_backend", lambda: "remote")
    monkeypatch.setattr(
        llm.model_registry, "selected_model_id", lambda: "Qwen/Qwen2.5-72B-Instruct"
    )
    monkeypatch.setattr(llm, "_llm", None)
    llm.load()
    assert llm.status()["state"] == llm.READY
    assert llm.status()["backend"] == "remote"


def test_switch_model_resolves_first_shard(monkeypatch):
    built = []

    class Fake:
        def __init__(self, **kwargs):
            built.append(kwargs["model_path"])

        def set_cache(self, cache):
            pass

        def close(self):
            pass

    _llama(monkeypatch, Fake)
    monkeypatch.setattr(
        llm.model_registry,
        "get_model",
        lambda model_id: {"files": ["a-00001-of-00002.gguf", "a-00002-of-00002.gguf"]},
    )
    monkeypatch.setattr(
        llm.model_registry,
        "primary_file",
        lambda card: Path("data/models/a-00001-of-00002.gguf"),
    )
    llm.load_model(model_id="m")
    assert built == [str(Path("data/models/a-00001-of-00002.gguf"))]
    assert llm.current_model_id() == "m"


def test_load_uses_startup_model_priority(monkeypatch):
    built = []

    class Fake:
        def __init__(self, **kwargs):
            built.append(kwargs["model_path"])

        def set_cache(self, cache):
            pass

    _llama(monkeypatch, Fake)  # env LLM_MODEL_PATH=model.gguf
    monkeypatch.setattr(llm.model_registry, "startup_model", lambda: ("selected.gguf", "qvikhr"))
    llm.load()
    assert built == ["selected.gguf"]
    assert llm.current_model_id() == "qvikhr"


def test_strip_thinking_removes_reasoning_artifacts():
    assert llm._strip_thinking("<think>разбор</think>Финальный ответ") == "Финальный ответ"
    assert llm._strip_thinking("<think>строка\nещё</think>Ответ") == "Ответ"
    assert llm._strip_thinking("рассуждения response Итоговый ответ") == "Итоговый ответ"
    assert llm._strip_thinking("</think>хвост<think>") == "хвост"
    assert llm._strip_thinking("Чистый ответ") == "Чистый ответ"


def test_load_model_persists_selection(monkeypatch):
    saved = []
    monkeypatch.setattr(llm, "_resolve_path", lambda path, model_id: ("fake.gguf", model_id))
    monkeypatch.setattr(llm, "_replace_model", lambda path, model_id: None)
    monkeypatch.setattr(
        llm.model_registry, "save_selected_model", lambda model_id: saved.append(model_id)
    )
    llm.load_model(model_id="qvikhr")
    assert saved == ["qvikhr"]
