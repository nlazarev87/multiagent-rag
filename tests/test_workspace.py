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
    entered = threading.Event()
    started = threading.Event()
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
        started.set()
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
    began = False
    try:
        assert entered.wait(5)
        saver.start()
        began = True
        assert started.wait(5)
        saver.join(1)
        assert saver.is_alive()
    finally:
        release.set()
    writer.join(5)
    if began:
        saver.join(5)
    assert errors == []
    assert not writer.is_alive()
    assert not saver.is_alive()
    saved = next(item for item in workspace.load()["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in saved["turns"]] == ["первый", "второй"]
    assert saved["turns"][1]["answer"] == "новый"
    tree = workspace.load()["tree"]
    assert tree["children"][0]["name"] == "Папка"
    assert workspace.iter_files(tree) == ["note.txt"]


def test_failed_replace_keeps_the_saved_workspace(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    saved = path.read_text(encoding="utf-8")

    def fail_replace(self, target):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        workspace.append_turn(row["id"], "ещё", _answer("новый"))
    assert path.read_text(encoding="utf-8") == saved
    assert [item.name for item in tmp_path.iterdir()] == ["workspace.json"]
    assert workspace.load()["dialogs"][0]["turns"][0]["answer"] == "ответ"


def test_broken_workspace_file_loads_empty_and_can_be_saved(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    for text in ("{", "[]", '{"dialogs": {}, "tree": []}'):
        path.write_text(text, encoding="utf-8")
        assert workspace.load() == workspace.empty()
    row = workspace.create_dialog()
    assert workspace.load()["dialogs"][0]["id"] == row["id"]


def test_append_turn_keeps_title_sources_and_order(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    clock = {"n": 0}

    def now():
        clock["n"] += 1
        return f"2020-01-01T00:00:{clock['n']:02d}+00:00"

    monkeypatch.setattr(workspace, "_now", now)
    older = workspace.create_dialog()
    newer = workspace.create_dialog()
    long_query = "а" * 80
    workspace.append_turn(older["id"], long_query, {
        "answer": "ответ",
        "document_names": [],
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": "note.txt"},
            {"document_name": "other.txt"},
        ],
    })
    workspace.append_turn(older["id"], "второй вопрос", _answer("ещё"))
    saved = next(item for item in workspace.load()["dialogs"] if item["id"] == older["id"])
    assert saved["title"] == "а" * 60 + "…"
    assert [turn["query"] for turn in saved["turns"]] == [long_query, "второй вопрос"]
    assert saved["turns"][0]["document_names"] == ["note.txt", "other.txt"]
    assert [item["id"] for item in workspace.load()["dialogs"]][:2] == [older["id"], newer["id"]]
    blank = workspace.create_dialog()
    workspace.append_turn(blank["id"], "   ", _answer("пусто"))
    titled = next(item for item in workspace.load()["dialogs"] if item["id"] == blank["id"])
    assert titled["title"] == workspace.TITLE
    assert next(item for item in workspace.load()["dialogs"] if item["id"] == newer["id"])["turns"] == []


def test_patch_ratings_merges_and_rejects_out_of_range(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    first = workspace.patch_ratings(row["id"], 0, {"answer_complete": 4, "links": {"1": 2}})
    assert first["ratings"]["answer_complete"] == 4
    assert first["ratings"]["links"] == {"1": 2}
    second = workspace.patch_ratings(row["id"], 0, {
        "answer_correct": 5,
        "links": {"2": 3},
        "documents": {"dir/note.txt": 2, "other.txt": "нет"},
    })
    assert second["ratings"]["answer_complete"] == 4
    assert second["ratings"]["answer_correct"] == 5
    assert second["ratings"]["links"] == {"1": 2, "2": 3}
    assert second["ratings"]["documents"] == {"note.txt": 2, "other.txt": None}
    cleared = workspace.patch_ratings(row["id"], 0, {"answer_complete": 0, "links": {"1": 6}})
    assert cleared["ratings"]["answer_complete"] is None
    assert cleared["ratings"]["answer_correct"] == 5
    assert cleared["ratings"]["links"]["1"] is None
    assert cleared["ratings"]["links"]["2"] == 3
    assert workspace.patch_ratings(row["id"], -1, {"answer_complete": 5}) is None
    assert workspace.patch_ratings(row["id"], 3, {"answer_complete": 5}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 5}) is None
    stored = workspace.load()["dialogs"][0]["turns"][0]["ratings"]
    assert stored["answer_complete"] is None
    assert stored["answer_correct"] == 5
    assert stored["documents"]["note.txt"] == 2


def test_sanitize_tree_stops_on_a_repeated_folder_and_strips_paths():
    folder = {
        "id": "loop",
        "name": "П" * 100,
        "children": [
            {"document_name": "dir/note.txt"},
            {"document_name": "missing.txt"},
            {"document_name": ""},
            "nope",
            {"id": "loop", "name": "Снова", "children": [{"document_name": "note.txt"}]},
        ],
    }
    tree = workspace.sanitize_tree({
        "id": "root",
        "name": "",
        "children": [folder, {"id": "", "name": "", "children": []}],
    }, {"note.txt"})
    assert tree["children"][0]["id"] == "loop"
    assert tree["children"][0]["name"] == "П" * 80
    assert tree["children"][0]["children"] == [{"document_name": "note.txt"}]
    assert tree["children"][1]["name"] == "Папка"
    assert tree["children"][1]["children"] == []
    assert workspace.sanitize_tree(["no"], {"note.txt"}) == {"id": "root", "name": "", "children": []}


def test_snapshot_lists_known_files_once_and_keeps_dialogs(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [{"document_name": "note.txt"}],
    }, ["note.txt"])
    first = workspace.snapshot(["note.txt", "other.txt"])
    second = workspace.snapshot(["note.txt", "other.txt"])
    assert workspace.iter_files(first["tree"]) == ["note.txt", "other.txt"]
    assert workspace.iter_files(second["tree"]) == ["note.txt", "other.txt"]
    assert second["dialogs"][0]["id"] == row["id"]
    assert second["dialogs"][0]["turns"][0]["answer"] == "ответ"


def test_get_dialog_row_keeps_the_last_twenty_turns(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    for number in range(25):
        workspace.append_turn(row["id"], str(number), _answer(str(number)))
    dialog.reset()
    loaded = workspace.get_dialog_row(row["id"])
    assert loaded["id"] == row["id"]
    assert [turn["query"] for turn in dialog.get_dialog(row["id"])] == [str(number) for number in range(5, 25)]
    assert len(workspace.load()["dialogs"][0]["turns"]) == 25
    assert workspace.get_dialog_row("missing") is None
