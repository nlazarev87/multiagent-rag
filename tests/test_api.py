import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api
from api import app

SOURCE = {"number": 1, "document_name": "pump.md", "section": ""}


@pytest.fixture(autouse=True)
def ui_store(tmp_path, monkeypatch):
    monkeypatch.setattr("workspace.PATH", tmp_path / "workspace.json")


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
    assert "data-document" in page.text and "data-index" in page.text


def test_ready(tmp_path, monkeypatch):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"x")
    monkeypatch.setenv("LLM_MODEL_PATH", str(model))
    api._state["done"] = True
    assert TestClient(app).get("/ready").status_code == 200


def test_preview_listed_document(monkeypatch):
    rows = [{"text": "абзац", "section": "Введение", "chunk_index": 0}]
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    monkeypatch.setattr("api.chunks_for_document", lambda name: rows if name == "note.txt" else [])
    response = TestClient(app).get("/documents/note.txt/preview")
    assert response.status_code == 200
    assert response.json() == {"document_name": "note.txt", "chunks": rows}


def test_preview_unknown_document(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    monkeypatch.setattr("api.chunks_for_document", lambda name: (_ for _ in ()).throw(AssertionError(name)))
    assert TestClient(app).get("/documents/missing.txt/preview").status_code == 404


def test_preview_stays_inside_listed_names(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr("api.INBOX", tmp_path)
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    monkeypatch.setattr("api.chunks_for_document", lambda name: called.append(name) or [])
    outside = tmp_path / "outside.txt"
    outside.write_text("чужой файл", encoding="utf-8")
    with pytest.raises(HTTPException) as error:
        api.documents_preview("../outside.txt")
    assert error.value.status_code == 404
    assert called == []
    assert outside.read_text(encoding="utf-8") == "чужой файл"


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


def test_ui_dialogs_and_ratings(tmp_path, monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    monkeypatch.setattr("api.run", lambda query, dialog_id: {
        "answer": "Цех имеет номер 4 [1].",
        "status": "подтверждён",
        "document_names": ["note.txt"],
        "sources": [{"number": 1, "document_name": "note.txt", "section": "", "chunk_index": 0}],
    })
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert created["title"] == "Новый диалог"
    assert created["turns"] == []
    listed = client.get("/ui").json()
    assert listed["dialogs"][0]["id"] == created["id"]
    assert {"document_name": "note.txt"} in listed["tree"]["children"]
    asked = client.post("/query", json={"query": "номер цеха", "dialog_id": created["id"]})
    assert asked.status_code == 200
    row = client.get("/ui/dialogs/" + created["id"]).json()
    assert row["title"] == "номер цеха"
    assert row["turns"][0]["answer"] == "Цех имеет номер 4 [1]."
    patched = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 4, "answer_correct": 5, "links": {"1": 3}, "documents": {"note.txt": 2}},
    )
    assert patched.status_code == 200
    assert patched.json()["ratings"]["answer_complete"] == 4
    assert patched.json()["ratings"]["links"]["1"] == 3
    leftover = client.delete("/ui/dialogs/" + created["id"]).json()
    assert leftover["dialogs"]
    assert leftover["dialogs"][0]["id"] != created["id"]


def test_ui_tree_drops_unknown_files(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    client = TestClient(app)
    response = client.put("/ui", json={
        "tree": {
            "id": "root",
            "name": "",
            "children": [
                {"id": "folder", "name": "Папка", "children": [{"document_name": "note.txt"}]},
                {"document_name": "missing.txt"},
            ],
        }
    })
    assert response.status_code == 200
    names = []
    for child in response.json()["tree"]["children"]:
        if "document_name" in child:
            names.append(child["document_name"])
        names.extend(item.get("document_name") for item in child.get("children") or [] if item.get("document_name"))
    assert "note.txt" in names
    assert "missing.txt" not in names
