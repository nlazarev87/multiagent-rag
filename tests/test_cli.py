from cli import main
from ingest import split_chunks


def test_cli_ingest_and_ask(tmp_path, monkeypatch):
    (tmp_path / "charter.txt").write_text("Цех имеет номер 4.", encoding="utf-8")
    saved = []
    monkeypatch.setattr("cli.upsert_chunks", saved.extend)
    monkeypatch.setattr("ingest.count_tokens", lambda text: max(1, len(str(text or "").split())))
    seen = {}

    def record(query, dialog_id):
        seen["query"] = query
        seen["dialog_id"] = dialog_id
        return {"answer": "4", "status": "accepted", "document_names": ["charter.txt"]}

    monkeypatch.setattr("cli.run", record)
    main(["ingest", str(tmp_path)])
    assert saved[0]["document_name"] == "charter.txt"
    result = main(["ask", "Какой", "номер", "у", "цеха?"])
    assert result["status"] == "accepted"
    assert seen == {"query": "Какой номер у цеха?", "dialog_id": "cli"}
    listed = main(["сколько", "насосов", "в", "цехе"])
    assert listed["status"] == "accepted"
    assert seen["query"] == "сколько насосов в цехе"
    assert main([]) is None
    assert main(["ask"]) is None
    assert split_chunks("Цех имеет номер 4.", "charter.txt")[0]["text"].startswith("Цех")


def test_cli_asks_the_words_after_the_command(capsys, monkeypatch):
    seen = []
    monkeypatch.setattr("cli.run", lambda query, dialog_id: seen.append((query, dialog_id)) or {
        "answer": "4",
        "status": "подтверждён",
        "document_names": ["charter.txt"],
    })
    monkeypatch.setattr("cli.upsert_chunks", lambda *_args: (_ for _ in ()).throw(AssertionError("ingest")))
    result = main(["ask", "Какой", "номер?"])
    assert seen == [("Какой номер?", "cli")]
    assert result["document_names"] == ["charter.txt"]
    assert capsys.readouterr().out == "4 подтверждён charter.txt\n"
