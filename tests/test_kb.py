from pathlib import Path

import kb


def _root(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ROOT", str(tmp_path / "root"))
    monkeypatch.delenv("RAG_TEST_USER", raising=False)


def test_legacy_base_is_created_once(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    kb.ensure_legacy()
    kb.ensure_legacy()
    rows = kb.list_kbs()
    assert [row["name"] for row in rows] == ["Документы"]
    assert rows[0]["id"] == kb.LEGACY_ID


def test_new_base_stays_inside_its_directory(tmp_path, monkeypatch):
    _root(tmp_path, monkeypatch)
    row = kb.create("Кадры")
    assert row["inbox"].is_dir()
    assert Path(tmp_path / "root" / "data" / "kbs") in row["inbox"].parents
    try:
        kb.create("Кадры")
    except FileExistsError:
        pass
    else:
        raise AssertionError("duplicate name")
    try:
        kb.create("a/b")
    except ValueError:
        pass
    else:
        raise AssertionError("slash")
