from docx import Document

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


def test_upsert_replaces_changed_document(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    store.upsert_chunks(split_chunks("Насос синий.", "pump.md"))
    store.upsert_chunks(split_chunks("Насос зелёный.", "pump.md"))
    assert store._rows(store.collection())[1] == ["Насос зелёный."]


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


def test_search_finds_exact_code(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    lines = [f"Поток X_{number}.1 передаёт заявки номер {number}." for number in range(1, 9)]
    lines.append("Поток X_9.2 передаёт годовые отчёты.")
    store.upsert_chunks(split_chunks("\n".join(lines * 20), "flows.txt"))
    found = store.search_chunks("Что передаёт поток X_9.2?")
    assert any("X_9.2" in chunk["text"] for chunk in found)


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
