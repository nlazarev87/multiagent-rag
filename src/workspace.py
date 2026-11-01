"""Диалоги, оценки и дерево папок в data/ui/workspace.json.

Запись под замком: оценка не затирает ход, который параллельно дописывает ответ.
Файл, который индекс временно скрыл, остаётся в своей папке, пока он на диске.
"""
import contextvars
import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dialog import drop_dialog, set_dialog

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "ui" / "workspace.json"
TITLE = "Новый диалог"
# Sync routes run on a thread pool. Each read-modify-write of the workspace
# file holds this lock; otherwise a rating or a tree save drops the turn that
# an in-flight answer is about to write.
_lock = threading.RLock()
_before_write = None
_owner = contextvars.ContextVar("workspace_owner", default=None)
DEFAULT = PATH


def set_owner(user_id):
    return _owner.set(user_id)


def reset_owner(token):
    _owner.reset(token)


def _split():
    owner = _owner.get()
    try:
        redirected = PATH.resolve() != DEFAULT.resolve()
    except OSError:
        redirected = PATH != DEFAULT
    return bool(owner) and not redirected


def _dialog_file():
    owner = _owner.get()
    if _split():
        from auth import app_root
        return app_root() / "data" / "users" / owner / "dialogs.json"
    return PATH


def _tree_file():
    return PATH


def blank_ratings():
    return {
        "answer_complete": None,
        "answer_correct": None,
        "links": {},
        "documents": {},
    }


def empty():
    return {"dialogs": [], "tree": {"id": "root", "name": "", "children": []}}


def _load_file(path):
    if not path.is_file():
        return empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return empty()
    if not isinstance(data, dict):
        return empty()
    dialogs = data.get("dialogs")
    tree = data.get("tree")
    if not isinstance(dialogs, list):
        dialogs = []
    if not isinstance(tree, dict):
        tree = {"id": "root", "name": "", "children": []}
    return {"dialogs": dialogs, "tree": tree}


def _dump(path, data):
    hook = _before_write
    if hook is not None and path == PATH:
        hook(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _read():
    if not _split():
        return _load_file(PATH)
    dialogs = _load_file(_dialog_file())["dialogs"]
    tree = _load_file(_tree_file())["tree"]
    return {"dialogs": dialogs, "tree": tree}


def _write(data):
    if not _split():
        _dump(PATH, data)
        return
    _dump(_dialog_file(), {"dialogs": data.get("dialogs") or [], "tree": {"id": "root", "name": "", "children": []}})
    stored = _load_file(_tree_file())
    stored["tree"] = data.get("tree") or stored["tree"]
    _dump(_tree_file(), stored)


def load():
    with _lock:
        return _read()


def save(data):
    with _lock:
        _write(data)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _title(text):
    line = " ".join(str(text or "").split())
    if not line:
        return TITLE
    if len(line) > 60:
        return line[:60].rstrip() + "…"
    return line


def _names(turn):
    names = []
    for name in turn.get("document_names") or []:
        if name and name not in names:
            names.append(name)
    if names:
        return names
    for source in turn.get("sources") or []:
        name = source.get("document_name")
        if name and name not in names:
            names.append(name)
    return names


def _turns(turns):
    rows = []
    for turn in turns[-20:]:
        rows.append({
            "query": turn.get("query", ""),
            "answer": turn.get("answer", ""),
            "document_names": _names(turn),
        })
    return rows


def score(value):
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= number <= 5:
        return number
    return None


def iter_files(node):
    names = []
    if not isinstance(node, dict):
        return names
    name = node.get("document_name")
    if name:
        names.append(Path(str(name)).name)
    for child in node.get("children") or []:
        names.extend(iter_files(child))
    return names


def sanitize_tree(node, known, seen=None):
    seen = seen if seen is not None else set()
    if not isinstance(node, dict):
        return {"id": "root", "name": "", "children": []}
    children = []
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if "document_name" in child:
            name = Path(str(child.get("document_name") or "")).name
            if name in known:
                children.append({"document_name": name})
            continue
        folder_id = str(child.get("id") or uuid.uuid4())
        if folder_id in seen:
            continue
        seen.add(folder_id)
        nested = sanitize_tree(child, known, seen)
        nested["id"] = folder_id
        nested["name"] = str(child.get("name") or "Папка")[:80] or "Папка"
        children.append(nested)
    node_id = str(node.get("id") or "root")
    return {"id": node_id, "name": str(node.get("name") or ""), "children": children}


def drop_file(node, name):
    if not isinstance(node, dict):
        return {"id": "root", "name": "", "children": []}
    kept = []
    for child in node.get("children") or []:
        if not isinstance(child, dict):
            continue
        if child.get("document_name") == name:
            continue
        if "document_name" in child:
            kept.append(child)
            continue
        kept.append(drop_file(child, name))
    node = dict(node)
    node["children"] = kept
    return node


def ensure_files(tree, names):
    have = set(iter_files(tree))
    children = list(tree.get("children") or [])
    for name in names:
        if name not in have:
            children.append({"document_name": name})
            have.add(name)
    tree = dict(tree)
    tree["children"] = children
    return tree


def _catalog(tree, known, keep):
    # A reindex deletes a document from the search catalog before it is added
    # back. The file is still in the inbox. Dropping it here pulls it out of
    # its folder; the next refresh can only put it back at the root.
    names = set(known or [])
    if keep:
        names.update(set(iter_files(tree)) & set(keep))
    return names


def snapshot(known=None, keep=None):
    """Дерево и диалоги для страницы. keep удерживает файл, который ещё лежит в inbox."""
    with _lock:
        data = _read()
        names = list(known or [])
        data["tree"] = ensure_files(sanitize_tree(data["tree"], _catalog(data["tree"], names, keep)), names)
        if not data["dialogs"]:
            data["dialogs"].append(_blank())
            _write(data)
        return data


def _blank():
    return {
        "id": str(uuid.uuid4()),
        "title": TITLE,
        "updated_at": _now(),
        "turns": [],
    }


def _find(data, dialog_id):
    for index, row in enumerate(data["dialogs"]):
        if isinstance(row, dict) and row.get("id") == dialog_id:
            return index, row
    return -1, None


def create_dialog():
    with _lock:
        data = _read()
        row = _blank()
        data["dialogs"].insert(0, row)
        _write(data)
    set_dialog(row["id"], [])
    return row


def delete_dialog(dialog_id):
    with _lock:
        data = _read()
        data["dialogs"] = [row for row in data["dialogs"] if not (isinstance(row, dict) and row.get("id") == dialog_id)]
        if not data["dialogs"]:
            data["dialogs"].append(_blank())
        _write(data)
    drop_dialog(dialog_id)
    return data


def get_dialog_row(dialog_id):
    with _lock:
        data = _read()
        _, row = _find(data, dialog_id)
        if row is None:
            return None
        turns = row.get("turns") or []
    set_dialog(row["id"], turns)
    return row


def prepare_dialog(dialog_id, *, memory_key=None):
    """Поднять ходы в память процесса. Новый диалог здесь не создаётся."""
    dialog_id = str(dialog_id)
    with _lock:
        data = _read()
        _, row = _find(data, dialog_id)
        turns = [] if row is None else (row.get("turns") or [])
    set_dialog(memory_key or dialog_id, turns)
    return row


def put_tree(tree, known, keep=None):
    """Проверить присланное дерево и записать его, не теряя диалоги."""
    with _lock:
        data = _read()
        names = list(known or [])
        data["tree"] = ensure_files(sanitize_tree(tree, _catalog(tree, names, keep)), names)
        _write(data)
        return data


def forget_file(name, known, keep=None):
    """Убрать файл из дерева и оставить диалоги."""
    with _lock:
        data = _read()
        data["tree"] = drop_file(data["tree"], name)
        _write(data)
        names = list(known or [])
        shown = ensure_files(sanitize_tree(data["tree"], _catalog(data["tree"], names, keep)), names)
        if not data["dialogs"]:
            data["dialogs"].append(_blank())
            data["tree"] = shown
            _write(data)
        return shown


def append_turn(dialog_id, query, result, *, create=True):
    """Дописать ход. create=False не возрождает диалог, удалённый пока шёл ответ."""
    with _lock:
        data = _read()
        index, row = _find(data, dialog_id)
        if row is None:
            if not create:
                return None
            row = _blank()
            row["id"] = dialog_id
            data["dialogs"].insert(0, row)
            index = 0
        turns = list(row.get("turns") or [])
        sources = result.get("sources") or []
        names = result.get("document_names") or _names({"sources": sources})
        places = []
        seen = set()
        for item in list(sources) + list(result.get("places") or []):
            if not isinstance(item, dict):
                continue
            base = item.get("kb_id") or ""
            name = item.get("document_name") or ""
            if base and name and (base, name) not in seen:
                places.append({"kb_id": base, "document_name": name})
                seen.add((base, name))
        turn = {
            "query": query,
            "answer": result.get("answer", ""),
            "sources": sources,
            "document_names": names,
            "ratings": blank_ratings(),
        }
        if places:
            turn["places"] = places
        turns.append(turn)
        row = dict(row)
        row["turns"] = turns
        if row.get("title") in (None, "", TITLE):
            row["title"] = _title(query)
        row["updated_at"] = _now()
        data["dialogs"][index] = row
        data["dialogs"].sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        _write(data)
        return row


def patch_ratings(dialog_id, turn_index, body):
    """Обновить оценки хода. Пустое поле не стирает уже стоящую оценку."""
    with _lock:
        data = _read()
        _, row = _find(data, dialog_id)
        if row is None:
            return None
        turns = list(row.get("turns") or [])
        if turn_index < 0 or turn_index >= len(turns):
            return None
        turn = dict(turns[turn_index])
        ratings = dict(turn.get("ratings") or blank_ratings())
        if "answer_complete" in body:
            ratings["answer_complete"] = score(body.get("answer_complete"))
        if "answer_correct" in body:
            ratings["answer_correct"] = score(body.get("answer_correct"))
        if "links" in body and isinstance(body.get("links"), dict):
            links = dict(ratings.get("links") or {})
            for key, value in body["links"].items():
                links[str(key)] = score(value)
            ratings["links"] = links
        if "documents" in body and isinstance(body.get("documents"), dict):
            documents = dict(ratings.get("documents") or {})
            for key, value in body["documents"].items():
                documents[Path(str(key)).name] = score(value)
            ratings["documents"] = documents
        turn["ratings"] = ratings
        turns[turn_index] = turn
        row["turns"] = turns
        _write(data)
        return turn
