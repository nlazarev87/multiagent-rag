"""Папки одной базы лежат в её tree.json, рядом с папкой файлов."""
import json
import threading
import uuid
from pathlib import Path

import auth
import kb
import workspace

_lock = threading.RLock()


def separate():
    """Тесты, которые подменяют только файл диалогов, дерево не переносят."""
    try:
        return workspace.PATH.resolve() == workspace.DEFAULT.resolve()
    except OSError:
        return workspace.PATH == workspace.DEFAULT


def path_for(row):
    return Path(row["inbox"]).parent / "tree.json"


def empty():
    return {"id": "root", "name": "", "children": []}


def read(path):
    if not Path(path).is_file():
        return empty()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return empty()
    tree = data.get("tree") if isinstance(data, dict) else None
    return tree if isinstance(tree, dict) else empty()


def write(path, tree):
    path = Path(path)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(json.dumps({"tree": tree}, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise


def migrate():
    """Один раз перенести дерево «Документы» из workspace.json. Повтор файл не затирает."""
    if auth.meta_get("tree_moved"):
        return
    row = kb.get(kb.LEGACY_ID)
    if row is None:
        return
    target = path_for(row)
    if not target.exists():
        source = workspace.PATH
        tree = empty()
        if source.is_file():
            try:
                data = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                data = {}
            stored = data.get("tree") if isinstance(data, dict) else None
            if isinstance(stored, dict):
                tree = stored
        write(target, tree)
    auth.meta_set("tree_moved", "1")


def drop_name(row, name):
    target = path_for(row)
    tree = workspace.drop_file(read(target), name)
    write(target, tree)
    return tree
