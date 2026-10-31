import threading
from pathlib import Path

import pytest

import dialog
import workspace


def _answer(text):
    return {"answer": text, "sources": [], "document_names": []}


def test_overlapping_rating_keeps_the_new_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    dialog_id = row["id"]
    workspace.append_turn(dialog_id, "первый", _answer("старый"))
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

    def rate():
        try:
            workspace.patch_ratings(dialog_id, 0, {"answer_complete": 5})
        except Exception as exc:
            errors.append(exc)

    writer = threading.Thread(target=add_turn)
    rater = threading.Thread(target=rate)
    writer.start()
    started = False
    try:
        assert entered.wait(5)
        rater.start()
        started = True
        rater.join(0.5)
        assert rater.is_alive()
    finally:
        release.set()
    writer.join(5)
    if started:
        rater.join(5)
    assert errors == []
    assert not writer.is_alive()
    assert not rater.is_alive()
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


def test_overlapping_tree_save_keeps_the_new_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    dialog_id = row["id"]
    workspace.append_turn(dialog_id, "первый", _answer("старый"))
    workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [{"document_name": "note.txt"}],
    }, ["note.txt"])
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

    def save_tree():
        try:
            workspace.put_tree({
                "id": "root",
                "name": "",
                "children": [
                    {"id": "folder", "name": "Папка", "children": [{"document_name": "note.txt"}]},
                ],
            }, ["note.txt"])
        except Exception as exc:
            errors.append(exc)

    writer = threading.Thread(target=add_turn)
    saver = threading.Thread(target=save_tree)
    writer.start()
    started = False
    try:
        assert entered.wait(5)
        saver.start()
        started = True
        saver.join(0.5)
        assert saver.is_alive()
    finally:
        release.set()
    writer.join(5)
    if started:
        saver.join(5)
    assert errors == []
    assert not writer.is_alive()
    assert not saver.is_alive()
    data = workspace.load()
    saved = next(item for item in data["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in saved["turns"]] == ["первый", "второй"]
    assert saved["turns"][1]["answer"] == "новый"
    assert workspace.iter_files(data["tree"]) == ["note.txt"]
    assert data["tree"]["children"][0]["name"] == "Папка"


def test_failed_replace_keeps_the_saved_dialog(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    original = path.read_text(encoding="utf-8")
    real_replace = Path.replace

    def fail_temp(self, target):
        if self.name.startswith(".workspace.json.") and self.name.endswith(".tmp"):
            raise OSError("disk full")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_temp)
    with pytest.raises(OSError, match="disk full"):
        workspace.append_turn(row["id"], "второй", _answer("потеря"))
    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".workspace.json.*.tmp")) == []
    saved = workspace.load()["dialogs"]
    assert [turn["query"] for turn in saved[0]["turns"]] == ["вопрос"]
    assert saved[0]["turns"][0]["answer"] == "ответ"


def test_ratings_keep_partial_updates_and_reject_bad_scores(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    workspace.patch_ratings(row["id"], 0, {
        "links": {"1": 5},
        "documents": {"note.txt": 3},
    })
    saved = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": "5",
        "answer_correct": 0,
        "links": {"2": "нет"},
        "documents": {"../../note.txt": 9, "folder/other.txt": 4},
    })
    assert saved["ratings"]["answer_complete"] == 5
    assert saved["ratings"]["answer_correct"] is None
    assert saved["ratings"]["links"] == {"1": 5, "2": None}
    assert saved["ratings"]["documents"] == {"note.txt": None, "other.txt": 4}
    assert workspace.patch_ratings(row["id"], 3, {"answer_complete": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 1}) is None
    again = next(item for item in workspace.load()["dialogs"] if item["id"] == row["id"])
    assert again["turns"][0]["answer"] == "ответ"
    assert again["turns"][0]["ratings"]["links"]["1"] == 5
    assert again["turns"][0]["ratings"]["answer_complete"] == 5


def test_prepare_dialog_clears_memory_when_the_dialog_is_not_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    dialog.add_turn("ghost", {"query": "секрет", "answer": "x", "document_names": ["hidden.txt"]})
    assert workspace.prepare_dialog("ghost") is None
    assert dialog.get_dialog("ghost") == []


def test_corrupt_workspace_loads_as_empty(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    path.write_text("{", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text("[]", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text('{"dialogs": "nope", "tree": []}', encoding="utf-8")
    loaded = workspace.load()
    assert loaded["dialogs"] == []
    assert loaded["tree"] == {"id": "root", "name": "", "children": []}


def test_append_turn_reads_document_names_from_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    saved = workspace.append_turn(row["id"], "вопрос", {
        "answer": "ответ",
        "document_names": [],
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": "note.txt"},
            {"document_name": ""},
            {"document_name": "other.txt"},
        ],
    })
    assert saved["turns"][0]["document_names"] == ["note.txt", "other.txt"]
    assert saved["title"] == "вопрос"
    again = workspace.append_turn(row["id"], "другой вопрос", _answer("ещё"))
    assert again["title"] == "вопрос"


def test_append_does_not_recreate_a_deleted_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.delete_dialog(row["id"])
    assert workspace.append_turn(row["id"], "вопрос", _answer("ответ"), create=False) is None
    assert all(item["id"] != row["id"] for item in workspace.load()["dialogs"])
    assert dialog.get_dialog(row["id"]) == []
