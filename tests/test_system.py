from pathlib import Path

import pytest

import dialog
import store
from agents import CONFIRMED, MISSING
from coordinator import run
from ingest import ingest_dir

DOCS = Path(__file__).parent / "docs"
STEPS = [
    ("Какой номер у цеха?", "4", None, {CONFIRMED}, "charter.txt"),
    ("Как зовут мастера?", "Иванов", None, {CONFIRMED}, "charter.txt"),
    ("Сколько она длится?", "8", None, {CONFIRMED}, "charter.txt"),
    ("Какое давление у насоса?", "6 бар", "Иванов", {CONFIRMED}, "pump.md"),
    ("В каком году его выпустили?", "2019", "18", {CONFIRMED}, "pump.md"),
    ("Какая температура на складе?", "18", "6 бар", {CONFIRMED}, "charter.txt"),
    ("Какой цвет у насоса?", None, "синий", {CONFIRMED, MISSING}, None),
    ("Какой номер у цеха?", "4", None, {CONFIRMED}, "charter.txt"),
]


@pytest.mark.slow
def test_dialog_switches_meaning(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHROMA", tmp_path / "chroma")
    store.reset()
    dialog.reset()
    store.upsert_chunks(ingest_dir(DOCS))
    store.calls = 0
    for query, fact, banned, statuses, name in STEPS:
        result = run(query, "shop-pump")
        assert result["status"] in statuses, (query, result)
        if fact:
            assert fact.lower() in result["answer"].lower(), (query, result)
        if banned:
            assert banned.lower() not in result["answer"].lower(), (query, result)
        if name:
            assert name in result["document_names"], (query, result)
    assert store.calls == 8
