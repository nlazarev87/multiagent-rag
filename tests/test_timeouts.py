"""Wave 1 #119: предел времени и один повтор вызова модели."""

import time

import pytest

import llm


def test_llm_complete_passes_when_fast(monkeypatch):
    monkeypatch.setattr(llm, "_complete_sync", lambda *args, **kwargs: "быстрый ответ")
    assert llm.complete("x", "y", max_tokens=10, timeout_s=1.0) == "быстрый ответ"


def test_llm_complete_raises_on_timeout(monkeypatch):
    def slow(*args, **kwargs):
        time.sleep(5)
        return "late"

    monkeypatch.setattr(llm, "_complete_sync", slow)
    with pytest.raises(TimeoutError, match="llm timeout"):
        llm.complete("x", "y", max_tokens=10, timeout_s=0.2)


def test_llm_complete_retries_once(monkeypatch):
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        time.sleep(5)
        return "late"

    monkeypatch.setattr(llm, "_complete_sync", flaky)
    monkeypatch.setattr(llm, "runtime", lambda: {"timeouts": {"llm_ms": 200, "retries": 1}})
    with pytest.raises(TimeoutError, match="llm timeout"):
        llm.complete("x", "y", max_tokens=10)
    assert calls["n"] == 2


def test_runtime_json_has_timeouts():
    data = llm.runtime()
    assert "timeouts" in data
    limits = data["timeouts"]
    missing = {"node_ms", "llm_ms", "chroma_ms", "retries"} - set(limits)
    assert not missing, missing
    assert "graph_ms" not in limits
    assert isinstance(limits["llm_ms"], int)
    assert isinstance(limits["retries"], int)
