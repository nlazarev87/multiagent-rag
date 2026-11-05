"""Журнал только дописывается. Цепочка хешей пишется под одним замком."""

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone

import auth

_lock = threading.Lock()
_ready: set[str] = set()


def path():
    return auth.app_root() / "data" / "audit" / "log.sqlite"


def _connect(target=None):
    chosen = path() if target is None else target
    chosen.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(chosen, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prev_hash TEXT NOT NULL,
            row_hash TEXT NOT NULL,
            body TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS events_no_update
        BEFORE UPDATE ON events
        BEGIN
            SELECT RAISE(ABORT, 'audit');
        END;
        CREATE TRIGGER IF NOT EXISTS events_no_delete
        BEFORE DELETE ON events
        BEGIN
            SELECT RAISE(ABORT, 'audit');
        END;
        """
    )


def ensure(target=None):
    chosen = path() if target is None else target
    key = str(chosen)
    if key in _ready:
        return
    with _lock:
        if key in _ready:
            return
        conn = _connect(chosen)
        try:
            _schema(conn)
            conn.commit()
        finally:
            conn.close()
        _ready.add(key)


def _archive_rank(name):
    body = name.removesuffix(".sqlite")[4:]
    parts = body.split("-")
    if len(parts) >= 3 and parts[-1].isdigit() and len(parts[-1]) < 4:
        return ("-".join(parts[:-1]), int(parts[-1]))
    return (body, 1)


def _archives():
    return sorted(
        path().parent.glob("log-*.sqlite"), key=lambda item: _archive_rank(item.name), reverse=True
    )


def _files():
    current = path()
    found = [current] if current.exists() else []
    found.extend(_archives())
    return found


def list_files():
    """Имена файлов журнала: текущий и архивы (#223).

    Публичная обёртка над _files(). Иначе api.py импортирует приватное имя.
    """
    return [item.name for item in _files()]


def _named(file):
    name = str(file or "")
    if not name.endswith(".sqlite") or "/" in name or "\\" in name:
        return None
    return path().parent / name


def _threshold_bytes():
    from settings import runtime

    raw = runtime().get("audit", {}).get("rotation_threshold_mb", 100)
    return int(float(raw) * 1024 * 1024)


def _maybe_rotate():
    current = path()
    if not current.exists():
        return
    try:
        limit = _threshold_bytes()
    except (TypeError, ValueError):
        return
    if current.stat().st_size < limit:
        return
    with _lock:
        if not current.exists() or current.stat().st_size < limit:
            return
        conn = _connect(current)
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
        if current.stat().st_size < limit:
            return
        stamp = datetime.now().strftime("%Y-%m")
        folder = current.parent
        target = folder / f"log-{stamp}.sqlite"
        number = 2
        while target.exists():
            target = folder / f"log-{stamp}-{number}.sqlite"
            number += 1
        current.rename(target)
        for suffix in ("-wal", "-shm"):
            side = current.parent / (current.name + suffix)
            if side.exists():
                side.rename(target.parent / (target.name + suffix))
        _ready.discard(str(current))
    ensure()


def canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _stamp():
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(kind, user, payload, ok=True):
    _maybe_rotate()
    ensure()
    payload = payload or {}
    login = "" if user is None else user.get("login", "")
    if not login:
        login = str(payload.get("login") or "")
    body = {
        "kind": kind,
        "time": _stamp(),
        "ok": bool(ok),
        "user_id": "" if user is None else user.get("id", ""),
        "login": login,
        "role_id": "" if user is None else user.get("role_id", ""),
        "role": "" if user is None else user.get("role", ""),
        "groups": [] if user is None else sorted(auth.group_ids_for(user)),
        "payload": payload or {},
    }
    text = canonical(body)
    with _lock:
        conn = _connect()
        try:
            prev = conn.execute("SELECT row_hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
            prev_hash = prev["row_hash"] if prev else "0" * 64
            row_hash = hashlib.sha256((prev_hash + text).encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO events (prev_hash, row_hash, body) VALUES (?, ?, ?)",
                (prev_hash, row_hash, text),
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        finally:
            conn.close()


def verify(file=None):
    if file is None:
        ensure()
        target = path()
    else:
        target = _named(file)
        if target is None or not target.exists():
            return False
    conn = _connect(target)
    try:
        rows = conn.execute(
            "SELECT id, prev_hash, row_hash, body FROM events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    prev = "0" * 64
    for row in rows:
        if row["prev_hash"] != prev:
            return False
        digest = hashlib.sha256((row["prev_hash"] + row["body"]).encode("utf-8")).hexdigest()
        if digest != row["row_hash"]:
            return False
        prev = row["row_hash"]
    return True


def _load(row):
    body = json.loads(row["body"])
    body["id"] = row["id"]
    body["prev_hash"] = row["prev_hash"]
    body["row_hash"] = row["row_hash"]
    return body


def list_events(
    *,
    file=None,
    user_id="",
    role_id="",
    group_id="",
    kind="",
    after="",
    before="",
    before_id=0,
    limit=50,
):
    if file is None:
        ensure()
        target = path()
    else:
        target = _named(file)
        if target is None or not target.exists():
            return []
    conn = _connect(target)
    try:
        rows = conn.execute(
            "SELECT id, prev_hash, row_hash, body FROM events ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()
    try:
        cursor = int(before_id or 0)
    except (TypeError, ValueError):
        cursor = 0
    found = []
    for row in rows:
        body = _load(row)
        # Границы периода входят в выборку. Продолжение страницы передаёт ещё id
        # последней строки: иначе строки той же секунды пропадают.
        if before and body["time"] > before:
            continue
        if before and cursor and body["time"] == before and body["id"] >= cursor:
            continue
        if after and body["time"] < after:
            continue
        if user_id and body.get("user_id") != user_id:
            continue
        if role_id and body.get("role_id") != role_id:
            continue
        if group_id and group_id not in (body.get("groups") or []):
            continue
        if kind and body.get("kind") != kind:
            continue
        found.append(body)
        if len(found) >= limit:
            break
    return found


def _get_from(target, event_id):
    if not target.exists():
        return None
    conn = _connect(target)
    try:
        row = conn.execute(
            "SELECT id, prev_hash, row_hash, body FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else _load(row)


def get_event(event_id, file=None):
    """Вернуть одно событие по id.

    В каждом файле `log-*.sqlite` свой AUTOINCREMENT. Один и тот же id
    может быть и в текущем `log.sqlite`, и в архиве. Без `file` вернётся
    первое совпадение: текущий файл, потом свежие архивы.

    Нужную строку выбирает `file` из `list_events` или из query-параметра.
    См. #222, #223.
    """
    if file is not None:
        target = _named(file)
        return None if target is None else _get_from(target, event_id)
    ensure()
    for candidate in _files():
        found = _get_from(candidate, event_id)
        if found is not None:
            return found
    return None
