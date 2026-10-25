from fastapi.testclient import TestClient

import api
from api import app

SOURCE = {"number": 1, "document_name": "pump.md", "section": ""}


def test_api_routes(tmp_path, monkeypatch):
    (tmp_path / "pump.md").write_text("Рабочее давление равно 6 бар.", encoding="utf-8")
    saved = []
    monkeypatch.setattr("api.INBOX", tmp_path)
    monkeypatch.setattr("api.upsert_chunks", saved.extend)
    monkeypatch.setattr("api.run", lambda query, dialog_id: {
        "answer": "Давление равно 6 бар [1].", "status": "подтверждён", "document_names": ["pump.md"], "sources": [SOURCE]
    })
    client = TestClient(app)
    assert client.post("/documents", json={"directory": str(tmp_path)}).status_code == 200
    assert saved[0]["document_name"] == "pump.md"
    assert client.post("/documents", json={"directory": str(tmp_path.parent)}).status_code == 400
    response = client.post("/query", json={"query": "давление", "dialog_id": "d"})
    assert response.json()["answer"] == "Давление равно 6 бар [1]."
    assert response.json()["sources"] == [SOURCE]


def test_upload_lists_document(tmp_path, monkeypatch):
    monkeypatch.setattr("api.INBOX", tmp_path)
    saved = []

    def remember(chunks):
        saved.extend(chunk["document_name"] for chunk in chunks)

    monkeypatch.setattr("api.upsert_chunks", remember)
    monkeypatch.setattr("api.list_documents", lambda: saved)
    client = TestClient(app)
    response = client.post("/upload", files=[("files", ("note.txt", "Цех имеет номер 4.", "text/plain"))])
    assert response.status_code == 200
    assert client.get("/documents").json()["documents"] == ["note.txt"]
    page = client.get("/")
    assert page.status_code == 200
    assert "insertAdjacentHTML" not in page.text and "innerHTML" not in page.text


def test_ready(tmp_path, monkeypatch):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"x")
    monkeypatch.setenv("LLM_MODEL_PATH", str(model))
    api._state["done"] = True
    assert TestClient(app).get("/ready").status_code == 200


def test_delete_document_stays_inside_inbox(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    removed = []
    monkeypatch.setattr("api.INBOX", inbox)
    monkeypatch.setattr("api.delete_document", removed.append)
    monkeypatch.setattr("api.list_documents", lambda: [])
    (inbox / "note.txt").write_text("текст", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("чужой файл", encoding="utf-8")
    assert TestClient(app).delete("/documents/note.txt").status_code == 200
    api.documents_delete("../outside.txt")
    assert removed == ["note.txt", "outside.txt"]
    assert not (inbox / "note.txt").exists()
    assert outside.exists()
