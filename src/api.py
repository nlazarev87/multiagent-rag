"""HTTP-страница, загрузка файлов и вопрос к координатору.

Пока индекс строится, /ui отдаёт сохранённое дерево и не трогает Chroma.
Неудачная замена файла возвращает прежние байты.
"""
import json
import os
import threading
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import access
import audit
import auth
import kb
import trees
import workspace
from coordinator import run
from ingest import SUFFIXES, _blocks, chunks_from_blocks, ingest_dir
from store import chunks_for_document, delete_document, list_documents, upsert_chunks

app = FastAPI()
INBOX = Path("data/inbox")
_PUBLIC = {("GET", "/"), ("GET", "/ready"), ("GET", "/auth/state"), ("POST", "/setup"), ("POST", "/login")}


@app.middleware("http")
async def _guard(request: Request, call_next):
    if not auth.origin_ok(request.headers.get("origin")):
        return JSONResponse({"detail": "Чужой источник"}, status_code=403)
    public = (request.method, request.url.path) in _PUBLIC
    token = None
    if not public:
        user = auth.user_from_request_cookie(request.cookies.get("session"))
        if user is None:
            return JSONResponse({"detail": "Нужен вход"}, status_code=401)
        request.state.user = user
        token = workspace.set_owner(user["id"])
    try:
        return await call_next(request)
    finally:
        if token is not None:
            workspace.reset_owner(token)
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
    from store import CHROMA, _embed
    saved = CHROMA
    try:
        _embed(["passage: готов"])
        kb.ensure_legacy()
        for row in kb.list_kbs():
            folder = row["inbox"]
            if not folder.is_dir():
                continue
            try:
                with _upload_lock:
                    if row["legacy"]:
                        upsert_chunks(ingest_dir(folder))
                    else:
                        from store import upsert_at
                        upsert_at(row["chroma"], ingest_dir(folder))
            except Exception:
                continue
    finally:
        import store
        store.CHROMA = saved
        store.reset()
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
    """200, когда модель ответа и числовая модель поиска на месте и индекс достроен."""
    from llm import loaded
    if (_state["done"] or loaded) and _files_ok():
        return {"ready": True}
    elapsed = 0 if _state["started"] is None else int(time.time() - _state["started"])
    return JSONResponse(
        status_code=503,
        content={"elapsed_sec": elapsed, "eta_sec": _eta(elapsed)},
    )


def _user(request: Request):
    return _actor(request)


def _rows(user):
    rows = []
    for item in kb.list_kbs():
        if not access.can_see(user, item["id"]):
            continue
        if item["id"] == kb.LEGACY_ID or item["legacy"]:
            names = list_documents()
        else:
            permit = access.issue_see(user, item["id"])
            if permit is None:
                continue
            try:
                from store import list_permit
                names = list_permit(permit)
            except PermissionError:
                continue
        for name in names:
            rows.append({"kb_id": item["id"], "kb_name": item["name"], "name": name})
    return rows


def _names(rows):
    return [row["name"] for row in rows]


def _actor(request):
    if request is None or not hasattr(request, "state"):
        return auth.user_by_id(os.environ.get("RAG_TEST_USER") or "")
    return request.state.user


@app.get("/auth/state")
def auth_state():
    return {"has_users": auth.count_users() > 0}


def _cookie(response, session_id):
    response.set_cookie("session", session_id, httponly=True, samesite="lax", max_age=auth.SESSION_HOURS * 3600, path="/")
    return response


class Login(BaseModel):
    login: str
    password: str


class PasswordChange(BaseModel):
    old: str = ""
    new: str
    user_id: str = ""


@app.post("/setup")
def setup(body: Login):
    try:
        session_id = auth.setup(body.login, body.password)
    except LookupError:
        raise HTTPException(404, detail="Учётные записи уже есть") from None
    except ValueError:
        raise HTTPException(400, detail="Логин или пароль не подходят") from None
    user = auth.user_by_session(session_id)
    kb.ensure_legacy()
    if user is not None:
        access.backfill_legacy(user["id"])
        _move_dialogs(user["id"])
    response = JSONResponse(_public_user(user))
    return _cookie(response, session_id)


def _move_dialogs(user_id):
    if auth.meta_get("dialogs_moved"):
        return
    source = workspace.PATH
    if source.is_file():
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        dialogs = data.get("dialogs") if isinstance(data, dict) else None
        target = auth.app_root() / "data" / "users" / user_id / "dialogs.json"
        if dialogs and not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"dialogs": dialogs, "tree": {"id": "root", "name": "", "children": []}}, ensure_ascii=False), encoding="utf-8")
    auth.meta_set("dialogs_moved", "1")


def _public_user(user):
    if user is None:
        return {}
    return {"id": user["id"], "login": user["login"], "role": user["role"], "role_id": user["role_id"], "actions": user.get("actions") or []}


@app.post("/login")
def login(body: Login):
    user, error = auth.authenticate(body.login, body.password)
    if error == "blocked":
        audit.write("login_fail", user, {"login": body.login}, ok=False)
        raise HTTPException(403, detail="Учётная запись заблокирована")
    if user is None:
        audit.write("login_fail", None, {"login": body.login}, ok=False)
        raise HTTPException(401, detail="Неверный логин или пароль")
    session_id = auth.open_session(user["id"])
    audit.write("login_ok", user, {})
    response = JSONResponse(_public_user(user))
    return _cookie(response, session_id)


@app.post("/logout")
def logout(request: Request):
    auth.drop_session(request.cookies.get("session") or "")
    audit.write("logout", _user(request), {})
    response = JSONResponse({"ok": True})
    response.delete_cookie("session", path="/")
    return response


@app.get("/me")
def me(request: Request):
    return _public_user(_user(request))


@app.post("/me/password")
def me_password(request: Request, body: PasswordChange):
    user = _user(request)
    try:
        if body.user_id and body.user_id != user["id"]:
            if not access.has_global(user, "manage_users"):
                raise HTTPException(403, detail="Нет права")
            auth.set_password(body.user_id, body.new)
            audit.write("password_set", user, {"user_id": body.user_id})
            audit.write("session_drop", user, {"user_id": body.user_id})
            return {"ok": True}
        auth.change_password(user["id"], body.old, body.new, request.cookies.get("session"))
    except PermissionError:
        raise HTTPException(400, detail="Прежний пароль не подошёл") from None
    except ValueError:
        raise HTTPException(400, detail="Пароль короче 8 знаков") from None
    audit.write("password_set", user, {"user_id": user["id"]})
    audit.write("session_drop", user, {"user_id": user["id"]})
    return {"ok": True}


@app.get("/upload-targets")
def upload_targets(request: Request):
    user = _user(request)
    rows = [row for row in kb.list_kbs() if access.can(user, row["id"], "upload")]
    return {
        "bases": [{"id": row["id"], "name": row["name"]} for row in rows],
        "create": access.has_global(user, "create_kb"),
    }


@app.get("/documents")
def documents_list(request: Request):
    """Имена документов, которые этому человеку можно смотреть."""
    return {"documents": _rows(_user(request))}


@app.get("/documents/{document_name:path}/preview")
def documents_preview_old(document_name: str):
    raise HTTPException(404, detail="Документ не найден")


@app.delete("/documents/{document_name:path}")
def documents_delete_old(document_name: str):
    raise HTTPException(404, detail="Документ не найден")


def _chunks(row, name, user):
    permit = access.issue_see(user, row["id"])
    if permit is None or not permit.confirm():
        return None
    if row["legacy"]:
        if name not in list_documents():
            return None
        return chunks_for_document(name)
    try:
        from store import chunks_permit
        return chunks_permit(permit, name)
    except PermissionError:
        return None


@app.get("/kb/{kb_id}/documents/{document_name:path}/preview")
def documents_preview(kb_id: str, document_name: str = None, request: Request = None):
    """Текст одного документа из индекса этой базы."""
    if document_name is None and request is None:
        document_name = kb_id
        kb_id = kb.LEGACY_ID
        request = type("Req", (), {"state": type("St", (), {"user": auth.user_by_id(os.environ.get("RAG_TEST_USER") or "")})()})()
    if not kb.is_uuid(kb_id):
        raise HTTPException(404, detail="Документ не найден")
    name = Path(document_name).name
    row = kb.get(kb_id)
    if row is None or not access.can_see(_user(request), kb_id):
        raise HTTPException(404, detail="Документ не найден")
    chunks = _chunks(row, name, _user(request))
    if not chunks:
        raise HTTPException(404, detail="Документ не найден")
    return {"document_name": name, "chunks": chunks}


@app.delete("/kb/{kb_id}/documents/{document_name:path}")
def documents_delete(kb_id: str, document_name: str = None, request: Request = None):
    """Удалить файл из папки базы и из её индекса, не трогая диалоги."""
    if document_name is None and request is None:
        document_name = kb_id
        kb_id = kb.LEGACY_ID
        request = type("Req", (), {"state": type("St", (), {"user": auth.user_by_id(os.environ.get("RAG_TEST_USER") or "")})()})()
    if not kb.is_uuid(kb_id):
        raise HTTPException(404, detail="Документ не найден")
    name = Path(document_name).name
    user = _user(request)
    row = kb.get(kb_id)
    if row is None or not access.can(user, kb_id, "delete"):
        raise HTTPException(404, detail="Документ не найден")
    with _upload_lock:
        folder = row["inbox"]
        path = folder / name
        if path.is_symlink() or (path.exists() and path.resolve().parent != folder.resolve()):
            raise HTTPException(404, detail="Документ не найден")
        if row["legacy"]:
            delete_document(name)
        else:
            from store import delete_at
            delete_at(row["chroma"], name)
        if path.is_file():
            path.unlink()
        audit.write("delete", user, {"kb_id": kb_id, "name": name})
        rows = _rows(user)
        if trees.separate():
            trees.drop_name(row, name)
            shown = _page_tree(user)
        else:
            shown = workspace.forget_file(name, _names(rows), _on_disk())
        return {"documents": rows, "tree": shown}


@app.post("/documents")
def documents(body: Docs, request: Request = None):
    """Переиндексировать только папку базы «Документы» из реестра, не путь с клиента."""
    user = _user(request)
    if not access.can(user, kb.LEGACY_ID, "upload"):
        raise HTTPException(403, detail="Нет права загружать")
    row = kb.get(kb.LEGACY_ID)
    if row is None:
        raise HTTPException(404, detail="База не найдена")
    folder = Path(row["inbox"]).resolve()
    if Path(body.directory).resolve() != folder:
        raise HTTPException(400, detail="Загружать можно только папку базы")
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


def _save_uploads(payloads, folder=None, chroma=None, legacy=True):
    with _upload_lock:
        return _save_uploads_locked(payloads, folder or INBOX, chroma, legacy)


def _save_uploads_locked(payloads, folder, chroma, legacy):
    saved = []
    try:
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        inbox = folder.resolve()
        for name, payload in payloads:
            path = folder / name
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
        chunks = ingest_dir(folder)
    except Exception as exc:
        _rollback_upload(saved)
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(500, detail="Не удалось записать файл") from exc
    try:
        if legacy:
            upsert_chunks(chunks)
        else:
            from store import upsert_at
            upsert_at(chroma, chunks)
        return {"documents": _rows(_user_upload), "tree": workspace.snapshot(_names(_rows(_user_upload)), _on_disk())["tree"]}
    except Exception as exc:
        raise HTTPException(500, detail="Не удалось записать файл") from exc


_user_upload = None


@app.post("/upload")
async def upload(request: Request = None, files: list[UploadFile] = File(None), kb_id: str = Form(""), new_name: str = Form("")):
    """Записать файлы в выбранную базу. Без id базы — отказ."""
    global _user_upload
    if isinstance(request, list):
        files = request
        request = None
    if not isinstance(kb_id, str):
        kb_id = ""
    if not isinstance(new_name, str):
        new_name = ""
    user = _actor(request)
    _user_upload = user
    target = kb_id
    created = False
    if new_name:
        if not access.has_global(user, "create_kb"):
            raise HTTPException(403, detail="Нет права создать базу")
        try:
            row = kb.create(new_name)
        except FileExistsError:
            raise HTTPException(400, detail="Такое имя уже есть") from None
        except ValueError:
            raise HTTPException(400, detail="Имя базы не подходит") from None
        auth.acl_add(row["id"], "user", user["id"], "allow")
        auth.set_user_content(user["id"], row["id"], list(auth.CONTENT_ACTIONS))
        audit.write("kb_create", user, {"kb_id": row["id"], "name": row["name"]})
        audit.write("access_allow", user, {"kb_id": row["id"], "subject": user["id"]})
        audit.write("personal_actions", user, {"kb_id": row["id"]})
        target = row["id"]
        created = True
    if not target:
        raise HTTPException(400, detail="Нужно выбрать базу")
    if not kb.is_uuid(target):
        raise HTTPException(404, detail="База не найдена")
    row = kb.get(target)
    if row is None or not access.can(user, target, "upload"):
        raise HTTPException(403, detail="Нет права загружать")
    payloads = [(_upload_name(item.filename), await item.read()) for item in files]
    saved = _save_uploads(payloads, row["inbox"], row["chroma"], row["legacy"])
    if not created:
        audit.write("upload", user, {"kb_id": target, "names": [name for name, _payload in payloads]})
    if trees.separate():
        saved["tree"] = _page_tree(user)
    return saved


def _visible_names(user):
    names = set(_names(_rows(user)))
    if access.can_see(user, kb.LEGACY_ID):
        names.update(_on_disk())
    return names


def _kb_file_names(row, user):
    if row["legacy"]:
        names = set(list_documents())
        names.update(_on_disk())
        return names
    permit = access.issue_see(user, row["id"])
    if permit is None:
        return set()
    try:
        from store import list_permit
        return set(list_permit(permit))
    except PermissionError:
        return set()


def _visible_rows(user):
    return [row for row in kb.list_kbs() if access.can_see(user, row["id"])]


def _compose(parts):
    if not parts:
        return trees.empty()
    if len(parts) == 1:
        return parts[0][1]
    root = trees.empty()
    for row, clean in parts:
        root["children"].append({
            "id": "kb-" + row["id"],
            "name": row["name"],
            "children": clean.get("children") or [],
        })
    return root


def _page_tree(user):
    """Дерево страницы: одна база как раньше, несколько — папка на каждую."""
    trees.migrate()
    parts = []
    for row in _visible_rows(user):
        names = _kb_file_names(row, user)
        stored = trees.read(trees.path_for(row))
        clean = workspace.ensure_files(workspace.sanitize_tree(stored, names), names)
        parts.append((row, clean))
    return _compose(parts)


def _stored_page_tree(user):
    """Сохранённые папки без чтения списка файлов."""
    trees.migrate()
    return _compose([(row, trees.read(trees.path_for(row))) for row in _visible_rows(user)])


def _same_tree(left, right):
    return json.dumps(left, sort_keys=True, ensure_ascii=False) == json.dumps(right, sort_keys=True, ensure_ascii=False)


def _split_flat(visible, node, user):
    owners = {}
    for row in visible:
        for name in _kb_file_names(row, user):
            owners.setdefault(name, row["id"])
    named = [name for name in workspace.iter_files(node) if name in owners]
    owner_ids = {owners[name] for name in named}
    rows = {row["id"]: row for row in visible}
    if len(owner_ids) == 1:
        return [(rows[next(iter(owner_ids))], node)]
    if not owner_ids:
        return []
    buckets = {row["id"]: [] for row in visible}
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if child.get("document_name"):
            kb_id = owners.get(child["document_name"])
            if kb_id:
                buckets[kb_id].append({"document_name": child["document_name"]})
            continue
        files = [item for item in child.get("children") or [] if isinstance(item, dict) and item.get("document_name")]
        used = {owners.get(item["document_name"]) for item in files if owners.get(item["document_name"])}
        if len(used) == 1:
            kb_id = next(iter(used))
            buckets[kb_id].append({
                "id": child.get("id") or "folder",
                "name": child.get("name") or "Папка",
                "children": [{"document_name": item["document_name"]} for item in files if owners.get(item["document_name"]) == kb_id],
            })
        else:
            for item in files:
                kb_id = owners.get(item["document_name"])
                if kb_id:
                    buckets[kb_id].append({"document_name": item["document_name"]})
    return [
        (rows[kb_id], {"id": "root", "name": "", "children": children})
        for kb_id, children in buckets.items()
        if children
    ]


def _store_page_tree(user, incoming):
    trees.migrate()
    node = incoming if isinstance(incoming, dict) else trees.empty()
    children = [child for child in (node.get("children") or []) if isinstance(child, dict)]
    wrapped = [child for child in children if str(child.get("id") or "").startswith("kb-")]
    visible = _visible_rows(user)
    targets = []
    if wrapped:
        for child in wrapped:
            row = kb.get(str(child.get("id"))[3:])
            if row is None or not access.can_see(user, row["id"]):
                continue
            targets.append((row, {"id": "root", "name": "", "children": child.get("children") or []}))
    elif len(visible) <= 1:
        if visible:
            targets.append((visible[0], node))
    else:
        targets.extend(_split_flat(visible, node, user))
    pending = []
    for row, tree in targets:
        names = _kb_file_names(row, user)
        known = set(names) | set(workspace.iter_files(trees.read(trees.path_for(row))))
        clean = workspace.sanitize_tree(tree, known)
        current = workspace.sanitize_tree(trees.read(trees.path_for(row)), known)
        if _same_tree(clean, current):
            continue
        if not access.can(user, row["id"], "arrange"):
            raise HTTPException(403, detail="Нет права раскладывать папки")
        pending.append((row, workspace.ensure_files(clean, names)))
    for row, clean in pending:
        trees.write(trees.path_for(row), clean)
    return [row["id"] for row, _clean in pending]


@app.get("/ui")
def ui_get(request: Request = None):
    """Снимок диалогов этого человека. До готовности индекса список файлов не читается."""
    user = _user(request)
    if trees.separate():
        data = workspace.load()
        data["tree"] = _stored_page_tree(user) if not _state["done"] else _page_tree(user)
        return data
    if not _state["done"]:
        return workspace.load()
    data = workspace.snapshot(_visible_names(user), _on_disk())
    data["tree"] = _filter_tree(data.get("tree"), set(_visible_names(user)))
    return data


def _filter_tree(node, allowed):
    if not isinstance(node, dict):
        return {"id": "root", "name": "", "children": []}
    children = []
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if child.get("document_name"):
            if child["document_name"] in allowed:
                children.append(child)
            continue
        copied = dict(child)
        copied["children"] = _filter_tree(child, allowed).get("children") or []
        children.append(copied)
    return {"id": node.get("id") or "root", "name": node.get("name") or "", "children": children}


@app.put("/ui")
def ui_put(body: UiTree, request: Request):
    """Сохранить дерево. Чужие имена не стираются и без права не двигаются."""
    user = _user(request)
    if trees.separate():
        try:
            changed = _store_page_tree(user, body.tree)
        except HTTPException as exc:
            if exc.status_code == 403:
                audit.write("tree", user, {}, ok=False)
            raise
        if changed:
            audit.write("tree", user, {"kb_ids": changed})
        data = workspace.load()
        data["tree"] = _page_tree(user)
        return data
    visible = set(_visible_names(user))
    current = workspace.load()
    stored = current.get("tree") or {"id": "root", "name": "", "children": []}
    if not access.can(user, kb.LEGACY_ID, "arrange"):
        audit.write("tree", user, {"kb_id": kb.LEGACY_ID}, ok=False)
        raise HTTPException(403, detail="Нет права раскладывать папки")
    merged = _merge_hidden(stored, body.tree, visible)
    known = list(visible)
    before = json.dumps(stored, sort_keys=True, ensure_ascii=False)
    saved = workspace.put_tree(merged, known, _on_disk())
    after = json.dumps(saved.get("tree") or {}, sort_keys=True, ensure_ascii=False)
    if before != after:
        audit.write("tree", user, {"kb_id": kb.LEGACY_ID})
    return saved


def _merge_hidden(stored, incoming, visible):
    hidden = [child for child in (stored.get("children") or []) if isinstance(child, dict) and child.get("document_name") and child["document_name"] not in visible]
    node = incoming if isinstance(incoming, dict) else {"id": "root", "name": "", "children": []}
    children = []
    for child in node.get("children") or []:
        if isinstance(child, dict) and child.get("document_name") and child["document_name"] not in visible:
            continue
        children.append(child)
    children.extend(hidden)
    return {"id": node.get("id") or "root", "name": node.get("name") or "", "children": children}


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
def query(body: Query, request: Request):
    """Ответить на вопрос. Базу выбирает проверка прав, не поле запроса."""
    user = _user(request)
    memory_key = f"{user['id']}:{body.dialog_id}"
    scope = access.build_scope(user)
    try:
        existed = workspace.prepare_dialog(body.dialog_id, memory_key=memory_key) is not None
        if not scope.kbs:
            result = {"answer": "В документах нет ответа.", "status": "нет ответа", "document_names": [], "sources": []}
        else:
            result = run(body.query, memory_key, scope)
        workspace.append_turn(body.dialog_id, body.query, result, create=not existed)
        audit.write("query", user, access.query_record(
            user, scope,
            query=body.query,
            answer=result.get("answer", ""),
            status=result.get("status", ""),
            dialog_id=body.dialog_id,
            sources=access.source_rows(result, getattr(scope, "found", None) or []),
            attempts=getattr(scope, "attempts", 0) or 0,
            feedback=getattr(scope, "feedback", "") or "",
        ))
        return result
    except Exception as exc:
        audit.write("query", user, access.query_record(
            user, scope,
            query=body.query,
            answer="",
            status="нет",
            dialog_id=body.dialog_id,
            sources=[],
            attempts=getattr(scope, "attempts", 0) or 0,
            feedback="",
            error=type(exc).__name__,
        ), ok=False)
        raise HTTPException(500, detail="Ошибка сервера") from exc


def _need(user, action):
    if not access.has_global(user, action):
        raise HTTPException(403, detail="Нет права")


class UserBody(BaseModel):
    login: str = ""
    password: str = ""
    role_id: str = ""
    blocked: bool | None = None


class RoleBody(BaseModel):
    name: str = ""
    actions: list[str] | None = None
    kb_actions: dict | None = None


class GroupBody(BaseModel):
    name: str = ""
    user_ids: list[str] | None = None
    role_ids: list[str] | None = None


class AclBody(BaseModel):
    subject_type: str
    subject_id: str


class ActionBody(BaseModel):
    actions: list[str] = []


class KbBody(BaseModel):
    name: str


@app.get("/admin/users")
def admin_users(request: Request):
    _need(_user(request), "manage_users")
    return {"users": auth.list_users()}


@app.post("/admin/users")
def admin_user_create(body: UserBody, request: Request):
    user = _user(request)
    _need(user, "manage_users")
    if not body.role_id:
        raise HTTPException(400, detail="Нужна роль")
    try:
        created = auth.create_user(body.login, body.password, body.role_id)
    except ValueError as exc:
        detail = "Такой логин уже есть" if exc.args == ("taken",) else "Логин или пароль не подходят"
        raise HTTPException(400, detail=detail) from None
    except LookupError:
        raise HTTPException(404, detail="Роль не найдена") from None
    audit.write("user_create", user, {"user_id": created["id"], "login": created["login"]})
    return created


@app.patch("/admin/users/{user_id}")
def admin_user_patch(user_id: str, body: UserBody, request: Request):
    user = _user(request)
    _need(user, "manage_users")
    if body.password:
        auth.set_password(user_id, body.password)
        audit.write("password_set", user, {"user_id": user_id})
        audit.write("session_drop", user, {"user_id": user_id})
    try:
        updated = auth.update_user(user_id, role_id=body.role_id or None, blocked=body.blocked)
    except PermissionError:
        raise HTTPException(400, detail="Нельзя оставить систему без управляющего") from None
    except LookupError:
        raise HTTPException(404, detail="Не найдено") from None
    if body.blocked is True:
        audit.write("user_block", user, {"user_id": user_id})
        audit.write("session_drop", user, {"user_id": user_id})
    elif body.blocked is False:
        audit.write("user_unblock", user, {"user_id": user_id})
    if body.role_id:
        audit.write("role_assign", user, {"user_id": user_id, "role_id": body.role_id})
    return updated


@app.delete("/admin/users/{user_id}")
def admin_user_delete(user_id: str, request: Request):
    user = _user(request)
    _need(user, "manage_users")
    try:
        auth.delete_user(user_id)
    except PermissionError:
        raise HTTPException(400, detail="Нельзя оставить систему без управляющего") from None
    audit.write("user_delete", user, {"user_id": user_id})
    return {"ok": True}


@app.get("/admin/roles")
def admin_roles(request: Request):
    _need(_user(request), "manage_roles")
    return {"roles": auth.list_roles(), "bases": [{"id": row["id"], "name": row["name"]} for row in kb.list_kbs()]}


@app.post("/admin/roles")
def admin_role_create(body: RoleBody, request: Request):
    user = _user(request)
    _need(user, "manage_roles")
    try:
        role_id = auth.create_role(body.name)
    except ValueError as exc:
        detail = "Такое имя уже есть" if exc.args == ("taken",) else "Нужно имя роли"
        raise HTTPException(400, detail=detail) from None
    audit.write("role_create", user, {"role_id": role_id, "name": body.name})
    return {"id": role_id}


@app.patch("/admin/roles/{role_id}")
def admin_role_patch(role_id: str, body: RoleBody, request: Request):
    user = _user(request)
    _need(user, "manage_roles")
    try:
        auth.update_role(role_id, name=body.name or None, actions=body.actions, kb_actions=body.kb_actions)
    except PermissionError:
        raise HTTPException(400, detail="Нельзя оставить систему без управляющего") from None
    except ValueError as exc:
        detail = "Такое имя уже есть" if exc.args == ("taken",) else "Нужно имя роли"
        raise HTTPException(400, detail=detail) from None
    audit.write("role_actions", user, {"role_id": role_id})
    return {"ok": True}


@app.delete("/admin/roles/{role_id}")
def admin_role_delete(role_id: str, request: Request):
    user = _user(request)
    _need(user, "manage_roles")
    try:
        auth.delete_role(role_id)
    except PermissionError:
        raise HTTPException(400, detail="Роль ещё назначена") from None
    audit.write("role_delete", user, {"role_id": role_id})
    return {"ok": True}


@app.get("/admin/groups")
def admin_groups(request: Request):
    _need(_user(request), "manage_groups")
    return {"groups": auth.list_groups()}


@app.post("/admin/groups")
def admin_group_create(body: GroupBody, request: Request):
    user = _user(request)
    _need(user, "manage_groups")
    try:
        group_id = auth.create_group(body.name)
    except ValueError as exc:
        detail = "Такое имя уже есть" if exc.args == ("taken",) else "Нужно имя группы"
        raise HTTPException(400, detail=detail) from None
    audit.write("group_create", user, {"group_id": group_id})
    return {"id": group_id}


@app.put("/admin/groups/{group_id}/members")
def admin_group_members(group_id: str, body: GroupBody, request: Request):
    user = _user(request)
    _need(user, "manage_groups")
    try:
        auth.set_group_members(group_id, body.user_ids or [], body.role_ids or [])
    except LookupError:
        raise HTTPException(404, detail="Группа не найдена") from None
    audit.write("group_members", user, {"group_id": group_id})
    return {"ok": True}


@app.delete("/admin/groups/{group_id}")
def admin_group_delete(group_id: str, request: Request):
    user = _user(request)
    _need(user, "manage_groups")
    auth.delete_group(group_id)
    audit.write("group_delete", user, {"group_id": group_id})
    return {"ok": True}


@app.get("/admin/kb")
def admin_kb(request: Request):
    user = _user(request)
    names = [{"id": row["id"], "name": row["name"]} for row in kb.list_kbs()]
    if access.has_global(user, "manage_access"):
        bases = []
        for row in kb.list_kbs():
            bases.append({
                "id": row["id"],
                "name": row["name"],
                "acl": auth.acl_rows(row["id"]),
                "role_actions": {
                    role["id"]: sorted(auth.role_content(role["id"], row["id"]))
                    for role in auth.list_roles()
                },
                "personal": {
                    person["id"]: sorted(auth.user_content(person["id"], row["id"]))
                    for person in auth.list_users()
                },
            })
        return {"bases": bases}
    if access.has_global(user, "manage_roles"):
        return {"bases": names}
    raise HTTPException(403, detail="Нет права")


@app.post("/admin/kb/{kb_id}/allow")
def admin_allow(kb_id: str, body: AclBody, request: Request):
    user = _user(request)
    _need(user, "manage_access")
    auth.acl_add(kb_id, body.subject_type, body.subject_id, "allow")
    audit.write("access_allow", user, {"kb_id": kb_id, "subject_type": body.subject_type, "subject_id": body.subject_id})
    return {"ok": True}


@app.delete("/admin/kb/{kb_id}/allow")
def admin_allow_delete(kb_id: str, body: AclBody, request: Request):
    user = _user(request)
    _need(user, "manage_access")
    auth.acl_remove(kb_id, body.subject_type, body.subject_id, "allow")
    audit.write("access_revoke", user, {"kb_id": kb_id, "subject_type": body.subject_type, "subject_id": body.subject_id})
    return {"ok": True}


@app.post("/admin/kb/{kb_id}/deny")
def admin_deny(kb_id: str, body: AclBody, request: Request):
    user = _user(request)
    _need(user, "manage_access")
    auth.acl_add(kb_id, body.subject_type, body.subject_id, "deny")
    audit.write("access_deny", user, {"kb_id": kb_id, "subject_type": body.subject_type, "subject_id": body.subject_id})
    return {"ok": True}


@app.delete("/admin/kb/{kb_id}/deny")
def admin_deny_delete(kb_id: str, body: AclBody, request: Request):
    user = _user(request)
    _need(user, "manage_access")
    auth.acl_remove(kb_id, body.subject_type, body.subject_id, "deny")
    audit.write("access_undeny", user, {"kb_id": kb_id, "subject_type": body.subject_type, "subject_id": body.subject_id})
    return {"ok": True}


@app.post("/admin/kb/{kb_id}/self")
def admin_self(kb_id: str, request: Request):
    user = _user(request)
    _need(user, "manage_access")
    try:
        changed = access.self_grant(user, kb_id)
    except PermissionError:
        raise HTTPException(400, detail="Роль или группа закрывает эту базу") from None
    except LookupError:
        raise HTTPException(404, detail="База не найдена") from None
    if changed:
        audit.write("access_allow", user, {"kb_id": kb_id, "subject_type": "user", "subject_id": user["id"]})
        audit.write("personal_actions", user, {"kb_id": kb_id, "actions": list(auth.CONTENT_ACTIONS)})
    return {"ok": True, "changed": changed}


@app.put("/admin/kb/{kb_id}/people/{user_id}/actions")
def admin_personal(kb_id: str, user_id: str, body: ActionBody, request: Request):
    user = _user(request)
    _need(user, "manage_access")
    auth.set_user_content(user_id, kb_id, body.actions)
    audit.write("personal_actions", user, {"kb_id": kb_id, "user_id": user_id, "actions": body.actions})
    return {"ok": True}


@app.post("/kb")
def kb_create(body: KbBody, request: Request):
    user = _user(request)
    _need(user, "create_kb")
    try:
        row = kb.create(body.name)
    except FileExistsError:
        raise HTTPException(400, detail="Такое имя уже есть") from None
    except ValueError:
        raise HTTPException(400, detail="Имя базы не подходит") from None
    auth.acl_add(row["id"], "user", user["id"], "allow")
    auth.set_user_content(user["id"], row["id"], list(auth.CONTENT_ACTIONS))
    audit.write("kb_create", user, {"kb_id": row["id"], "name": row["name"]})
    return {"id": row["id"], "name": row["name"]}


@app.get("/admin/audit")
def admin_audit(request: Request, user: str = "", role: str = "", group: str = "", kind: str = "", before: str = "", after: str = ""):
    actor = _user(request)
    _need(actor, "view_audit")
    rows = audit.list_events(user_id=user, role_id=role, group_id=group, kind=kind, before=before, after=after, limit=50)
    audit.write("audit_view", actor, {"user": user, "role": role, "group": group, "kind": kind})
    return {"events": rows}


@app.get("/admin/audit/{event_id}")
def admin_audit_one(event_id: int, request: Request):
    actor = _user(request)
    _need(actor, "view_audit")
    row = audit.get_event(event_id)
    if row is None:
        raise HTTPException(404, detail="Запись не найдена")
    audit.write("audit_view", actor, {"event_id": event_id})
    return row
