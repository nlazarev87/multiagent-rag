import sqlite3
import threading

import audit


def _root(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ROOT", str(tmp_path / "root"))
    monkeypatch.delenv("RAG_TEST_USER", raising=False)


def test_chain_detects_a_changed_row(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    user = {"id": "u", "login": "ann", "role_id": "r", "role": "Роль"}
    audit.write("login_ok", user, {})
    audit.write("logout", user, {})
    assert audit.verify()
    conn = sqlite3.connect(audit.path())
    try:
        conn.execute("UPDATE events SET body = '{}' WHERE id = 1")
        conn.commit()
        changed = False
    except sqlite3.IntegrityError:
        changed = True
    finally:
        conn.close()
    assert changed
    assert audit.verify()


def test_parallel_writes_do_not_share_a_previous_hash(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    user = {"id": "u", "login": "ann", "role_id": "r", "role": "Роль"}
    errors = []

    def worker():
        try:
            for _ in range(8):
                audit.write("upload", user, {"n": 1})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert audit.verify()
    conn = sqlite3.connect(audit.path())
    hashes = [row[0] for row in conn.execute("SELECT prev_hash FROM events ORDER BY id")]
    conn.close()
    assert len(hashes) == len(set(hashes))


def test_deleted_user_does_not_remove_the_event_or_store_a_password(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    user = {"id": "u", "login": "ann", "role_id": "r", "role": "Роль"}
    audit.write("login_fail", None, {"login": "ann"})
    text = audit.path().read_bytes()
    assert b"password" not in text.lower()
    rows = audit.list_events(user_id="")
    assert rows
    assert audit.get_event(rows[0]["id"])["kind"] == "login_fail"
    assert rows[0]["login"] == "ann"


def test_changed_row_breaks_the_chain(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    audit.write("login_ok", {"id": "u", "login": "ann", "role_id": "r", "role": "Роль"}, {})
    conn = sqlite3.connect(audit.path())
    try:
        conn.execute("DROP TRIGGER events_no_update")
        conn.execute("UPDATE events SET body = '{}' WHERE id = 1")
        conn.commit()
    finally:
        conn.close()
    assert audit.verify() is False


def test_deleted_person_leaves_the_login(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    import auth
    from fastapi.testclient import TestClient
    from api import app
    client = TestClient(app)
    client.post("/setup", json={"login": "admin", "password": "password12"})
    role_id = auth.user_by_login("admin")["role_id"]
    created = auth.create_user("ann", "password12", role_id)
    audit.write("login_ok", created, {})
    auth.delete_user(created["id"])
    rows = [row for row in audit.list_events() if row["kind"] == "login_ok" and row["login"] == "ann"]
    assert rows
    assert b"password12" not in audit.path().read_bytes()


def test_old_role_filter_uses_the_snapshot(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    import auth
    from fastapi.testclient import TestClient
    from api import app
    client = TestClient(app)
    client.post("/setup", json={"login": "admin", "password": "password12"})
    old = auth.create_role("Старая")
    person = auth.create_user("ann", "password12", old)
    audit.write("upload", person, {"name": "a.txt"})
    new = auth.create_role("Новая")
    auth.update_user(person["id"], role_id=new)
    found = audit.list_events(role_id=old, kind="upload")
    assert any(row["login"] == "ann" for row in found)
    guest = auth.create_role("Гость")
    auth.create_user("guest", "password12", guest)
    bare = TestClient(app)
    bare.post("/login", json={"login": "guest", "password": "password12"})
    assert bare.get("/admin/audit").status_code == 403


def test_same_second_continues_and_the_period_includes_its_edges(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    user = {"id": "u", "login": "ann", "role_id": "r", "role": "Роль"}
    monkeypatch.setattr(audit, "_stamp", lambda: "2026-11-02T00:00:01Z")
    for number in range(3):
        audit.write("upload", user, {"n": number})
    page = audit.list_events(limit=2)
    assert [row["id"] for row in page] == [3, 2]
    rest = audit.list_events(before=page[-1]["time"], before_id=page[-1]["id"], limit=2)
    assert [row["id"] for row in rest] == [1]
    assert len(audit.list_events(after="2026-11-02T00:00:01Z")) == 3
    assert len(audit.list_events(before="2026-11-02T00:00:01Z")) == 3
    assert audit.list_events(after="2026-11-02T00:00:02Z") == []
    assert audit.list_events(before="2026-11-02T00:00:00Z") == []
