import asyncio
import tempfile
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import api
import dialog
import workspace
from api import app
import time

SOURCE = {"number": 1, "document_name": "pump.md", "section": ""}


def _answer_row():
    return {"answer": "ответ", "sources": [], "document_names": ["note.txt"]}


@pytest.fixture(autouse=True)
def ui_store(tmp_path, monkeypatch):
    monkeypatch.setattr("workspace.PATH", tmp_path / "workspace.json")
    monkeypatch.setenv("APP_ROOT", tempfile.mkdtemp(prefix="rag-auth-"))
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("CONFIG_DIR", str(repo / "config"))
    monkeypatch.setenv("PROMPTS_DIR", str(repo / "data" / "prompts"))
    import settings
    settings.reload()
    import access
    import auth
    import kb
    auth.ensure()
    if auth.count_users() == 0:
        auth.setup("admin", "password12")
    user = auth.user_by_login("admin")
    kb.ensure_legacy()
    access.backfill_legacy(user["id"])
    monkeypatch.setenv("RAG_TEST_USER", user["id"])


def _doc_names(payload):
    rows = payload.get("documents", payload) if isinstance(payload, dict) else payload
    return [row["name"] if isinstance(row, dict) else row for row in rows]


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
    stored = workspace.load()["dialogs"]
    assert stored[0]["id"] == "d"
    assert stored[0]["turns"][0]["query"] == "давление"


def test_upload_indexes_other_files_when_one_is_unreadable(tmp_path, monkeypatch):
    monkeypatch.setattr("api.INBOX", tmp_path)
    monkeypatch.setattr("ingest.count_tokens", lambda text: max(1, len(str(text).split())))
    from ingest import _word_tokens

    _word_tokens.cache_clear()
    (tmp_path / "bad.txt").write_bytes(b"\xff")
    saved = []
    monkeypatch.setattr("api.upsert_chunks", saved.extend)
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("note.txt", "Цех имеет номер 4.", "text/plain"))],
    )
    assert response.status_code == 200
    assert {chunk["document_name"] for chunk in saved} == {"note.txt"}
    _word_tokens.cache_clear()


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
    assert _doc_names(client.get("/documents").json()) == ["note.txt"]
    page = client.get("/")
    assert page.status_code == 200
    assert "insertAdjacentHTML" not in page.text and "innerHTML" not in page.text
    assert "data-document" in page.text and "data-index" in page.text


def _token_count(monkeypatch):
    monkeypatch.setattr("ingest.count_tokens", lambda text: max(1, len(str(text).split())))
    from ingest import _word_tokens

    _word_tokens.cache_clear()
    return _word_tokens


def test_upload_replaces_readable_file(tmp_path, monkeypatch):
    monkeypatch.setattr("api.INBOX", tmp_path)
    cache = _token_count(monkeypatch)
    (tmp_path / "note.txt").write_text("старое значение", encoding="utf-8")
    saved = []
    monkeypatch.setattr("api.upsert_chunks", lambda chunks: saved.extend(chunks))
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("note.txt", "новое значение 8".encode(), "text/plain"))],
    )
    assert response.status_code == 200
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "новое значение 8"
    assert any(chunk["document_name"] == "note.txt" and "новое значение 8" in chunk["text"] for chunk in saved)
    cache.cache_clear()


def test_upload_keeps_previous_file_when_replacement_cannot_be_read(tmp_path, monkeypatch):
    monkeypatch.setattr("api.INBOX", tmp_path)
    original = "Давление равно 6 бар."
    (tmp_path / "note.txt").write_text(original, encoding="utf-8")
    (tmp_path / "other.txt").write_text("Цех имеет номер 4.", encoding="utf-8")
    called = []
    monkeypatch.setattr("api.upsert_chunks", called.append)
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("note.txt", b"\xff\xfe not text", "text/plain"))],
    )
    assert response.status_code == 400
    assert "note.txt" in response.json()["detail"]
    assert "сохран" in response.json()["detail"]
    assert called == []
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == original
    assert (tmp_path / "other.txt").read_text(encoding="utf-8") == "Цех имеет номер 4."


def test_upload_keeps_previous_file_when_replacement_has_no_text(tmp_path, monkeypatch):
    monkeypatch.setattr("api.INBOX", tmp_path)
    original = "Давление равно 6 бар."
    (tmp_path / "note.txt").write_text(original, encoding="utf-8")
    called = []
    monkeypatch.setattr("api.upsert_chunks", called.append)
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("note.txt", b" \n\n\t", "text/plain"))],
    )
    assert response.status_code == 400
    assert "нет текста" in response.json()["detail"]
    assert called == []
    assert (tmp_path / "note.txt").read_bytes() == original.encode()


def test_upload_keeps_previous_docx_when_replacement_is_corrupt(tmp_path, monkeypatch):
    monkeypatch.setattr("api.INBOX", tmp_path)
    original = b"previous-document-bytes"
    (tmp_path / "note.docx").write_bytes(original)
    called = []
    monkeypatch.setattr("api.upsert_chunks", called.append)
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("note.docx", b"not a docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
    )
    assert response.status_code == 400
    assert "note.docx" in response.json()["detail"]
    assert called == []
    assert (tmp_path / "note.docx").read_bytes() == original


def test_upload_drops_an_empty_new_file(tmp_path, monkeypatch):
    monkeypatch.setattr("api.INBOX", tmp_path)
    called = []
    monkeypatch.setattr("api.upsert_chunks", called.append)
    response = TestClient(app).post("/upload", files=[("files", ("empty.txt", b"\n", "text/plain"))])
    assert response.status_code == 400
    assert called == []
    assert not (tmp_path / "empty.txt").exists()


def test_upload_rolls_back_the_batch_when_a_later_file_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("api.INBOX", tmp_path)
    cache = _token_count(monkeypatch)
    (tmp_path / "note.txt").write_text("старое значение", encoding="utf-8")
    called = []
    monkeypatch.setattr("api.upsert_chunks", called.append)
    response = TestClient(app).post(
        "/upload",
        files=[
            ("files", ("note.txt", "новое значение 8".encode(), "text/plain")),
            ("files", ("other.txt", b"\xff", "text/plain")),
        ],
    )
    assert response.status_code == 400
    assert called == []
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "старое значение"
    assert not (tmp_path / "other.txt").exists()
    cache.cache_clear()


def test_upload_does_not_follow_a_symlink(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("секрет", encoding="utf-8")
    try:
        (inbox / "note.txt").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available")
    monkeypatch.setattr("api.INBOX", inbox)
    called = []
    monkeypatch.setattr("api.upsert_chunks", called.append)
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("note.txt", "новое".encode(), "text/plain"))],
    )
    assert response.status_code == 400
    assert called == []
    assert outside.read_text(encoding="utf-8") == "секрет"
    assert (inbox / "note.txt").is_symlink()


def test_upload_rejects_a_parent_directory_name(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr("api.INBOX", inbox)
    response = TestClient(app).post("/upload", files=[("files", ("..", b"x", "text/plain"))])
    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == [inbox]
    assert list(inbox.iterdir()) == []


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
    response = TestClient(app).get("/kb/00000000-0000-4000-8000-000000000001/documents/note.txt/preview")
    assert response.status_code == 200
    assert response.json() == {"document_name": "note.txt", "chunks": rows}


def test_preview_unknown_document(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    monkeypatch.setattr("api.chunks_for_document", lambda name: (_ for _ in ()).throw(AssertionError(name)))
    assert TestClient(app).get("/kb/00000000-0000-4000-8000-000000000001/documents/missing.txt/preview").status_code == 404


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
    assert TestClient(app).delete("/kb/00000000-0000-4000-8000-000000000001/documents/note.txt").status_code == 200
    api.documents_delete("../outside.txt")
    assert removed == ["note.txt", "outside.txt"]
    assert not (inbox / "note.txt").exists()
    assert outside.exists()


def test_ui_returns_saved_dialogs_before_index_is_ready(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: (_ for _ in ()).throw(AssertionError("chroma")))
    saved = workspace.create_dialog()
    saved["title"] = "сохранённый"
    data = workspace.load()
    data["dialogs"][0] = saved
    workspace.save(data)
    done = api._state["done"]
    api._state["done"] = False
    try:
        listed = api.ui_get()
    finally:
        api._state["done"] = done
    assert listed["dialogs"][0]["id"] == saved["id"]
    assert listed["dialogs"][0]["title"] == "сохранённый"


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
    api._state["done"] = True
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


def test_tree_keeps_inbox_file_missing_from_the_index(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "note.txt").write_text("текст", encoding="utf-8")
    monkeypatch.setattr("api.INBOX", inbox)
    monkeypatch.setattr("api.list_documents", lambda: [])
    client = TestClient(app)
    tree = {
        "id": "root",
        "name": "",
        "children": [
            {"id": "folder", "name": "Папка", "children": [
                {"document_name": "note.txt"},
                {"document_name": "gone.txt"},
            ]},
        ],
    }
    saved = client.put("/ui", json={"tree": tree}).json()["tree"]
    assert saved["children"][0]["name"] == "Папка"
    assert saved["children"][0]["children"] == [{"document_name": "note.txt"}]
    listed = client.get("/ui").json()["tree"]
    assert listed["children"][0]["children"] == [{"document_name": "note.txt"}]
    stored = workspace.load()["tree"]
    assert stored["children"][0]["children"] == [{"document_name": "note.txt"}]


def test_query_reloads_saved_history_after_memory_is_cleared(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    seen = []

    def run(query, dialog_id):
        seen.append([
            (turn["query"], turn["document_names"])
            for turn in dialog.get_dialog(dialog_id)
        ])
        return {"answer": "ответ", "status": "подтверждён", "document_names": ["note.txt"], "sources": []}

    monkeypatch.setattr("api.run", run)
    dialog.reset()
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert client.post("/query", json={"query": "первый", "dialog_id": created["id"]}).status_code == 200
    dialog.add_turn(created["id"], {"query": "устарело", "answer": "x", "document_names": ["other.md"]})
    assert client.post("/query", json={"query": "второй", "dialog_id": created["id"]}).status_code == 200
    assert seen == [[], [("первый", ["note.txt"])]]


def test_upload_keeps_the_file_inside_inbox(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr("api.INBOX", inbox)
    monkeypatch.setattr("api.ingest_dir", lambda folder: [])
    monkeypatch.setattr("api.upsert_chunks", lambda chunks: None)
    monkeypatch.setattr("api.list_documents", lambda: ["outside.txt"])
    outside = tmp_path / "outside.txt"
    outside.write_text("чужой файл", encoding="utf-8")
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("../outside.txt", "новый текст".encode(), "text/plain"))],
    )
    assert response.status_code == 200
    assert outside.read_text(encoding="utf-8") == "чужой файл"
    assert (inbox / "outside.txt").read_text(encoding="utf-8") == "новый текст"


def test_missing_dialog_and_turn_return_404(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: [])
    client = TestClient(app)
    assert client.get("/ui/dialogs/missing").status_code == 404
    created = client.post("/ui/dialogs").json()
    missing = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 4},
    )
    assert missing.status_code == 404


def test_query_error_does_not_store_a_turn(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: [])

    def run(query, dialog_id):
        raise RuntimeError("model down")

    monkeypatch.setattr("api.run", run)
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    response = client.post("/query", json={"query": "номер", "dialog_id": created["id"]})
    assert response.status_code == 500
    saved = workspace.load()["dialogs"]
    assert all(turn.get("query") != "номер" for row in saved for turn in row.get("turns") or [])


def test_rating_outside_one_to_five_is_stored_empty(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    monkeypatch.setattr("api.run", lambda query, dialog_id: {
        "answer": "Цех имеет номер 4 [1].",
        "status": "подтверждён",
        "document_names": ["note.txt"],
        "sources": [],
    })
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert client.post("/query", json={"query": "номер", "dialog_id": created["id"]}).status_code == 200
    patched = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 6, "answer_correct": 0, "documents": {"../secret/note.txt": 3}},
    )
    assert patched.status_code == 200
    assert patched.json()["ratings"]["answer_complete"] is None
    assert patched.json()["ratings"]["answer_correct"] is None
    assert patched.json()["ratings"]["documents"] == {"note.txt": 3}


def test_query_drops_stale_memory_when_the_dialog_is_not_on_disk(monkeypatch):
    seen = []

    def run(query, dialog_id):
        seen.append([turn["query"] for turn in dialog.get_dialog(dialog_id)])
        return {"answer": "ответ", "status": "подтверждён", "document_names": [], "sources": []}

    monkeypatch.setattr("api.run", run)
    dialog.reset()
    dialog.add_turn("fresh", {"query": "устарело", "answer": "x", "document_names": ["secret.txt"]})
    client = TestClient(app)
    assert client.post("/query", json={"query": "новый", "dialog_id": "fresh"}).status_code == 200
    assert seen == [[]]
    stored = next(row for row in workspace.load()["dialogs"] if row["id"] == "fresh")
    assert [turn["query"] for turn in stored["turns"]] == ["новый"]


def test_query_does_not_restore_a_dialog_deleted_while_answering(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: [])

    def run(query, dialog_id):
        workspace.delete_dialog(dialog_id)
        return {"answer": "Цех имеет номер 4 [1].", "status": "подтверждён", "document_names": [], "sources": []}

    monkeypatch.setattr("api.run", run)
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    response = client.post("/query", json={"query": "номер", "dialog_id": created["id"]})
    assert response.status_code == 200
    assert response.json()["answer"] == "Цех имеет номер 4 [1]."
    saved = workspace.load()["dialogs"]
    assert all(row["id"] != created["id"] for row in saved)
    assert all(turn.get("query") != "номер" for row in saved for turn in row.get("turns") or [])

def test_upload_writes_only_the_file_name(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr("api.INBOX", inbox)
    monkeypatch.setattr("api.ingest_dir", lambda folder: [])
    monkeypatch.setattr("api.upsert_chunks", lambda chunks: None)
    monkeypatch.setattr("api.list_documents", lambda: ["outside.txt", "note.txt"])
    outside = tmp_path / "outside.txt"
    outside.write_text("чужой файл", encoding="utf-8")

    class FakeUpload:
        def __init__(self, filename, payload):
            self.filename = filename
            self.payload = payload

        async def read(self):
            return self.payload

    result = asyncio.run(api.upload([
        FakeUpload("../outside.txt", "Цех имеет номер 4.".encode()),
        FakeUpload("subdir/note.txt", "Насос Н-12.".encode()),
    ]))
    assert (inbox / "outside.txt").read_text(encoding="utf-8") == "Цех имеет номер 4."
    assert (inbox / "note.txt").read_text(encoding="utf-8") == "Насос Н-12."
    assert not (inbox / "subdir").exists()
    assert outside.read_text(encoding="utf-8") == "чужой файл"
    assert _doc_names(result) == ["outside.txt", "note.txt"]

def test_delete_document_keeps_the_saved_answer(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    known = ["note.txt", "gone.txt"]
    monkeypatch.setattr("api.INBOX", inbox)
    monkeypatch.setattr("api.list_documents", lambda: list(known))

    def forget(name):
        if name in known:
            known.remove(name)

    monkeypatch.setattr("api.delete_document", forget)
    monkeypatch.setattr("api.run", lambda query, dialog_id: {
        "answer": "ответ",
        "status": "подтверждён",
        "document_names": ["gone.txt"],
        "sources": [],
    })
    (inbox / "gone.txt").write_text("текст", encoding="utf-8")
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert client.post("/query", json={"query": "вопрос", "dialog_id": created["id"]}).status_code == 200
    placed = client.put("/ui", json={
        "tree": {
            "id": "root",
            "name": "",
            "children": [{"document_name": "gone.txt"}, {"document_name": "note.txt"}],
        },
    })
    assert placed.status_code == 200
    response = client.delete("/kb/00000000-0000-4000-8000-000000000001/documents/gone.txt")
    assert response.status_code == 200
    assert _doc_names(response.json()) == ["note.txt"]
    assert workspace.iter_files(response.json()["tree"]) == ["note.txt"]
    saved = next(item for item in workspace.load()["dialogs"] if item["id"] == created["id"])
    assert saved["turns"][0]["query"] == "вопрос"
    assert saved["turns"][0]["answer"] == "ответ"
    assert "gone.txt" not in workspace.iter_files(workspace.load()["tree"])
    assert not (inbox / "gone.txt").exists()

def test_missing_dialog_and_turn_are_not_found():
    client = TestClient(app)
    assert client.get("/ui/dialogs/missing").status_code == 404
    created = client.post("/ui/dialogs").json()
    missing_turn = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 3},
    )
    assert missing_turn.status_code == 404
    assert client.patch(
        "/ui/dialogs/missing/turns/0/ratings",
        json={"answer_complete": 3},
    ).status_code == 404

def test_query_failure_does_not_save_a_turn(monkeypatch):
    def run(query, dialog_id):
        raise RuntimeError("model down")

    monkeypatch.setattr("api.run", run)
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    response = client.post("/query", json={"query": "номер", "dialog_id": created["id"]})
    assert response.status_code == 500
    assert response.json()["detail"] == "Ошибка сервера"
    assert workspace.get_dialog_row(created["id"])["turns"] == []

def test_ratings_reject_out_of_range_and_missing_turns(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    monkeypatch.setattr("api.run", lambda query, dialog_id: {
        "answer": "Цех имеет номер 4 [1].",
        "status": "подтверждён",
        "document_names": ["note.txt"],
        "sources": [SOURCE],
    })
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert client.post("/query", json={"query": "номер", "dialog_id": created["id"]}).status_code == 200
    ok = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_correct": 5, "links": {"1": 4}},
    )
    assert ok.status_code == 200
    bad = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 9, "links": {"2": 6}, "documents": {"../note.txt": 3}},
    )
    assert bad.status_code == 200
    ratings = bad.json()["ratings"]
    assert ratings["answer_complete"] is None
    assert ratings["answer_correct"] == 5
    assert ratings["links"] == {"1": 4, "2": None}
    assert ratings["documents"] == {"note.txt": 3}
    missing = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/2/ratings",
        json={"answer_complete": 1},
    )
    assert missing.status_code == 404
    unknown = client.patch("/ui/dialogs/missing/turns/0/ratings", json={"answer_complete": 1})
    assert unknown.status_code == 404

def test_upload_strips_directory_from_filename(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr("api.INBOX", inbox)
    monkeypatch.setattr("api.ingest_dir", lambda folder: [])
    monkeypatch.setattr("api.upsert_chunks", lambda chunks: None)
    monkeypatch.setattr("api.list_documents", lambda: ["outside.txt"])
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("../outside.txt", "чужой файл", "text/plain"))],
    )
    assert response.status_code == 200
    assert (inbox / "outside.txt").read_text(encoding="utf-8") == "чужой файл"
    assert not (tmp_path / "outside.txt").exists()

def test_query_ignores_memory_for_an_unsaved_dialog(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: [])
    seen = []

    def run(query, dialog_id):
        seen.append(dialog.get_dialog(dialog_id))
        return {"answer": "ответ", "status": "подтверждён", "document_names": [], "sources": []}

    monkeypatch.setattr("api.run", run)
    dialog.reset()
    dialog.add_turn("ghost", {"query": "секрет", "answer": "x", "document_names": ["hidden.txt"]})
    client = TestClient(app)
    response = client.post("/query", json={"query": "новый", "dialog_id": "ghost"})
    assert response.status_code == 200
    assert seen == [[]]
    saved = next(row for row in workspace.load()["dialogs"] if row["id"] == "ghost")
    assert saved["turns"][0]["query"] == "новый"
    assert saved["turns"][0]["document_names"] == []

def test_rating_rejects_out_of_range_and_missing_turn(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    monkeypatch.setattr("api.run", lambda query, dialog_id: {
        "answer": "ответ",
        "status": "подтверждён",
        "document_names": ["note.txt"],
        "sources": [],
    })
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert client.post("/query", json={"query": "вопрос", "dialog_id": created["id"]}).status_code == 200
    patched = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 9, "answer_correct": 1, "documents": {"../note.txt": 4}, "links": {"1": 0}},
    )
    assert patched.status_code == 200
    ratings = patched.json()["ratings"]
    assert ratings["answer_complete"] is None
    assert ratings["answer_correct"] == 1
    assert ratings["documents"] == {"note.txt": 4}
    assert ratings["links"] == {"1": None}
    assert client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/3/ratings",
        json={"answer_complete": 2},
    ).status_code == 404
    assert client.get("/ui/dialogs/missing").status_code == 404

def test_query_after_delete_does_not_reuse_the_answer_memory(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: [])
    seen = []

    def run(query, dialog_id):
        if query == "первый":
            workspace.delete_dialog(dialog_id)
            dialog.add_turn(dialog_id, {"query": query, "answer": "хвост", "document_names": ["note.txt"]})
        seen.append([turn["query"] for turn in dialog.get_dialog(dialog_id)])
        return {"answer": "ответ", "status": "подтверждён", "document_names": [], "sources": []}

    monkeypatch.setattr("api.run", run)
    dialog.reset()
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert client.post("/query", json={"query": "первый", "dialog_id": created["id"]}).status_code == 200
    assert client.post("/query", json={"query": "второй", "dialog_id": created["id"]}).status_code == 200
    assert seen == [["первый"], []]
    saved = workspace.load()["dialogs"]
    assert [turn.get("query") for row in saved for turn in row.get("turns") or []] == ["второй"]

def test_ratings_drop_out_of_range_scores_and_path_keys(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    monkeypatch.setattr("api.run", lambda query, dialog_id: {
        "answer": "Цех имеет номер 4 [1].",
        "status": "подтверждён",
        "document_names": ["note.txt"],
        "sources": [SOURCE],
    })
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert client.post("/query", json={"query": "номер", "dialog_id": created["id"]}).status_code == 200
    saved = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 4, "answer_correct": 5, "links": {"1": 3}},
    )
    assert saved.status_code == 200
    updated = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 9, "documents": {"../../note.txt": 2, "other.txt": 0}},
    )
    assert updated.status_code == 200
    ratings = updated.json()["ratings"]
    assert ratings["answer_complete"] is None
    assert ratings["answer_correct"] == 5
    assert ratings["links"]["1"] == 3
    assert ratings["documents"] == {"note.txt": 2, "other.txt": None}

def test_upload_keeps_the_file_inside_the_inbox(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    monkeypatch.setattr("api.INBOX", inbox)
    monkeypatch.setattr("api.ingest_dir", lambda folder: [])
    monkeypatch.setattr("api.upsert_chunks", lambda chunks: None)
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    outside = tmp_path / "note.txt"
    outside.write_text("чужой файл", encoding="utf-8")
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("../note.txt", "Цех имеет номер 4.", "text/plain"))],
    )
    assert response.status_code == 200
    assert (inbox / "note.txt").read_text(encoding="utf-8") == "Цех имеет номер 4."
    assert outside.read_text(encoding="utf-8") == "чужой файл"
    assert {path.resolve() for path in tmp_path.rglob("note.txt")} == {
        outside.resolve(),
        (inbox / "note.txt").resolve(),
    }

def test_ready_waits_until_the_model_file_is_present(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL_PATH", str(tmp_path / "missing.gguf"))
    response = TestClient(app).get("/ready")
    assert response.status_code == 503
    assert isinstance(response.json()["elapsed_sec"], int)

def test_rating_patch_keeps_fields_the_body_omits(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    monkeypatch.setattr("api.run", lambda query, dialog_id: {
        "answer": "Цех имеет номер 4 [1].",
        "status": "подтверждён",
        "document_names": ["note.txt"],
        "sources": [{"number": 1, "document_name": "note.txt", "section": "", "chunk_index": 0}],
    })
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert client.post("/query", json={"query": "номер", "dialog_id": created["id"]}).status_code == 200
    base = "/ui/dialogs/" + created["id"] + "/turns/"
    assert client.patch(base + "0/ratings", json={"answer_complete": 4}).status_code == 200
    second = client.patch(base + "0/ratings", json={"answer_correct": 5, "links": {"1": 3}})
    assert second.status_code == 200
    assert second.json()["ratings"]["answer_complete"] == 4
    assert second.json()["ratings"]["answer_correct"] == 5
    assert second.json()["ratings"]["links"] == {"1": 3}
    denied = client.patch(base + "-1/ratings", json={"answer_correct": 1})
    assert denied.status_code == 404
    stored = client.get("/ui/dialogs/" + created["id"]).json()
    assert stored["turns"][0]["ratings"]["answer_complete"] == 4
    assert stored["turns"][0]["ratings"]["answer_correct"] == 5
    assert stored["turns"][0]["answer"] == "Цех имеет номер 4 [1]."

def test_upload_keeps_the_name_inside_inbox(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    monkeypatch.setattr("api.INBOX", inbox)
    saved = []
    seen = []

    def remember(chunks):
        saved.extend(chunk["document_name"] for chunk in chunks)

    def ingest(folder):
        seen.append(folder)
        return [
            {"document_name": path.name}
            for path in sorted(folder.iterdir())
            if path.is_file()
        ]

    monkeypatch.setattr("api.upsert_chunks", remember)
    monkeypatch.setattr("api.ingest_dir", ingest)
    monkeypatch.setattr("api.list_documents", lambda: saved)
    outside = tmp_path / "outside.txt"
    client = TestClient(app)
    response = client.post("/upload", files=[
        ("files", ("../outside.txt", "Секретный текст.", "text/plain")),
        ("files", ("nested/secret.txt", "Второй текст.", "text/plain")),
    ])
    assert response.status_code == 200
    assert seen == [inbox]
    assert not outside.exists()
    assert not (inbox / "nested").exists()
    assert (inbox / "outside.txt").read_text(encoding="utf-8") == "Секретный текст."
    assert (inbox / "secret.txt").read_text(encoding="utf-8") == "Второй текст."
    assert saved == ["outside.txt", "secret.txt"]

def test_rating_patch_keeps_unsent_scores(monkeypatch):
    monkeypatch.setattr("api.list_documents", lambda: ["note.txt"])
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    workspace.append_turn(created["id"], "номер", {
        "answer": "4",
        "sources": [{"document_name": "note.txt"}],
        "document_names": ["note.txt"],
    })
    first = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 4, "links": {"1": 3}, "documents": {"note.txt": 2}},
    )
    assert first.status_code == 200
    second = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_correct": 5},
    )
    ratings = second.json()["ratings"]
    assert ratings["answer_complete"] == 4
    assert ratings["answer_correct"] == 5
    assert ratings["links"]["1"] == 3
    assert ratings["documents"]["note.txt"] == 2
    cleared = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 9},
    )
    assert cleared.status_code == 200
    assert cleared.json()["ratings"]["answer_complete"] is None
    assert cleared.json()["ratings"]["answer_correct"] == 5
    assert client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/3/ratings",
        json={"answer_complete": 1},
    ).status_code == 404
    assert client.patch(
        "/ui/dialogs/missing/turns/0/ratings",
        json={"answer_complete": 1},
    ).status_code == 404
    assert client.get("/ui/dialogs/missing").status_code == 404

def test_delete_document_drops_tree_node_and_keeps_dialog(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    names = ["note.txt", "keep.txt"]
    monkeypatch.setattr("api.INBOX", inbox)
    monkeypatch.setattr("api.delete_document", lambda name: names.remove(name) if name in names else None)
    monkeypatch.setattr("api.list_documents", lambda: list(names))
    (inbox / "note.txt").write_text("текст", encoding="utf-8")
    (inbox / "keep.txt").write_text("остаётся", encoding="utf-8")
    client = TestClient(app)
    client.put("/ui", json={"tree": {
        "id": "root",
        "name": "",
        "children": [
            {"id": "folder", "name": "Папка", "children": [{"document_name": "note.txt"}]},
            {"document_name": "keep.txt"},
        ],
    }})
    created = client.post("/ui/dialogs").json()
    workspace.append_turn(created["id"], "вопрос", _answer_row())
    response = client.delete("/kb/00000000-0000-4000-8000-000000000001/documents/note.txt")
    assert response.status_code == 200
    assert _doc_names(response.json()) == ["keep.txt"]
    assert workspace.iter_files(response.json()["tree"]) == ["keep.txt"]
    assert response.json()["tree"]["children"][0]["name"] == "Папка"
    saved = workspace.load()
    assert saved["dialogs"][0]["turns"][0]["answer"] == "ответ"
    assert not (inbox / "note.txt").exists()
    assert (inbox / "keep.txt").read_text(encoding="utf-8") == "остаётся"

def test_ratings_out_of_range_are_cleared_and_missing_turns_are_404(monkeypatch):
    monkeypatch.setattr("api.run", lambda query, dialog_id: {
        "answer": "ответ", "status": "подтверждён", "document_names": [], "sources": [],
    })
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert client.post("/query", json={"query": "вопрос", "dialog_id": created["id"]}).status_code == 200
    patched = client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/0/ratings",
        json={"answer_complete": 0, "answer_correct": 6},
    )
    assert patched.status_code == 200
    assert patched.json()["ratings"]["answer_complete"] is None
    assert patched.json()["ratings"]["answer_correct"] is None
    assert client.patch(
        "/ui/dialogs/" + created["id"] + "/turns/4/ratings",
        json={"answer_complete": 3},
    ).status_code == 404
    dialog.add_turn("ghost", {"query": "жив", "answer": "a", "document_names": []})
    assert client.get("/ui/dialogs/ghost").status_code == 404
    assert dialog.get_dialog("ghost")[0]["query"] == "жив"

def test_delete_document_keeps_the_dialog(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    listed = {"names": ["note.txt", "kept.txt"]}
    monkeypatch.setattr("api.INBOX", inbox)
    monkeypatch.setattr("api.list_documents", lambda: list(listed["names"]))
    monkeypatch.setattr("api.delete_document", lambda name: listed.update(names=["kept.txt"]))
    monkeypatch.setattr("api.run", lambda query, dialog_id: {
        "answer": "ответ", "status": "подтверждён", "document_names": ["note.txt"], "sources": [],
    })
    (inbox / "note.txt").write_text("текст", encoding="utf-8")
    client = TestClient(app)
    created = client.post("/ui/dialogs").json()
    assert client.post("/query", json={"query": "вопрос", "dialog_id": created["id"]}).status_code == 200
    client.put("/ui", json={
        "tree": {
            "id": "root",
            "name": "",
            "children": [
                {"id": "folder", "name": "Папка", "children": [{"document_name": "note.txt"}]},
                {"document_name": "kept.txt"},
            ],
        }
    })
    response = client.delete("/kb/00000000-0000-4000-8000-000000000001/documents/note.txt")
    assert response.status_code == 200
    assert _doc_names(response.json()) == ["kept.txt"]
    assert "note.txt" not in workspace.iter_files(response.json()["tree"])
    assert {"document_name": "kept.txt"} in response.json()["tree"]["children"]
    saved = next(row for row in workspace.load()["dialogs"] if row["id"] == created["id"])
    assert saved["turns"][0]["query"] == "вопрос"
    assert not (inbox / "note.txt").exists()


def test_delete_during_upload_is_not_indexed_again(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "keep.txt").write_text("секрет", encoding="utf-8")
    indexed = {"keep.txt"}
    monkeypatch.setattr(api, "INBOX", inbox)
    monkeypatch.setattr(api, "delete_document", lambda name: indexed.discard(name))
    monkeypatch.setattr(api, "list_documents", lambda: sorted(indexed))
    monkeypatch.setattr(api, "upsert_chunks", lambda chunks: indexed.update(chunk["document_name"] for chunk in chunks))
    monkeypatch.setattr(api, "_blocks", lambda path: [{"kind": "p", "text": "новый"}])
    monkeypatch.setattr(api, "chunks_from_blocks", lambda blocks, name: [{"document_name": name}] if blocks else [])
    started = threading.Event()
    release = threading.Event()

    def ingest(folder):
        chunks = [
            {"document_name": path.name}
            for path in sorted(folder.iterdir())
            if path.is_file() and path.suffix.lower() == ".txt"
        ]
        started.set()
        assert release.wait(5)
        return chunks

    monkeypatch.setattr(api, "ingest_dir", ingest)
    began = threading.Event()
    finished = threading.Event()
    errors = []

    def delete_keep():
        began.set()
        try:
            api.documents_delete("keep.txt")
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    def upload_new():
        try:
            api._save_uploads([("new.txt", "новый текст".encode())])
        except Exception as exc:
            errors.append(exc)
        finally:
            release.set()

    uploader = threading.Thread(target=upload_new)
    deleter = threading.Thread(target=delete_keep)
    uploader.start()
    try:
        assert started.wait(5)
        deleter.start()
        assert began.wait(2)
        # The upload still holds the inbox snapshot. The delete has to wait
        # for that snapshot to be indexed, or the upload writes the file back.
        assert not finished.wait(0.3)
    finally:
        release.set()
    uploader.join(5)
    deleter.join(5)
    assert errors == []
    assert not uploader.is_alive()
    assert not deleter.is_alive()
    assert indexed == {"new.txt"}
    assert not (inbox / "keep.txt").exists()
    assert (inbox / "new.txt").read_text(encoding="utf-8") == "новый текст"


def test_startup_index_does_not_restore_a_document_deleted_while_it_runs(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "keep.txt").write_text("секрет", encoding="utf-8")
    (inbox / "stay.txt").write_text("остается", encoding="utf-8")
    indexed = {"keep.txt", "stay.txt"}
    previous = dict(api._state)
    monkeypatch.setattr(api, "INBOX", inbox)
    monkeypatch.setattr(api, "LOAD_TIME", tmp_path / "load_time.txt")
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(api, "delete_document", lambda name: indexed.discard(name))
    monkeypatch.setattr(api, "list_documents", lambda: sorted(indexed))
    monkeypatch.setattr(api, "upsert_chunks", lambda chunks: indexed.update(chunk["document_name"] for chunk in chunks))
    monkeypatch.setattr("store._embed", lambda _texts: None)
    monkeypatch.setattr("llm.load", lambda: None)
    started = threading.Event()
    release = threading.Event()

    def ingest(folder):
        chunks = [
            {"document_name": path.name}
            for path in sorted(folder.iterdir())
            if path.is_file() and path.suffix.lower() == ".txt"
        ]
        started.set()
        assert release.wait(5)
        return chunks

    monkeypatch.setattr(api, "ingest_dir", ingest)
    began = threading.Event()
    finished = threading.Event()
    errors = []

    def delete_keep():
        began.set()
        try:
            api.documents_delete("keep.txt")
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    def warm():
        try:
            api._warm()
        except Exception as exc:
            errors.append(exc)

    warmer = threading.Thread(target=warm)
    deleter = threading.Thread(target=delete_keep)
    warmer.start()
    try:
        assert started.wait(5)
        deleter.start()
        assert began.wait(2)
        # Startup still holds the inbox snapshot. The delete has to wait,
        # or the snapshot writes the removed file back into the index.
        assert not finished.wait(0.3)
    finally:
        release.set()
        warmer.join(5)
        deleter.join(5)
        api._state.clear()
        api._state.update(previous)
    assert errors == []
    assert not warmer.is_alive()
    assert not deleter.is_alive()
    assert indexed == {"stay.txt"}
    assert not (inbox / "keep.txt").exists()
    assert (inbox / "stay.txt").read_text(encoding="utf-8") == "остается"


def test_reindex_does_not_restore_a_document_deleted_while_it_runs(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "keep.txt").write_text("секрет", encoding="utf-8")
    (inbox / "stay.txt").write_text("остается", encoding="utf-8")
    indexed = {"keep.txt", "stay.txt"}
    monkeypatch.setattr(api, "INBOX", inbox)
    monkeypatch.setattr(api, "delete_document", lambda name: indexed.discard(name))
    monkeypatch.setattr(api, "list_documents", lambda: sorted(indexed))
    monkeypatch.setattr(api, "upsert_chunks", lambda chunks: indexed.update(chunk["document_name"] for chunk in chunks))
    started = threading.Event()
    release = threading.Event()

    def ingest(folder):
        chunks = [
            {"document_name": path.name}
            for path in sorted(folder.iterdir())
            if path.is_file() and path.suffix.lower() == ".txt"
        ]
        started.set()
        assert release.wait(5)
        return chunks

    monkeypatch.setattr(api, "ingest_dir", ingest)
    began = threading.Event()
    finished = threading.Event()
    errors = []

    def delete_keep():
        began.set()
        try:
            api.documents_delete("keep.txt")
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    def reindex():
        try:
            api.documents(api.Docs(directory=str(inbox)))
        except Exception as exc:
            errors.append(exc)
        finally:
            release.set()

    indexer = threading.Thread(target=reindex)
    deleter = threading.Thread(target=delete_keep)
    indexer.start()
    try:
        assert started.wait(5)
        deleter.start()
        assert began.wait(2)
        assert not finished.wait(0.3)
    finally:
        release.set()
    indexer.join(5)
    deleter.join(5)
    assert errors == []
    assert not indexer.is_alive()
    assert not deleter.is_alive()
    assert indexed == {"stay.txt"}
    assert not (inbox / "keep.txt").exists()
    assert (inbox / "stay.txt").read_text(encoding="utf-8") == "остается"


def test_upload_rejects_a_directory_and_restores_the_earlier_file(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "note.txt").write_text("старое значение", encoding="utf-8")
    occupied = inbox / "slot.txt"
    occupied.mkdir()
    (occupied / "secret.txt").write_text("секрет", encoding="utf-8")
    monkeypatch.setattr("api.INBOX", inbox)
    cache = _token_count(monkeypatch)
    called = []
    monkeypatch.setattr("api.upsert_chunks", called.append)
    response = TestClient(app).post(
        "/upload",
        files=[
            ("files", ("note.txt", "новое значение".encode(), "text/plain")),
            ("files", ("slot.txt", "внутрь".encode(), "text/plain")),
        ],
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Некорректное имя файла"
    assert called == []
    assert (inbox / "note.txt").read_text(encoding="utf-8") == "старое значение"
    assert occupied.is_dir()
    assert (occupied / "secret.txt").read_text(encoding="utf-8") == "секрет"
    cache.cache_clear()

def test_ready_ignores_a_corrupt_load_time(tmp_path, monkeypatch):
    previous = dict(api._state)
    monkeypatch.setattr(api, "LOAD_TIME", tmp_path / "load_time.txt")
    monkeypatch.setenv("LLM_MODEL_PATH", str(tmp_path / "missing.gguf"))
    api._state["done"] = False
    api._state["started"] = time.time() - 5
    try:
        (tmp_path / "load_time.txt").write_text("nope", encoding="utf-8")
        assert TestClient(app).get("/ready").json()["eta_sec"] is None
        (tmp_path / "load_time.txt").write_text("3", encoding="utf-8")
        assert TestClient(app).get("/ready").json()["eta_sec"] == 0
        (tmp_path / "load_time.txt").write_text("100000", encoding="utf-8")
        assert TestClient(app).get("/ready").json()["eta_sec"] > 1000
    finally:
        api._state.clear()
        api._state.update(previous)

def test_rollback_continues_after_one_file_fails(tmp_path):
    restored = tmp_path / "restored.txt"
    restored.write_text("new", encoding="utf-8")

    class Locked:
        def unlink(self, missing_ok=True):
            raise OSError("busy")

        def write_bytes(self, _data):
            raise AssertionError("locked file should be removed, not rewritten")

    class Restored:
        def unlink(self, missing_ok=True):
            raise AssertionError("previous bytes should be written back")

        def write_bytes(self, data):
            restored.write_bytes(data)

    api._rollback_upload([(Restored(), "старое".encode()), (Locked(), None)])
    assert restored.read_text(encoding="utf-8") == "старое"

def test_upload_keeps_the_file_when_indexing_fails(tmp_path, monkeypatch):
    monkeypatch.setattr("api.INBOX", tmp_path)
    cache = _token_count(monkeypatch)

    def boom(_chunks):
        raise RuntimeError("index down")

    monkeypatch.setattr("api.upsert_chunks", boom)
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("note.txt", "Цех имеет номер 4.".encode(), "text/plain"))],
    )
    assert response.status_code == 500
    assert response.json()["detail"] == "Не удалось записать файл"
    assert (tmp_path / "note.txt").read_text(encoding="utf-8") == "Цех имеет номер 4."
    cache.cache_clear()

def test_upload_restores_the_file_when_the_parser_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("api.INBOX", tmp_path)
    original = b"previous-docx"
    (tmp_path / "note.docx").write_bytes(original)
    (tmp_path / "keep.txt").write_text("Цех имеет номер 4.", encoding="utf-8")
    called = []
    monkeypatch.setattr("api.upsert_chunks", called.append)

    def missing(_path):
        raise ImportError("python-docx")

    monkeypatch.setattr("ingest._docx_blocks", missing)
    response = TestClient(app).post(
        "/upload",
        files=[("files", ("note.docx", b"new-docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))],
    )
    assert response.status_code == 500
    assert called == []
    assert (tmp_path / "note.docx").read_bytes() == original
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "Цех имеет номер 4."


def test_reindex_does_not_restore_a_document_deleted_while_it_runs(tmp_path, monkeypatch):
    # POST /documents reads the inbox and then indexes that snapshot. Without the
    # same lock as upload, a delete in between removes the file and the snapshot
    # puts it back.
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "keep.txt").write_text("секрет", encoding="utf-8")
    (inbox / "stay.txt").write_text("остается", encoding="utf-8")
    indexed = {"keep.txt", "stay.txt"}
    monkeypatch.setattr(api, "INBOX", inbox)
    monkeypatch.setattr(api, "delete_document", lambda name: indexed.discard(name))
    monkeypatch.setattr(api, "list_documents", lambda: sorted(indexed))
    monkeypatch.setattr(api, "upsert_chunks", lambda chunks: indexed.update(chunk["document_name"] for chunk in chunks))
    started = threading.Event()
    release = threading.Event()

    def ingest(folder):
        chunks = [
            {"document_name": path.name}
            for path in sorted(folder.iterdir())
            if path.is_file() and path.suffix.lower() == ".txt"
        ]
        started.set()
        assert release.wait(5)
        return chunks

    monkeypatch.setattr(api, "ingest_dir", ingest)
    began = threading.Event()
    finished = threading.Event()
    errors = []

    def delete_keep():
        began.set()
        try:
            api.documents_delete("keep.txt")
        except Exception as exc:
            errors.append(exc)
        finally:
            finished.set()

    def reindex():
        try:
            api.documents(api.Docs(directory=str(inbox)))
        except Exception as exc:
            errors.append(exc)
        finally:
            release.set()

    indexer = threading.Thread(target=reindex)
    deleter = threading.Thread(target=delete_keep)
    indexer.start()
    try:
        assert started.wait(5)
        deleter.start()
        assert began.wait(2)
        assert not finished.wait(0.3)
    finally:
        release.set()
    indexer.join(5)
    deleter.join(5)
    assert errors == []
    assert not indexer.is_alive()
    assert not deleter.is_alive()
    assert indexed == {"stay.txt"}
    assert not (inbox / "keep.txt").exists()
    assert (inbox / "stay.txt").read_text(encoding="utf-8") == "остается"
