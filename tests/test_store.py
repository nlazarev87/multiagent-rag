from collections import Counter

from docx import Document

import ingest
import settings
import store
from ingest import ingest_dir, split_chunks


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHROMA", tmp_path / "chroma")
    store.reset()


def test_identical_text_is_stored_for_each_document(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])
    text = "Договор: оплата в течение 10 дней."

    def chunk(name):
        return {"text": text, "document_name": name, "chunk_index": 0, "checksum": "same", "section": ""}

    store.upsert_chunks([chunk("draft.txt"), chunk("signed.txt")])
    store.upsert_chunks([chunk("copy.txt")])
    assert sorted(store.list_documents()) == ["copy.txt", "draft.txt", "signed.txt"]
    assert store.chunks_for_document("signed.txt")[0]["text"] == text
    assert store.collection().count() == 3


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


def test_delete_document_removes_only_that_file(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])
    store.upsert_chunks([
        {"text": "Цех имеет номер 4.", "document_name": "charter.txt", "chunk_index": 0, "checksum": "c", "section": "A"},
        {"text": "Насос синий.", "document_name": "pump.md", "chunk_index": 0, "checksum": "p", "section": ""},
    ])
    store.known("цех")
    assert store._index is not None
    store.delete_document("charter.txt")
    assert store._index is None
    assert set(store.list_documents()) == {"pump.md"}
    assert store.chunks_for_document("charter.txt") == []
    assert store.chunks_for_document("pump.md")[0]["text"] == "Насос синий."
    store.delete_document("missing.txt")
    assert store.chunks_for_document("pump.md")[0]["text"] == "Насос синий."
    assert all("номер 4" not in chunk["text"] for chunk in store.search_chunks("номер цеха"))
    assert any("синий" in chunk["text"] for chunk in store.search_chunks("насос"))


def test_search_keeps_routing_where(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.2, 0.3, 0.4, 0.5] for _ in texts])
    store.upsert_chunks([
        {
            "text": "Сушильная камера имеет площадь 25 квадратных метров.",
            "document_name": "plain.txt",
            "chunk_index": 0,
            "checksum": "p",
            "kind": "text",
            "section": "",
        },
        {
            "text": "Сушильная камера имеет площадь 40 квадратных метров.",
            "document_name": "listed.txt",
            "chunk_index": 0,
            "checksum": "l",
            "kind": "overview",
            "section": "",
        },
    ])
    monkeypatch.setattr(store, "route_where", lambda: {"kind": "overview"})
    found = store.search_chunks("площадь сушильной камеры")
    assert found
    assert {chunk["document_name"] for chunk in found} == {"listed.txt"}


def test_where_ignores_blank_filters(monkeypatch):
    monkeypatch.setattr(settings, "routing", lambda: {
        "where": {"kind": "", "collection": None, "section": [], "version": 0},
    })
    assert settings.where() == {"version": 0}


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


def test_scope_narrows_only_when_one_document_owns_the_number():
    both = {"vocabulary": {"a_1.2-99.txt": set(), "b_1.2-99.txt": set()}}
    assert store.scope(both, "Что указано в 1.2-99?") is None
    one = {"vocabulary": {"STD_1.2-99.txt": set(), "STD_1.3-99.txt": set()}}
    assert store.scope(one, "Что указано в 1.2-99?") == ["STD_1.2-99.txt"]
    alone = {"vocabulary": {"STD_1.2-99.txt": set()}}
    assert store.scope(alone, "Что указано в 1.2-99?") is None


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


def test_search_keeps_its_index_when_a_delete_clears_the_global(monkeypatch):
    text = "Рабочее давление равно 6 бар."
    meta = {
        "document_name": "pump.md",
        "chunk_index": 0,
        "section": "Характеристики",
        "kind": "text",
        "group": "",
        "head": "",
    }
    store._index = {
        "ids": ["id0"],
        "texts": [text],
        "metas": [meta],
        "groups": {},
        "position": {"id0": 0},
        "vocabulary": {"pump.md": set()},
        "counts": [],
        "lengths": [],
        "frequency": {},
        "size": {},
        "chunks": {},
    }

    class Col:
        def count(self):
            return 1

        def get(self, **kwargs):
            return {"ids": ["id0"], "documents": [text], "metadatas": [meta]}

        def delete(self, ids):
            self.ids = ids

        def query(self, **kwargs):
            return {"ids": [["id0"]], "distances": [[0.1]]}

    monkeypatch.setattr(store, "collection", lambda: Col())
    monkeypatch.setattr(store, "scope", lambda index, query: None)
    monkeypatch.setattr(store, "_lexical", lambda index, query, allowed: ["id0"])
    monkeypatch.setattr(store, "_focus", lambda query, allowed: query)

    def dense(col, query, allowed, total):
        # Upload and delete finish by dropping the global index. That overlaps
        # the slow vector query, and Chroma can also return an id the opened
        # index never saw.
        store.delete_document("pump.md")
        return ["id0", "gone"]

    monkeypatch.setattr(store, "_dense", dense)
    try:
        found = store.search_chunks("давление насоса")
    finally:
        store._index = None
    assert [chunk["text"] for chunk in found] == [text]
    assert found[0]["document_name"] == "pump.md"


def test_delete_during_query_embed_does_not_crash_search(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "CHROMA", tmp_path / "chroma")
    store.reset()
    vector = [0.1, 0.2, 0.3, 0.4]

    def embed(texts):
        # The vector step is the slow part of a question. A delete that lands
        # there used to drop the global index and abort the question.
        if any(str(text).startswith("query:") for text in texts):
            store.delete_document("pump.md")
            store.delete_document("charter.txt")
        return [vector for _ in texts]

    monkeypatch.setattr(store, "_embed", embed)
    store.upsert_chunks([
        {"text": "Насос синий.", "document_name": "pump.md", "chunk_index": 0, "checksum": "a", "section": ""},
        {"text": "Цех имеет номер 4.", "document_name": "charter.txt", "chunk_index": 0, "checksum": "b", "section": ""},
    ])
    try:
        found = store.search_chunks("насос")
        assert isinstance(found, list)
        assert store.search_chunks("насос") == []
        assert store.list_documents() == []
    finally:
        store.reset()


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

def _stored(text, name, index=0, checksum="same"):
    return {
        "text": text,
        "document_name": name,
        "chunk_index": index,
        "checksum": checksum,
        "section": "",
    }

def test_upsert_keeps_chunks_beyond_the_first_batch(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])
    chunks = [
        _stored(f"Фрагмент номер {index} про склад.", "long.txt", index)
        for index in range(64)
    ]
    chunks.append(_stored("Уникальный хвост партии лежит в последнем ящике.", "long.txt", 64))
    store.upsert_chunks(chunks)
    rows = store.chunks_for_document("long.txt")
    assert [row["chunk_index"] for row in rows] == list(range(65))
    assert rows[-1]["text"] == "Уникальный хвост партии лежит в последнем ящике."
    found = store.search_chunks("Где лежит уникальный хвост партии?")
    assert found
    assert found[0]["chunk_index"] == 64
    assert "последнем ящике" in found[0]["text"]

def test_search_stays_on_requested_documents(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])
    store.upsert_chunks([
        _stored("Смена длится 8 часов.", "charter.txt", checksum="charter"),
        _stored("Смена длится 12 часов.", "pump.md", checksum="pump"),
        _stored("Система АЛЬФА передаёт данные по протоколу HTTP.", "a.txt", checksum="a"),
        _stored("Система БЕТА передаёт данные по протоколу FTP.", "b.txt", checksum="b"),
    ])
    shift = store.search_chunks("Сколько длится смена?", document_names=["gone.txt", "charter.txt"])
    assert {chunk["document_name"] for chunk in shift} == {"charter.txt"}
    assert all("8 часов" in chunk["text"] for chunk in shift)
    named = store.search_chunks("По какому протоколу передаёт данные БЕТА?", document_names=["a.txt"])
    assert {chunk["document_name"] for chunk in named} == {"a.txt"}
    assert all("HTTP" in chunk["text"] for chunk in named)

def test_search_limits_follow_up_to_named_documents(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])

    def chunk(text, name, checksum):
        return {
            "text": text,
            "document_name": name,
            "chunk_index": 0,
            "checksum": checksum,
            "section": "",
        }

    store.upsert_chunks([
        chunk("Система АЛЬФА передаёт данные по протоколу HTTP.", "a.txt", "a"),
        chunk("Система БЕТА передаёт данные по протоколу FTP.", "b.txt", "b"),
    ])
    limited = store.search_chunks("По какому протоколу передаёт данные?", document_names=["a.txt", "missing.txt"])
    assert {chunk["document_name"] for chunk in limited} == {"a.txt"}
    unknown = store.search_chunks("По какому протоколу передаёт данные?", document_names=["missing.txt"])
    assert {chunk["document_name"] for chunk in unknown} == {"a.txt", "b.txt"}

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

def test_search_stays_inside_the_routed_collection(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])
    store.upsert_chunks([{
        "text": "Насос имеет обозначение Н-12.",
        "document_name": "pump.md",
        "chunk_index": 0,
        "checksum": "a",
        "section": "",
        "collection": "alpha",
    }])
    store.upsert_chunks([{
        "text": "Кран имеет обозначение К-9.",
        "document_name": "valve.md",
        "chunk_index": 0,
        "checksum": "b",
        "section": "",
        "collection": "beta",
    }])
    monkeypatch.setattr(settings, "routing", lambda: {"where": {}})
    assert store.route_where() == {}
    assert store._chroma_where(None) is None
    assert store._chroma_where(["pump.md"]) == {"document_name": {"$in": ["pump.md"]}}
    assert {chunk["document_name"] for chunk in store.search_chunks("обозначение")} == {"pump.md", "valve.md"}
    monkeypatch.setattr(
        settings,
        "routing",
        lambda: {"where": {"collection": "alpha", "tenant": "", "site": None, "tags": []}},
    )
    assert store.route_where() == {"collection": "alpha"}
    assert store._chroma_where(["pump.md"]) == {
        "$and": [{"collection": "alpha"}, {"document_name": {"$in": ["pump.md"]}}],
    }
    assert {chunk["document_name"] for chunk in store.search_chunks("обозначение")} == {"pump.md"}
    assert store.search_chunks("обозначение", document_names=["valve.md"]) == []

def test_scope_names_one_file_and_stays_open_on_a_tie():
    assert store.scope({"vocabulary": {"only.txt": {"насос"}}}, "Что умеет насос Н-12?") is None
    assert store.scope(
        {"vocabulary": {"a.txt": {"альфа"}, "b.txt": {"альфа"}}},
        "Как устроена система АЛЬФА?",
    ) is None
    assert store.scope(
        {"vocabulary": {"a.txt": {"альфа"}, "b.txt": {"бета"}}},
        "Как устроена система БЕТА?",
    ) == ["b.txt"]
    assert store.scope(
        {"vocabulary": {"a.txt": {"альфа"}, "b.txt": {"бета"}}},
        "Как устроена система ГАММА?",
    ) is None
    numbered = {"vocabulary": {"STD_1.2-99.txt": set(), "STD_1.3-99.txt": set()}}
    assert store.scope(numbered, "Что указано в STD 1.2-99?") == ["STD_1.2-99.txt"]

def test_focus_drops_the_document_name_when_words_remain():
    scoped = store._focus("Какое давление у системы БЕТА сейчас", ["b.txt"])
    assert scoped == "Какое давление у системы сейчас"
    assert store._focus("БЕТА?", ["b.txt"]) == "БЕТА?"
    assert store._focus("Какое давление у системы БЕТА", None) == "Какое давление у системы БЕТА"

def test_table_context_keeps_overview_and_near_rows_inside_the_budget(monkeypatch):
    monkeypatch.setattr(ingest, "count_tokens", lambda text: max(1, len((text or "").split())))
    small = {
        "texts": ["цель", "сосед", "далеко"],
        "metas": [
            {"head": "шапка", "kind": "table", "document_name": "t.docx", "group": "t1", "chunk_index": 0},
            {"head": "", "kind": "table", "document_name": "t.docx", "group": "t1", "chunk_index": 1},
            {"head": "", "kind": "table", "document_name": "t.docx", "group": "t1", "chunk_index": 2},
        ],
        "groups": {("t.docx", "t1"): [0, 1, 2]},
    }
    monkeypatch.setattr(store, "_context", lambda: 3)
    near = store._render(small, [0])
    assert "цель" in near and "сосед" in near and "шапка" in near
    assert "далеко" not in near
    wide = {
        "texts": ["цель", "сосед", "один два три четыре пять шесть"],
        "metas": [
            {"head": "шапка", "kind": "table", "document_name": "t.docx", "group": "t1", "chunk_index": 0},
            {"head": "", "kind": "table", "document_name": "t.docx", "group": "t1", "chunk_index": 1},
            {"head": "", "kind": "overview", "document_name": "t.docx", "group": "t1", "chunk_index": 2},
        ],
        "groups": {("t.docx", "t1"): [0, 1, 2]},
    }
    monkeypatch.setattr(store, "_context", lambda: 4)
    forced = store._render(wide, [0])
    assert "один два три четыре пять шесть" in forced
    assert "цель" in forced
    assert "сосед" not in forced

def test_contexts_collapse_one_table_into_a_single_slot(monkeypatch):
    monkeypatch.setattr(ingest, "count_tokens", lambda text: 1)
    monkeypatch.setattr(store, "_context", lambda: 100)
    index = {
        "ids": ["a0", "a1", "a2", "b0"],
        "texts": ["A0", "A1", "список значений", "B0"],
        "metas": [
            {"document_name": "a.docx", "group": "t1", "kind": "table", "chunk_index": 0, "section": "S", "head": ""},
            {"document_name": "a.docx", "group": "t1", "kind": "table", "chunk_index": 1, "section": "S", "head": ""},
            {"document_name": "a.docx", "group": "t1", "kind": "overview", "chunk_index": 2, "section": "S", "head": ""},
            {"document_name": "b.txt", "group": "", "kind": "text", "chunk_index": 0, "section": "", "head": ""},
        ],
        "groups": {("a.docx", "t1"): [0, 1, 2]},
        "position": {"a0": 0, "a1": 1, "a2": 2, "b0": 3},
    }
    found = store._contexts(index, ["a0", "a1", "a2", "b0"], 2)
    assert [item["document_name"] for item in found] == ["a.docx", "b.txt"]
    assert found[0]["kind"] == "overview"
    assert "A0" in found[0]["text"] and "A1" in found[0]["text"] and "список значений" in found[0]["text"]
    assert found[1]["text"] == "B0"

def test_fuse_ranks_a_shared_hit_above_a_single_list(monkeypatch):
    monkeypatch.setattr(store, "_rrf", lambda: 5)
    assert store._fuse(["b", "a"], ["a"]) == ["a", "b"]

def test_blank_route_values_are_not_filters(monkeypatch):
    monkeypatch.setattr(settings, "routing", lambda: {"where": {"collection": "", "kind": None, "tags": [], "keep": "alpha"}})
    assert settings.where() == {"keep": "alpha"}
    monkeypatch.setattr(store, "route_where", lambda: {})
    assert store._meta_ok({"collection": "beta"}) is True
    assert store._chroma_where(None) is None
    assert store._chroma_where(["a.txt"]) == {"document_name": {"$in": ["a.txt"]}}
    monkeypatch.setattr(store, "route_where", lambda: {"collection": "alpha"})
    assert store._meta_ok({"collection": "alpha"}) is True
    assert store._meta_ok({}) is False
    assert store._chroma_where(None) == {"collection": "alpha"}
    assert store._chroma_where(["a.txt"]) == {
        "$and": [{"collection": "alpha"}, {"document_name": {"$in": ["a.txt"]}}],
    }

def test_lexical_hides_another_collection(monkeypatch):
    monkeypatch.setattr(store, "route_where", lambda: {"collection": "alpha"})
    monkeypatch.setattr(store, "_candidates", lambda: 10)
    terms = store._terms("насос")
    count = Counter({term: 1 for term in terms})
    index = {
        "counts": [Counter(count), Counter(count)],
        "lengths": [sum(count.values()), sum(count.values())],
        "metas": [
            {"document_name": "a.txt", "collection": "alpha"},
            {"document_name": "b.txt", "collection": "beta"},
        ],
        "frequency": {"a.txt": Counter(count), "b.txt": Counter(count)},
        "size": Counter({"a.txt": sum(count.values()), "b.txt": sum(count.values())}),
        "chunks": Counter({"a.txt": 1, "b.txt": 1}),
        "ids": ["a", "b"],
    }
    assert store._lexical(index, "насос", None) == ["a"]
    assert store._lexical(index, "насос", ["a.txt", "b.txt"]) == ["a"]
    monkeypatch.setattr(store, "route_where", lambda: {})
    assert store._lexical(index, "насос", ["b.txt"]) == ["b"]
    assert store._lexical(index, "склад", ["a.txt"]) == []

def test_scope_keeps_search_open_on_a_tie_or_unknown_name():
    index = {"vocabulary": {"a.txt": {"альфа", "протокол"}, "b.txt": {"бета", "протокол"}}}
    assert store.scope(index, "Какой протокол у АЛЬФА?") == ["a.txt"]
    assert store.scope(index, "Какой протокол у АЛЬФА и БЕТА?") is None
    assert store.scope(index, "Какой протокол у ГАММА?") is None
    assert store.scope({"vocabulary": {"only.txt": {"альфа"}}}, "АЛЬФА") is None

def test_scope_matches_a_numbered_filename_without_a_longer_prefix():
    index = {
        "vocabulary": {
            "STD_1.2-99.txt": set(),
            "STD_1.20-99.txt": set(),
            "STD_1.3-99.txt": set(),
        }
    }
    assert store.scope(index, "пункт 1.2") == ["STD_1.2-99.txt"]
    assert store.scope(index, "Что указано в STD?") is None
    assert store.scope(index, "Что указано в 1.2 и 1.3?") == ["STD_1.2-99.txt", "STD_1.3-99.txt"]
    pair = {"vocabulary": {"STD_1.2-99.txt": set(), "STD_1.3-99.txt": set()}}
    assert store.scope(pair, "Что указано в 1.2 и 1.3?") is None

def test_explicit_document_names_override_the_query_scope(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "_embed", lambda texts: [[0.1, 0.2, 0.3, 0.4] for _ in texts])

    def chunk(text, name):
        return {"text": text, "document_name": name, "chunk_index": 0, "checksum": name, "section": ""}

    store.upsert_chunks([
        chunk("Система АЛЬФА передаёт данные по протоколу HTTP.", "a.txt"),
        chunk("Система БЕТА передаёт данные по протоколу FTP.", "b.txt"),
    ])
    forced = store.search_chunks("По какому протоколу передаёт данные БЕТА?", document_names=["a.txt"])
    assert forced
    assert {chunk["document_name"] for chunk in forced} == {"a.txt"}
    fallback = store.search_chunks("По какому протоколу передаёт данные БЕТА?", document_names=["gone.txt"])
    assert {chunk["document_name"] for chunk in fallback} == {"b.txt"}
