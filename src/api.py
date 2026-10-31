"""HTTP-страница, загрузка файлов и вопрос к координатору.

Пока индекс строится, /ui отдаёт сохранённое дерево и не трогает Chroma.
Неудачная замена файла возвращает прежние байты.
"""
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import workspace
from coordinator import run
from ingest import SUFFIXES, _blocks, chunks_from_blocks, ingest_dir
from store import chunks_for_document, delete_document, list_documents, upsert_chunks

app = FastAPI()
INBOX = Path("data/inbox")
PAGE = Path(__file__).parent / "web" / "index.html"
ROOT = Path(__file__).resolve().parents[1]
LOAD_TIME = ROOT / "data" / "load_time.txt"
_state = {"started": None, "done": False}
# Upload reads the inbox and then indexes that snapshot. A delete or another
# ingest in between removes a document and the snapshot puts it back.
_upload_lock = threading.Lock()


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
        with _upload_lock:
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


def _on_disk():
    if not INBOX.is_dir():
        return set()
    return {
        path.name
        for path in INBOX.iterdir()
        if path.is_file() and path.suffix.lower() in SUFFIXES
    }


@app.get("/")
def page():
    """Отдать страницу интерфейса."""
    return FileResponse(PAGE, headers={"Cache-Control": "no-store"})


@app.get("/ready")
def ready():
    """200, когда модель и эмбеддинги на месте и индекс достроен."""
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
    """Имена документов в индексе."""
    return {"documents": list_documents()}


@app.get("/documents/{document_name:path}/preview")
def documents_preview(document_name: str):
    """Текст одного документа из индекса. Чужое имя не читает диск напрямую."""
    name = Path(document_name).name
    if name not in list_documents():
        raise HTTPException(404, detail="Документ не найден")
    return {"document_name": name, "chunks": chunks_for_document(name)}


@app.delete("/documents/{document_name:path}")
def documents_delete(document_name: str):
    """Удалить файл из inbox и индекса, не трогая диалоги."""
    name = Path(document_name).name
    with _upload_lock:
        delete_document(name)
        path = INBOX / name
        if path.is_file():
            path.unlink()
        known = list_documents()
        return {"documents": known, "tree": workspace.forget_file(name, known, _on_disk())}


@app.post("/documents")
def documents(body: Docs):
    """Переиндексировать только data/inbox."""
    folder = Path(body.directory).resolve()
    if folder != INBOX.resolve():
        raise HTTPException(400, detail="Загружать можно только папку data/inbox")
    with _upload_lock:
        upsert_chunks(ingest_dir(folder))
    return {"ok": True}


def _upload_name(filename):
    name = Path(str(filename or "")).name
    if name in ("", ".", ".."):
        raise HTTPException(400, detail="Некорректное имя файла")
    return name


def _upload_detail(name, previous, *, empty):
    reason = f"В файле {name} нет текста" if empty else f"Не удалось прочитать {name}"
    if previous is not None:
        return reason + ". Прежний файл сохранён"
    return reason


def _rollback_upload(saved):
    for path, previous in reversed(saved):
        try:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous)
        except OSError:
            continue


def _save_uploads(payloads):
    with _upload_lock:
        return _save_uploads_locked(payloads)


def _save_uploads_locked(payloads):
    saved = []
    try:
        INBOX.mkdir(parents=True, exist_ok=True)
        inbox = INBOX.resolve()
        for name, payload in payloads:
            path = INBOX / name
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise HTTPException(400, detail="Некорректное имя файла")
            if path.resolve().parent != inbox:
                raise HTTPException(400, detail="Некорректное имя файла")
            previous = path.read_bytes() if path.is_file() else None
            saved.append((path, previous))
            path.write_bytes(payload)
            try:
                extracted = chunks_from_blocks(_blocks(path), name)
            except ImportError:
                raise
            except Exception as exc:
                raise HTTPException(400, detail=_upload_detail(name, previous, empty=False)) from exc
            if not extracted:
                raise HTTPException(400, detail=_upload_detail(name, previous, empty=True))
        chunks = ingest_dir(INBOX)
    except Exception as exc:
        # Замена, которую не удалось проиндексировать, не должна оставлять новый файл вместо старого.
        _rollback_upload(saved)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, detail=str(exc)) from exc
    try:
        upsert_chunks(chunks)
        names = list_documents()
        return {"documents": names, "tree": workspace.snapshot(names, _on_disk())["tree"]}
    except Exception as exc:
        raise HTTPException(500, detail=str(exc)) from exc


@app.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    """Записать файлы в inbox и обновить индекс. Сбой пакета откатывает байты."""
    payloads = [(_upload_name(item.filename), await item.read()) for item in files]
    return _save_uploads(payloads)


@app.get("/ui")
def ui_get():
    """Снимок диалогов и дерева. До готовности индекса Chroma не вызывается."""
    if not _state["done"]:
        return workspace.load()
    return workspace.snapshot(list_documents(), _on_disk())


@app.put("/ui")
def ui_put(body: UiTree):
    """Сохранить дерево. Узел файла, который ещё на диске, остаётся в папке."""
    return workspace.put_tree(body.tree, list_documents(), _on_disk())


@app.post("/ui/dialogs")
def ui_dialog_create():
    """Новый пустой диалог."""
    return workspace.create_dialog()


@app.get("/ui/dialogs/{dialog_id}")
def ui_dialog_get(dialog_id: str):
    """Один диалог с ходами и оценками."""
    row = workspace.get_dialog_row(dialog_id)
    if row is None:
        raise HTTPException(404, detail="Диалог не найден")
    return row


@app.delete("/ui/dialogs/{dialog_id}")
def ui_dialog_delete(dialog_id: str):
    """Удалить диалог и забыть его ходы в памяти процесса."""
    return workspace.delete_dialog(dialog_id)


@app.patch("/ui/dialogs/{dialog_id}/turns/{turn_index}/ratings")
def ui_ratings(dialog_id: str, turn_index: int, body: Ratings):
    """Записать оценки 1–5. Число вне диапазона не сохраняется."""
    turn = workspace.patch_ratings(dialog_id, turn_index, _fields(body))
    if turn is None:
        raise HTTPException(404, detail="Ход не найден")
    return turn


@app.post("/query")
def query(body: Query):
    """Ответить на вопрос. Перед этим поднять ходы с диска, после — дописать ход."""
    try:
        existed = workspace.prepare_dialog(body.dialog_id) is not None
        result = run(body.query, body.dialog_id)
        workspace.append_turn(body.dialog_id, body.query, result, create=not existed)
        return result
    except Exception as exc:
        raise HTTPException(500, detail=str(exc)) from exc
