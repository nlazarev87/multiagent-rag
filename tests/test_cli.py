from pathlib import Path

from cli import main
from ingest import split_chunks


def test_cli_ingest_and_ask(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ROOT", str(tmp_path / "root"))
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("CONFIG_DIR", str(repo / "config"))
    monkeypatch.setenv("PROMPTS_DIR", str(repo / "data" / "prompts"))
    import settings
    settings.reload()
    monkeypatch.setenv("CLI_PASSWORD", "password12")
    monkeypatch.delenv("RAG_TEST_USER", raising=False)
    import access
    import auth
    import kb
    auth.setup("admin", "password12")
    user = auth.user_by_login("admin")
    kb.ensure_legacy()
    access.backfill_legacy(user["id"])
    source = tmp_path / "files"
    source.mkdir()
    (source / "charter.txt").write_text("Цех имеет номер 4.", encoding="utf-8")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr("api.INBOX", inbox)
    saved = []
    monkeypatch.setattr("cli.upsert_chunks", saved.extend)
    monkeypatch.setattr("ingest.count_tokens", lambda text: max(1, len(str(text or "").split())))
    seen = {}

    def record(query, dialog_id, scope=None):
        seen["query"] = query
        seen["dialog_id"] = dialog_id
        return {"answer": "4", "status": "accepted", "document_names": ["charter.txt"]}

    monkeypatch.setattr("cli.run", record)
    main(["--user", "admin", "ingest", "--kb", kb.LEGACY_ID, str(source)])
    assert saved[0]["document_name"] == "charter.txt"
    result = main(["--user", "admin", "ask", "Какой", "номер", "у", "цеха?"])
    assert result["status"] == "accepted"
    assert seen == {"query": "Какой номер у цеха?", "dialog_id": "cli"}
    listed = main(["--user", "admin", "сколько", "насосов", "в", "цехе"])
    assert listed["status"] == "accepted"
    assert seen["query"] == "сколько насосов в цехе"
    assert main([]) is None
    assert main(["ask"]) is None
    assert split_chunks("Цех имеет номер 4.", "charter.txt")[0]["text"].startswith("Цех")
