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
