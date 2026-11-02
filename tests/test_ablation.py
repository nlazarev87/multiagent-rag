"""Wave 0 #117: флаги эвристик.

При выключенном флаге поиск меняется. test_features_default_all_true не требует корпуса.
"""
from pathlib import Path

import pytest

import agents
from settings import runtime
from store import search_chunks

ROOT = Path(__file__).resolve().parent.parent
_HAS_CORPUS = (ROOT / "data" / "inbox").is_dir() and any((ROOT / "data" / "inbox").glob("*.docx"))


def test_features_default_all_true():
    feats = runtime().get("features", {})
    assert feats, "runtime.json must have 'features'"
    expected = {
        "inject_rare", "focus", "scope", "cover_latin", "prefer_name",
        "from_overview", "table_neighbors", "overview_rows",
    }
    missing = expected - set(feats.keys())
    assert not missing, f"runtime.json missing features: {missing}"
    assert all(feats[name] is True for name in expected)


def test_cover_latin_off_does_not_refuse(monkeypatch):
    """Выключенный cover_latin не превращает промах в отказ. Включённый — по-прежнему."""
    calls = {"cover": 0, "model": 0}

    def cover(query, chunks):
        calls["cover"] += 1
        return None

    def model(*_args, **_kwargs):
        calls["model"] += 1
        return "из модели"

    monkeypatch.setattr(agents, "_cover_latin", cover)
    monkeypatch.setattr(agents, "count_tokens", lambda text: len(text.split()))
    monkeypatch.setattr(agents, "complete", model)
    chunks = [{"text": "Насос работает.", "document_name": "a.txt", "chunk_index": 0, "section": ""}]
    off = {"cover_latin": False, "prefer_name": False, "from_overview": False}
    answer = agents.answer_agent("Где NPP?", "Где NPP?", chunks, [], features=off)
    assert calls["cover"] == 0
    assert calls["model"] == 1
    assert "из модели" in answer
    calls["model"] = 0
    on = dict(off, cover_latin=True)
    assert agents.answer_agent("Где NPP?", "Где NPP?", chunks, [], features=on) == agents.NO_ANSWER
    assert calls["model"] == 0


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_CORPUS, reason="no corpus in data/inbox")
def test_disable_inject_rare_returns_slots():
    query = "Сколько потоков"
    baseline = search_chunks(query, 4, debug=True)
    disabled = search_chunks(query, 4, debug=True, features={
        "inject_rare": False, "overview_rows": True, "table_neighbors": True,
        "scope": True, "focus": True,
    })
    assert isinstance(baseline["slots"], list)
    assert isinstance(disabled["slots"], list)


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_CORPUS, reason="no corpus in data/inbox")
def test_disable_overview_rows_filters_overview_kind():
    query = "Сколько потоков"
    result = search_chunks(query, 4, debug=True, features={
        "overview_rows": False, "inject_rare": True, "table_neighbors": True,
        "scope": True, "focus": True,
    })
    for slot in result["slots"]:
        assert "Разных значений в столбце" not in (slot.get("text") or ""), (
            f"overview text leaked into slot with overview_rows=False: {slot.get('id')}"
        )


@pytest.mark.slow
@pytest.mark.skipif(not _HAS_CORPUS, reason="no corpus in data/inbox")
def test_disable_scope_widens_search():
    query = "насосный агрегат на площадке"
    with_scope = search_chunks(query, 4, debug=True, features={
        "scope": True, "inject_rare": True, "overview_rows": True,
        "table_neighbors": True, "focus": True,
    })
    without_scope = search_chunks(query, 4, debug=True, features={
        "scope": False, "inject_rare": True, "overview_rows": True,
        "table_neighbors": True, "focus": True,
    })
    assert isinstance(with_scope["slots"], list)
    assert isinstance(without_scope["slots"], list)
