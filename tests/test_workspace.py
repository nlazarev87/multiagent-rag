import threading
from pathlib import Path

import pytest

import dialog
import workspace


def _answer(text):
    return {"answer": text, "sources": [], "document_names": []}


def _freeze_clock(monkeypatch):
    clock = {"n": 0}

    def now():
        clock["n"] += 1
        return f"2020-01-01T00:00:{clock['n']:02d}+00:00"

    monkeypatch.setattr(workspace, "_now", now)


def _run_beside_append(monkeypatch, dialog_id, other):
    entered = threading.Event()
    release = threading.Event()
    state = {"stalled": False}

    def stall(_data):
        if state["stalled"]:
            return
        state["stalled"] = True
        entered.set()
        release.wait(5)

    monkeypatch.setattr(workspace, "_before_write", stall)
    errors = []

    def add_turn():
        try:
            workspace.append_turn(dialog_id, "второй", _answer("новый"))
        except Exception as exc:
            errors.append(exc)

    def side():
        try:
            other()
        except Exception as exc:
            errors.append(exc)

    writer = threading.Thread(target=add_turn)
    extra = threading.Thread(target=side)
    writer.start()
    started = False
    try:
        assert entered.wait(5)
        extra.start()
        started = True
        extra.join(0.5)
        assert extra.is_alive()
    finally:
        release.set()
    writer.join(5)
    if started:
        extra.join(5)
    assert errors == []
    assert not writer.is_alive()
    assert not extra.is_alive()


def test_overlapping_rating_keeps_the_new_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    dialog_id = row["id"]
    workspace.append_turn(dialog_id, "первый", _answer("старый"))
    _run_beside_append(monkeypatch, dialog_id, lambda: workspace.patch_ratings(dialog_id, 0, {"answer_complete": 5}))
    saved = next(item for item in workspace.load()["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in saved["turns"]] == ["первый", "второй"]
    assert saved["turns"][0]["ratings"]["answer_complete"] == 5
    assert saved["turns"][1]["answer"] == "новый"


def test_forget_file_keeps_the_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [
            {"id": "folder", "name": "Папка", "children": [{"document_name": "gone.txt"}]},
            {"document_name": "note.txt"},
        ],
    }, ["note.txt", "gone.txt"])
    workspace.forget_file("gone.txt", ["note.txt"])
    saved = workspace.load()
    assert saved["dialogs"][0]["id"] == row["id"]
    assert saved["dialogs"][0]["turns"][0]["answer"] == "ответ"
    names = workspace.iter_files(saved["tree"])
    assert names == ["note.txt"]
    assert saved["tree"]["children"][0]["name"] == "Папка"


def test_append_does_not_recreate_a_deleted_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.delete_dialog(row["id"])
    assert workspace.append_turn(row["id"], "вопрос", _answer("ответ"), create=False) is None
    assert all(item["id"] != row["id"] for item in workspace.load()["dialogs"])
    assert dialog.get_dialog(row["id"]) == []


def test_overlapping_tree_save_keeps_the_new_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    dialog_id = row["id"]
    workspace.append_turn(dialog_id, "первый", _answer("старый"))

    def save_tree():
        workspace.put_tree({
            "id": "root",
            "name": "",
            "children": [
                {"id": "folder", "name": "Архив", "children": [{"document_name": "note.txt"}]},
            ],
        }, ["note.txt"])

    _run_beside_append(monkeypatch, dialog_id, save_tree)
    data = workspace.load()
    saved = next(item for item in data["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in saved["turns"]] == ["первый", "второй"]
    assert saved["turns"][1]["answer"] == "новый"
    assert data["tree"]["children"] == [
        {"id": "folder", "name": "Архив", "children": [{"document_name": "note.txt"}]},
    ]


def test_failed_write_keeps_the_saved_workspace(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    dialog.reset()
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    original = path.read_text(encoding="utf-8")
    real = Path.write_text

    def boom(self, *args, **kwargs):
        if self.name.startswith(".workspace.json."):
            raise OSError("disk")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", boom)
    with pytest.raises(OSError):
        workspace.append_turn(row["id"], "ещё", _answer("потеря"))
    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".workspace.json.*.tmp")) == []
    saved = workspace.load()["dialogs"]
    assert [item["id"] for item in saved] == [row["id"]]
    assert [turn["query"] for turn in saved[0]["turns"]] == ["вопрос"]


def test_load_keeps_a_broken_file_until_the_next_save(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    path.write_text("{", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    assert path.read_text(encoding="utf-8") == "{"
    path.write_text("[]", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    assert path.read_text(encoding="utf-8") == "[]"
    raw = '{"dialogs": {"id": "x"}, "tree": []}'
    path.write_text(raw, encoding="utf-8")
    loaded = workspace.load()
    assert loaded["dialogs"] == []
    assert loaded["tree"] == {"id": "root", "name": "", "children": []}
    assert path.read_text(encoding="utf-8") == raw
    row = workspace.create_dialog()
    saved = workspace.load()
    assert saved["dialogs"][0]["id"] == row["id"]
    assert saved["tree"]["id"] == "root"


def test_prepare_dialog_restores_saved_scope_without_creating_a_row(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    data = workspace.load()
    data["dialogs"][0]["turns"] = [{
        "query": "где насос",
        "answer": "в цехе",
        "sources": [
            {"document_name": "pump.md"},
            {"document_name": "pump.md"},
            {"document_name": "note.txt"},
        ],
    }]
    workspace.save(data)
    dialog.add_turn(row["id"], {"query": "устарело", "answer": "x", "document_names": ["other.md"]})
    found = workspace.prepare_dialog(row["id"])
    assert found["id"] == row["id"]
    assert dialog.get_dialog(row["id"]) == [{
        "query": "где насос",
        "answer": "в цехе",
        "document_names": ["pump.md", "note.txt"],
    }]
    dialog.add_turn("missing", {"query": "устарело", "answer": "x", "document_names": ["other.md"]})
    assert workspace.prepare_dialog("missing") is None
    assert dialog.get_dialog("missing") == []
    assert all(item["id"] != "missing" for item in workspace.load()["dialogs"])


def test_append_turn_names_sources_and_keeps_the_title(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    _freeze_clock(monkeypatch)
    first = workspace.create_dialog()
    second = workspace.create_dialog()
    saved = workspace.append_turn(first["id"], "а" * 61, {
        "answer": "6 бар",
        "document_names": [],
        "sources": [
            {"document_name": "pump.md"},
            {"document_name": "pump.md"},
            {"document_name": ""},
            {"document_name": "note.txt"},
        ],
    })
    assert saved["title"] == ("а" * 60) + "…"
    assert saved["turns"][0]["document_names"] == ["pump.md", "note.txt"]
    again = workspace.append_turn(first["id"], "другой вопрос", _answer("дальше"))
    assert again["title"] == ("а" * 60) + "…"
    assert [item["id"] for item in workspace.load()["dialogs"]][0] == first["id"]
    blank = workspace.append_turn(second["id"], "   ", _answer("пусто"))
    assert blank["title"] == workspace.TITLE
    assert [item["id"] for item in workspace.load()["dialogs"]][0] == second["id"]


def test_sanitize_tree_stops_on_a_repeated_folder_and_strips_paths():
    tree = workspace.sanitize_tree({
        "id": "root",
        "name": "",
        "children": [
            {
                "id": "loop",
                "name": "",
                "children": [
                    {"id": "loop", "name": "снова", "children": [{"document_name": "note.txt"}]},
                    {"document_name": "sub/note.txt"},
                    {"document_name": "../secret.txt"},
                    "nope",
                ],
            },
            {"id": "long", "name": "П" * 90, "children": []},
        ],
    }, {"note.txt"})
    assert tree == {
        "id": "root",
        "name": "",
        "children": [
            {"id": "loop", "name": "Папка", "children": [{"document_name": "note.txt"}]},
            {"id": "long", "name": "П" * 80, "children": []},
        ],
    }


def test_patch_ratings_merges_and_rejects_out_of_range(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", {
        "answer": "ответ",
        "sources": [{"number": 1, "document_name": "note.txt"}],
        "document_names": ["note.txt"],
    })
    assert workspace.patch_ratings(row["id"], 0, {"answer_complete": 4})["ratings"]["answer_complete"] == 4
    workspace.patch_ratings(row["id"], 0, {"answer_correct": "5"})
    workspace.patch_ratings(row["id"], 0, {"links": {"1": 3}})
    workspace.patch_ratings(row["id"], 0, {"links": {"2": "4", "3": "нет"}})
    workspace.patch_ratings(row["id"], 0, {"documents": {"note.txt": 2}})
    workspace.patch_ratings(row["id"], 0, {"documents": {"../../note.txt": 1, "other.txt": 6}})
    workspace.patch_ratings(row["id"], 0, {"answer_complete": 0})
    assert workspace.patch_ratings(row["id"], -1, {"answer_correct": 1}) is None
    assert workspace.patch_ratings(row["id"], 3, {"answer_correct": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_correct": 1}) is None
    ratings = workspace.load()["dialogs"][0]["turns"][0]["ratings"]
    assert ratings == {
        "answer_complete": None,
        "answer_correct": 5,
        "links": {"1": 3, "2": 4, "3": None},
        "documents": {"note.txt": 1, "other.txt": None},
    }
