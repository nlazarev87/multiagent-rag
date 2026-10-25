from cli import main
from ingest import split_chunks


def test_cli_ingest_and_ask(tmp_path, monkeypatch):
    (tmp_path / "charter.txt").write_text("Цех имеет номер 4.", encoding="utf-8")
    saved = []
    monkeypatch.setattr("cli.upsert_chunks", saved.extend)
    monkeypatch.setattr("cli.run", lambda query, dialog_id: {
        "answer": "4", "status": "accepted", "document_names": ["charter.txt"]
    })
    main(["ingest", str(tmp_path)])
    assert saved[0]["document_name"] == "charter.txt"
    result = main(["ask", "Какой", "номер", "у", "цеха?"])
    assert result["status"] == "accepted"
    assert split_chunks("Цех имеет номер 4.", "charter.txt")[0]["text"].startswith("Цех")
