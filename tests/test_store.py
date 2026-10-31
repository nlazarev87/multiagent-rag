from collections import Counter

from docx import Document

import ingest
import settings
import store
from ingest import ingest_dir, split_chunks


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHROMA", tmp_path / "chroma")
    store.reset()


def test_upsert_skips_same_checksum(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    chunks = split_chunks("Цех имеет номер 4. Мастер цеха Иванов.", "charter.txt")
    store.upsert_chunks(chunks)
    store.upsert_chunks(chunks)
    assert store.collection().count() == 1


def test_reingest_applies_overlap_change(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])
    monkeypatch.setattr(ingest, "count_tokens", lambda text: max(1, len((text or "").split())))
    ingest._word_tokens.cache_clear()
    text = "\n".join(
        f"строка {number} " + " ".join(f"слово{number}_{index}" for index in range(8))
        for number in range(40)
    )
    state = {"tokens": 250, "overlap": 40, "intro": 120}
    monkeypatch.setattr(ingest, "runtime", lambda: state)
    first = split_chunks(text, "doc.txt")
    store.upsert_chunks(first)
    state["overlap"] = 0
    second = split_chunks(text, "doc.txt")
    assert len(first) == len(second) > 1
    assert [chunk["text"] for chunk in first] != [chunk["text"] for chunk in second]
    store.upsert_chunks(second)
    _, texts, metas = store._rows(store.collection())
    stored = [body for _, body in sorted(zip(metas, texts), key=lambda item: item[0]["chunk_index"])]
    assert stored == [chunk["text"] for chunk in second]
    ingest._word_tokens.cache_clear()


def test_upsert_replaces_changed_document(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    store.upsert_chunks(split_chunks("Насос синий.", "pump.md"))
    store.upsert_chunks(split_chunks("Насос зелёный.", "pump.md"))
    assert store._rows(store.collection())[1] == ["Насос зелёный."]


def test_chunks_for_document_orders_by_index(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])
    store.upsert_chunks([
        {"text": "второй", "document_name": "note.txt", "chunk_index": 1, "checksum": "a", "section": "B"},
        {"text": "первый", "document_name": "note.txt", "chunk_index": 0, "checksum": "a", "section": "A"},
        {"text": "чужой", "document_name": "other.txt", "chunk_index": 0, "checksum": "b", "section": ""},
    ])
    rows = store.chunks_for_document("note.txt")
    assert [row["text"] for row in rows] == ["первый", "второй"]
    assert [row["section"] for row in rows] == ["A", "B"]
    assert [row["chunk_index"] for row in rows] == [0, 1]


def test_empty_search_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHROMA", tmp_path / "empty")
    store.reset()
    assert store.search_chunks("номер цеха") == []


def test_search_finds_document(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    store.upsert_chunks(split_chunks("Насос имеет обозначение Н-12. Рабочее давление равно 6 бар.", "pump.md"))
    found = store.search_chunks("давление насоса")
    assert found[0]["document_name"] == "pump.md"
    assert "6 бар" in found[0]["text"]


def test_search_keeps_to_document_named_in_question(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    store.upsert_chunks(split_chunks("Система АЛЬФА передаёт данные по протоколу HTTP.", "a.txt"))
    store.upsert_chunks(split_chunks("Система БЕТА передаёт данные по протоколу FTP.", "b.txt"))
    found = store.search_chunks("По какому протоколу передаёт данные БЕТА?")
    assert {chunk["document_name"] for chunk in found} == {"b.txt"}


def test_search_keeps_to_numbered_filename_in_question(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    same = "В разделе Назначение программы должны быть указаны сведения о назначении программы."
    store.upsert_chunks(split_chunks(same, "STD_1.2-99.txt"))
    store.upsert_chunks(split_chunks(same, "STD_1.3-99.txt"))
    found = store.search_chunks("Что указывают в разделе Назначение программы по STD 1.2-99?")
    assert {chunk["document_name"] for chunk in found} == {"STD_1.2-99.txt"}


def test_search_finds_exact_code(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    lines = [f"Поток X_{number}.1 передаёт заявки номер {number}." for number in range(1, 9)]
    lines.append("Поток X_9.2 передаёт годовые отчёты.")
    store.upsert_chunks(split_chunks("\n".join(lines * 20), "flows.txt"))
    found = store.search_chunks("Что передаёт поток X_9.2?")
    assert any("X_9.2" in chunk["text"] for chunk in found)


def _index(docs):
    names = list(docs)
    return {
        "vocabulary": docs,
        "ids": names,
        "texts": ["" for _ in names],
        "metas": [{"document_name": name, "chunk_index": 0, "section": ""} for name in names],
        "counts": [Counter() for _ in names],
        "lengths": [1 for _ in names],
        "frequency": {name: Counter() for name in names},
        "size": {name: 1 for name in names},
        "chunks": {name: 1 for name in names},
        "groups": {},
        "position": {name: number for number, name in enumerate(names)},
    }


def test_scope_stays_open_without_a_unique_document():
    single = _index({"only.txt": {"цех"}})
    assert store.scope(single, "Что сказано в ONLY про цех?") is None
    pair = _index({"ALFA.txt": set(), "BETA.txt": set()})
    assert store.scope(pair, "Чем отличаются ALFA и BETA?") is None
    unknown = _index({"a.txt": {"альфа"}, "b.txt": {"бета"}})
    assert store.scope(unknown, "Как работает ZZ-9?") is None


def test_scope_picks_the_file_named_by_a_number():
    index = _index({"STD_1.2-99.txt": set(), "STD_1.3-99.txt": set()})
    assert store.scope(index, "Что указано в STD 1.2-99?") == ["STD_1.2-99.txt"]


def test_focus_drops_the_filename_when_words_remain():
    query = "Что указывают в разделе Назначение программы по STD 1.2-99?"
    focused = store._focus(query, ["STD_1.2-99.txt"])
    assert "STD" not in focused.split()
    assert "1.2-99" not in focused
    assert "Назначение" in focused
    assert store._focus("Что STD?", ["STD.txt"]) == "Что STD?"
    assert store._focus(query, None) == query


def test_where_ignores_blank_filters(monkeypatch):
    monkeypatch.setattr(settings, "routing", lambda: {
        "where": {"collection": "", "kind": None, "tags": [], "lang": "ru"},
    })
    assert settings.where() == {"lang": "ru"}


def test_metadata_filter_hides_another_collection(monkeypatch):
    state = {"where": {"collection": "library"}}
    monkeypatch.setattr(store, "route_where", lambda: state["where"])
    assert store._meta_ok({"collection": "library"})
    assert not store._meta_ok({"collection": "other"})
    assert not store._meta_ok({"document_name": "c.txt"})
    assert store._chroma_where(["a.txt"]) == {
        "$and": [{"collection": "library"}, {"document_name": {"$in": ["a.txt"]}}],
    }
    assert store._chroma_where([]) == {"collection": "library"}
    terms = store._terms("насос")
    count = Counter(terms)
    index = {
        "counts": [Counter(count), Counter(count)],
        "lengths": [sum(count.values()), sum(count.values())],
        "frequency": {"a.txt": Counter(count), "b.txt": Counter(count)},
        "size": {"a.txt": sum(count.values()), "b.txt": sum(count.values())},
        "chunks": {"a.txt": 1, "b.txt": 1},
        "metas": [
            {"document_name": "a.txt", "collection": "library"},
            {"document_name": "b.txt", "collection": "other"},
        ],
        "ids": ["a", "b"],
    }
    assert store._lexical(index, "насос", None) == ["a"]
    state["where"] = {}
    assert store._meta_ok({"document_name": "c.txt"})
    assert store._chroma_where(None) is None
    assert store._chroma_where(["a.txt"]) == {"document_name": {"$in": ["a.txt"]}}
    assert store._lexical(index, "насос", None) == ["a", "b"]


class _Count:
    def count(self):
        return 2


def test_document_argument_overrides_a_matching_name(monkeypatch):
    index = _index({"a.txt": {"http"}, "b.txt": {"ftp"}})
    monkeypatch.setattr(store, "_index", index)
    monkeypatch.setattr(store, "collection", lambda: _Count())
    seen = []

    def dense(_col, query, allowed, _total):
        seen.append((query, list(allowed) if allowed is not None else None))
        return []

    monkeypatch.setattr(store, "_dense", dense)
    store.search_chunks("Какой порт у HTTP?", document_names=["b.txt"])
    store.search_chunks("Какой порт у HTTP?", document_names=["gone.txt"])
    store.search_chunks("Какой порт у HTTP?")
    assert seen[0][1] == ["b.txt"]
    assert seen[1][1] == ["a.txt"]
    assert seen[2][1] == ["a.txt"]
    assert "HTTP" not in seen[0][0].split()


def test_table_row_comes_with_its_table(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    folder = tmp_path / "docs"
    folder.mkdir()
    document = Document()
    document.add_heading("Склад", level=1)
    document.add_paragraph("Таблица 1 – Помещения склада")
    rows = [("Помещение", "Площадь"), ("Холодильная камера", "40 м²"), ("Сушильная", "25 м²"), ("Архив", "12 м²")]
    table = document.add_table(rows=len(rows), cols=2)
    for row, (key, value) in zip(table.rows, rows):
        row.cells[0].text, row.cells[1].text = key, value
    document.save(folder / "store.docx")
    store.upsert_chunks(ingest_dir(folder))
    found = store.search_chunks("Какая площадь у холодильной камеры?")
    text = next(chunk["text"] for chunk in found if "Холодильная камера" in chunk["text"])
    assert "Таблица 1 – Помещения склада" in text
    assert "Холодильная камера: 40 м²" in text
    assert "Архив: 12 м²" in text
    assert text.count("Таблица 1") == 1
