import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import workspace
from coordinator import run
from ingest import ingest_dir
from store import chunks_for_document, delete_document, list_documents, upsert_chunks

app = FastAPI()
INBOX = Path("data/inbox")
PAGE = Path(__file__).parent / "web" / "index.html"
ROOT = Path(__file__).resolve().parents[1]
LOAD_TIME = ROOT / "data" / "load_time.txt"
_state = {"started": None, "done": False}


def _files_ok():
    model = Path(os.environ.get("LLM_MODEL_PATH", ""))
    embed = ROOT / "data" / "models" / "multilingual-e5-small"
    return model.is_file() and embed.is_dir()


def _eta(elapsed):
    if not LOAD_TIME.is_file():
        return None
    try:
        saved = float(LOAD_TIME.read_text(encoding="utf-8") or 0)
    except ValueError:
        return None
    return max(0, int(saved - elapsed))


def _warm():
    _state["started"] = time.time()
    from llm import load
    from store import _embed
    _embed(["passage: готов"])
    if INBOX.is_dir():
        upsert_chunks(ingest_dir(INBOX))
    _state["done"] = True
    time.sleep(1)
    load()
    LOAD_TIME.parent.mkdir(parents=True, exist_ok=True)
    LOAD_TIME.write_text(str(int(time.time() - _state["started"])), encoding="utf-8")


@app.on_event("startup")
def startup():
    if os.environ.get("PYTEST_CURRENT_TEST"):
        _state["started"] = time.time()
        _state["done"] = _files_ok()
        return
    threading.Thread(target=_warm, daemon=True).start()


class Docs(BaseModel):
    directory: str


class Query(BaseModel):
    query: str
    dialog_id: str


class UiTree(BaseModel):
    tree: dict


class Ratings(BaseModel):
    answer_complete: int | None = None
    answer_correct: int | None = None
    links: dict | None = None
    documents: dict | None = None


def _fields(body):
    if hasattr(body, "model_dump"):
        return body.model_dump(exclude_unset=True)
    return body.dict(exclude_unset=True)


@app.get("/")
def page():
    return FileResponse(PAGE, headers={"Cache-Control": "no-store"})


@app.get("/ready")
def ready():
    from llm import loaded
    if (_state["done"] or loaded) and _files_ok():
        return {"ready": True}
    elapsed = 0 if _state["started"] is None else int(time.time() - _state["started"])
    return JSONResponse(
        status_code=503,
        content={"elapsed_sec": elapsed, "eta_sec": _eta(elapsed)},
    )


@app.get("/documents")
def documents_list():
    return {"documents": list_documents()}


@app.get("/documents/{document_name:path}/preview")
def documents_preview(document_name: str):
    name = Path(document_name).name
    if name not in list_documents():
        raise HTTPException(404, detail="Документ не найден")
    return {"document_name": name, "chunks": chunks_for_document(name)}


@app.delete("/documents/{document_name:path}")
def documents_delete(document_name: str):
    name = Path(document_name).name
    delete_document(name)
    path = INBOX / name
    if path.is_file():
        path.unlink()
    known = list_documents()
    return {"documents": known, "tree": workspace.forget_file(name, known)}


@app.post("/documents")
def documents(body: Docs):
    folder = Path(body.directory).resolve()
    if folder != INBOX.resolve():
        raise HTTPException(400, detail="Загружать можно только папку data/inbox")
    upsert_chunks(ingest_dir(folder))
    return {"ok": True}


@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    try:
        INBOX.mkdir(parents=True, exist_ok=True)
        for item in files:
            (INBOX / Path(item.filename).name).write_bytes(await item.read())
        upsert_chunks(ingest_dir(INBOX))
        names = list_documents()
        return {"documents": names, "tree": workspace.snapshot(names)["tree"]}
    except Exception as exc:
        raise HTTPException(500, detail=str(exc)) from exc


@app.get("/ui")
def ui_get():
    if not _state["done"]:
        return workspace.load()
    return workspace.snapshot(list_documents())


@app.put("/ui")
def ui_put(body: UiTree):
    return workspace.put_tree(body.tree, list_documents())


@app.post("/ui/dialogs")
def ui_dialog_create():
    return workspace.create_dialog()


@app.get("/ui/dialogs/{dialog_id}")
def ui_dialog_get(dialog_id: str):
    row = workspace.get_dialog_row(dialog_id)
    if row is None:
        raise HTTPException(404, detail="Диалог не найден")
    return row


@app.delete("/ui/dialogs/{dialog_id}")
def ui_dialog_delete(dialog_id: str):
    return workspace.delete_dialog(dialog_id)


@app.patch("/ui/dialogs/{dialog_id}/turns/{turn_index}/ratings")
def ui_ratings(dialog_id: str, turn_index: int, body: Ratings):
    turn = workspace.patch_ratings(dialog_id, turn_index, _fields(body))
    if turn is None:
        raise HTTPException(404, detail="Ход не найден")
    return turn


@app.post("/query")
def query(body: Query):
    try:
        existed = workspace.prepare_dialog(body.dialog_id) is not None
        result = run(body.query, body.dialog_id)
        workspace.append_turn(body.dialog_id, body.query, result, create=not existed)
        return result
    except Exception as exc:
        raise HTTPException(500, detail=str(exc)) from exc
