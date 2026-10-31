from pathlib import Path

import pytest
from docx import Document
from docx.enum.style import WD_STYLE_TYPE

from ingest import TOKENS, VERSION, count_tokens, ingest_dir, load_text, split_chunks


def _toc_style(document):
    try:
        return document.styles["toc 1"]
    except KeyError:
        return document.styles.add_style("toc 1", WD_STYLE_TYPE.PARAGRAPH)


def test_txt_and_md(tmp_path):
    (tmp_path / "a.txt").write_text("Цех имеет номер 4.", encoding="utf-8")
    (tmp_path / "b.md").write_text("# Насос\nНасос Н-12.", encoding="utf-8")
    chunks = {chunk["document_name"]: chunk for chunk in ingest_dir(tmp_path)}
    assert set(chunks) == {"a.txt", "b.md"}
    assert chunks["b.md"]["section"] == "Насос"
    assert chunks["b.md"]["text"] == "Насос\nНасос Н-12."


def test_docx_keeps_order_sections_and_skips_toc(tmp_path):
    path = tmp_path / "c.docx"
    document = Document()
    document.add_paragraph("Склад 7", style=_toc_style(document))
    document.add_heading("Склад", level=1)
    document.add_paragraph("Температура склада равна 18 градусам.")
    document.add_paragraph("Таблица 1 – Состав склада")
    table = document.add_table(rows=3, cols=2)
    for row, (key, value) in zip(table.rows, [("Показатель", "Значение"), ("Площадь", "120 м²"), ("Этаж", "2")]):
        row.cells[0].text, row.cells[1].text = key, value
    document.add_paragraph("Склад закрыт по воскресеньям.")
    document.save(path)
    chunks = ingest_dir(tmp_path)
    texts = [chunk["text"] for chunk in chunks]
    assert not any("Склад 7" in text for text in texts)
    rows = [chunk for chunk in chunks if chunk["kind"] == "table"]
    assert [chunk["section"] for chunk in rows] == ["Склад", "Склад"]
    assert all("Таблица 1 – Состав склада" in chunk["text"] for chunk in rows)
    assert "Площадь: 120 м²" in rows[0]["text"]
    order = [text for text in texts if "18 градусам" in text or "Площадь" in text or "воскресеньям" in text]
    assert "18 градусам" in order[0] and "воскресеньям" in order[-1]
    intro = next(chunk for chunk in chunks if chunk["kind"] == "intro")
    assert "18 градусам" in intro["text"] and intro["group"] == rows[0]["group"]
    assert not any(chunk["kind"] == "overview" for chunk in chunks)
    assert "18" in load_text(path)


def test_overview_list_keeps_every_value(monkeypatch):
    monkeypatch.setattr("ingest.count_tokens", lambda text: max(1, len(text.split())))
    from ingest import _word_tokens, chunks_from_blocks

    _word_tokens.cache_clear()
    values = [f"Наименование характеристики номер {number} очень длинное" for number in range(1, 41)]
    blocks = [{
        "kind": "table",
        "caption": "Таблица 1 – Перечень",
        "labels": ["Статус", "Описание"],
        "width": 2,
        "rows": [[("Статус", "Да"), ("Описание", value)] for value in values],
    }]
    chunks = chunks_from_blocks(blocks, "list.txt")
    overview = next(chunk["text"] for chunk in chunks if chunk["kind"] == "overview")
    assert "Разных значений в столбце «Описание»: 40." in overview
    assert all(value in overview for value in values)


def test_large_table_gets_overview(tmp_path):
    document = Document()
    table = document.add_table(rows=41, cols=3)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text, table.rows[0].cells[2].text = "Код", "Описание", "Статус"
    for number, row in enumerate(table.rows[1:], 1):
        row.cells[0].text = f"K_{number}"
        row.cells[1].text = f"Описание позиции номер {number} в длинном перечне склада"
        row.cells[2].text = "Да"
    document.save(tmp_path / "big.docx")
    chunks = ingest_dir(tmp_path)
    overview = next(chunk for chunk in chunks if chunk["kind"] == "overview")
    assert "Разных значений в столбце «Код»: 40" in overview["text"]
    assert len({chunk["group"] for chunk in chunks if chunk["kind"] in ("overview", "table")}) == 1


def test_merged_cells_are_not_repeated(tmp_path):
    document = Document()
    table = document.add_table(rows=2, cols=3)
    table.rows[0].cells[0].text = "ИД"
    table.rows[0].cells[1].merge(table.rows[0].cells[2]).text = "Описание"
    table.rows[1].cells[0].text = "A_1"
    table.rows[1].cells[1].text = "Запрос"
    table.rows[1].cells[2].text = "Передача данных"
    document.save(tmp_path / "m.docx")
    row = next(chunk["text"] for chunk in ingest_dir(tmp_path) if chunk["kind"] == "table")
    assert row.count("Описание") == 1
    assert "ИД: A_1; Описание: Запрос; Передача данных" in row


def test_chunks_fit_tokens_and_overlap():
    text = " ".join(f"слово{i}" for i in range(900))
    chunks = split_chunks(text, "long.txt")
    assert len(chunks) > 1
    assert all(count_tokens(chunk["text"]) <= TOKENS for chunk in chunks)
    assert len({chunk["checksum"] for chunk in chunks}) == 1
    assert all(chunk["version"] == VERSION for chunk in chunks)
    first, second = chunks[0]["text"].split(), chunks[1]["text"].split()
    assert first[-1] in second[:40]


def test_long_line_splits_after_a_sentence(monkeypatch):
    monkeypatch.setattr("ingest.count_tokens", lambda text: max(1, len(str(text).split())))
    from ingest import _cut, _word_tokens

    _word_tokens.cache_clear()
    lead = " ".join(f"слово{number}" for number in range(50)) + "."
    mid = " ".join(f"хвост{number}" for number in range(40))
    tail = "В разделе Назначение должны быть указаны сведения о назначении программы."
    pieces = _cut((lead + " " + mid + " " + tail).split(), 80)
    assert pieces[0].endswith(".")
    assert "Назначение" not in pieces[0]
    assert any("Назначение" in piece for piece in pieces[1:])
    _word_tokens.cache_clear()


def test_docx_joins_hyphen_line_break(tmp_path):
    document = Document()
    document.add_paragraph("Требования к содержанию доку-")
    document.add_paragraph("мента приведены в приложении.")
    document.save(tmp_path / "hyphen.docx")
    text = " ".join(chunk["text"] for chunk in ingest_dir(tmp_path))
    assert "документа" in text
    assert "доку-" not in text


def test_paragraph_with_section_number_is_kept():
    chunks = split_chunks("Согласно разделу 3.2 насос имеет давление 6 бар.", "pump.txt")
    assert "3.2" in chunks[0]["text"]


def test_doc_via_libreoffice(tmp_path):
    soffice = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
    if not soffice.exists():
        pytest.skip("LibreOffice не установлен")
    source = tmp_path / "d.docx"
    document = Document()
    document.add_paragraph("Год выпуска равен 2019.")
    document.save(source)
    import subprocess
    subprocess.run([str(soffice), "--headless", "--convert-to", "doc", "--outdir", str(tmp_path), str(source)], check=True)
    source.unlink()
    assert "2019" in load_text(tmp_path / "d.doc")
    assert sorted(path.name for path in tmp_path.iterdir()) == ["d.doc"]


def test_numbered_line_becomes_section(tmp_path):
    path = tmp_path / "n.docx"
    document = Document()
    document.add_paragraph("3 Перечень испытаний")
    document.add_paragraph("Опытная эксплуатация проверяет работу.")
    document.add_paragraph("2.1. В разделе Введение указывают наименование программы и объекта, в котором используют программу.")
    document.save(path)
    chunks = ingest_dir(tmp_path)
    assert chunks[0]["section"] == "3 Перечень испытаний"
    assert "Опытная эксплуатация" in chunks[0]["text"]
    assert all(chunk["section"] != "2.1. В разделе Введение указывают наименование программы и объекта, в котором используют программу." for chunk in chunks)
