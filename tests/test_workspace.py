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


def test_overlapping_tree_write_keeps_the_new_turn(tmp_path, monkeypatch):
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

    def save_tree():
        try:
            workspace.put_tree({
                "id": "root",
                "name": "",
                "children": [
                    {"id": "folder", "name": "Архив", "children": [{"document_name": "note.txt"}]},
                ],
            }, ["note.txt"])
        except Exception as exc:
            errors.append(exc)

    writer = threading.Thread(target=add_turn)
    editor = threading.Thread(target=save_tree)
    writer.start()
    started = False
    try:
        assert entered.wait(5)
        editor.start()
        started = True
        editor.join(0.5)
        assert editor.is_alive()
    finally:
        release.set()
    writer.join(5)
    if started:
        editor.join(5)
    assert errors == []
    assert not writer.is_alive()
    assert not editor.is_alive()
    saved = workspace.load()
    kept = next(item for item in saved["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in kept["turns"]] == ["первый", "второй"]
    assert kept["turns"][1]["answer"] == "новый"
    assert saved["tree"]["children"][0]["name"] == "Архив"
    assert workspace.iter_files(saved["tree"]) == ["note.txt"]


def test_failed_write_keeps_the_saved_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    original = (tmp_path / "workspace.json").read_text(encoding="utf-8")
    real_replace = Path.replace

    def fail_workspace_replace(self, target):
        if self.name.startswith(".workspace.json."):
            raise OSError("disk full")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_workspace_replace)
    with pytest.raises(OSError, match="disk full"):
        workspace.append_turn(row["id"], "второй", _answer("потеря"))
    assert (tmp_path / "workspace.json").read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".workspace.json.*.tmp")) == []
    saved = workspace.load()["dialogs"]
    assert [item["id"] for item in saved] == [row["id"]]
    assert [turn["query"] for turn in saved[0]["turns"]] == ["вопрос"]
    assert saved[0]["turns"][0]["answer"] == "ответ"


def test_patch_ratings_validates_scores_and_document_names(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    other = workspace.create_dialog()
    workspace.append_turn(other["id"], "другой", _answer("второй"))
    updated = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": "4",
        "answer_correct": 5,
        "links": {"1": 3},
        "documents": {"note.txt": 2},
    })
    assert updated["ratings"]["answer_complete"] == 4
    assert updated["ratings"]["answer_correct"] == 5
    cleared = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 9,
        "links": {"1": "нет", "2": 1},
        "documents": {"../secret/note.txt": 3, "dir/other.txt": 0},
    })
    assert cleared["query"] == "вопрос"
    assert cleared["answer"] == "ответ"
    assert cleared["ratings"]["answer_complete"] is None
    assert cleared["ratings"]["answer_correct"] == 5
    assert cleared["ratings"]["links"] == {"1": None, "2": 1}
    assert cleared["ratings"]["documents"] == {"note.txt": 3, "other.txt": None}
    ignored = workspace.patch_ratings(row["id"], 0, {"links": ["1"], "documents": "note.txt"})
    assert ignored["ratings"]["links"]["2"] == 1
    assert ignored["ratings"]["documents"]["note.txt"] == 3
    assert workspace.patch_ratings(row["id"], 3, {"answer_complete": 1}) is None
    assert workspace.patch_ratings(row["id"], -1, {"answer_complete": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 1}) is None
    saved = workspace.load()["dialogs"]
    kept = next(item for item in saved if item["id"] == row["id"])
    assert kept["turns"][0]["ratings"]["answer_correct"] == 5
    assert kept["turns"][0]["answer"] == "ответ"
    untouched = next(item for item in saved if item["id"] == other["id"])
    assert untouched["turns"][0]["answer"] == "второй"
    assert untouched["turns"][0]["ratings"]["answer_complete"] is None


def test_put_tree_keeps_dialogs_and_drops_unsafe_nodes(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    saved = workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [
            "skip",
            {"document_name": "../secret/note.txt"},
            {"document_name": "missing.txt"},
            {
                "id": "folder",
                "name": "П" * 100,
                "children": [
                    {"id": "folder", "name": "повтор", "children": [{"document_name": "hidden.txt"}]},
                    {"document_name": "note.txt"},
                ],
            },
            {"id": "empty", "name": "", "children": []},
        ],
    }, ["note.txt", "extra.txt"])
    assert saved["dialogs"][0]["turns"][0]["answer"] == "ответ"
    folders = [child for child in saved["tree"]["children"] if "document_name" not in child]
    assert folders[0]["id"] == "folder"
    assert folders[0]["name"] == "П" * 80
    assert folders[0]["children"] == [{"document_name": "note.txt"}]
    assert folders[1]["id"] == "empty"
    assert folders[1]["name"] == "Папка"
    names = workspace.iter_files(saved["tree"])
    assert "missing.txt" not in names
    assert "hidden.txt" not in names
    assert "../secret/note.txt" not in names
    assert names.count("note.txt") == 2
    assert names[-1] == "extra.txt"
    assert workspace.load()["dialogs"][0]["turns"][0]["query"] == "вопрос"


def test_append_turn_names_the_dialog_and_sorts_it_first(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    older = workspace.create_dialog()
    newer = workspace.create_dialog()
    long_query = "  вопрос " + ("слово " * 20)
    row = workspace.append_turn(older["id"], long_query, {
        "answer": "ответ",
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": "note.txt"},
            {"document_name": "other.txt"},
        ],
    })
    collapsed = " ".join(long_query.split())
    assert row["title"].endswith("…")
    assert "  " not in row["title"]
    assert collapsed.startswith(row["title"][:-1])
    assert len(row["title"]) < len(collapsed)
    assert row["turns"][0]["document_names"] == ["note.txt", "other.txt"]
    assert row["turns"][0]["ratings"] == workspace.blank_ratings()
    again = workspace.append_turn(older["id"], "ещё", {
        "answer": "второй",
        "document_names": ["kept.txt"],
        "sources": [{"document_name": "ignored.txt"}],
    })
    assert again["title"] == row["title"]
    assert again["turns"][1]["document_names"] == ["kept.txt"]
    assert [item["id"] for item in workspace.load()["dialogs"]][0] == older["id"]
    blank = workspace.append_turn(newer["id"], "   ", {"answer": ""})
    assert blank["title"] == workspace.TITLE


def test_append_does_not_recreate_a_deleted_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.delete_dialog(row["id"])
    assert workspace.append_turn(row["id"], "вопрос", _answer("ответ"), create=False) is None
    assert all(item["id"] != row["id"] for item in workspace.load()["dialogs"])
    assert dialog.get_dialog(row["id"]) == []
