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
    saved = workspace.load()
    dialog_row = next(item for item in saved["dialogs"] if item["id"] == dialog_id)
    assert [turn["query"] for turn in dialog_row["turns"]] == ["первый", "второй"]
    assert dialog_row["turns"][1]["answer"] == "новый"
    assert workspace.iter_files(saved["tree"]) == ["note.txt"]
    assert saved["tree"]["children"][0]["name"] == "Папка"


def test_ratings_reject_bad_scores_and_path_keys(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    turn = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 4,
        "answer_correct": "5",
        "links": {"1": 3},
        "documents": {"dir/note.txt": 2, "other.txt": 9, "../keep.txt": 1},
    })
    assert turn["answer"] == "ответ"
    assert turn["ratings"] == {
        "answer_complete": 4,
        "answer_correct": 5,
        "links": {"1": 3},
        "documents": {"note.txt": 2, "other.txt": None, "keep.txt": 1},
    }
    again = workspace.patch_ratings(row["id"], 0, {"answer_correct": 1, "links": "нет"})
    assert again["ratings"]["answer_complete"] == 4
    assert again["ratings"]["answer_correct"] == 1
    assert again["ratings"]["links"] == {"1": 3}
    assert again["ratings"]["documents"]["note.txt"] == 2
    cleared = workspace.patch_ratings(row["id"], 0, {"answer_complete": "нет"})
    assert cleared["ratings"]["answer_complete"] is None
    assert cleared["ratings"]["answer_correct"] == 1
    before = path.read_bytes()
    assert workspace.patch_ratings(row["id"], -1, {"answer_complete": 5}) is None
    assert workspace.patch_ratings(row["id"], 2, {"answer_complete": 5}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 5}) is None
    assert path.read_bytes() == before


def test_tree_keeps_known_basenames_and_stops_repeated_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    saved = workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [
            {
                "id": "a",
                "name": "",
                "children": [
                    {"id": "a", "name": "снова", "children": [{"document_name": "nested/note.txt"}]},
                    {"document_name": "keep.txt"},
                ],
            },
            "skip",
            {"document_name": "../other.txt"},
            {"document_name": "dir/secret.txt"},
            {"id": "long", "name": "я" * 90, "children": []},
        ],
    }, ["note.txt", "keep.txt", "other.txt"])
    children = saved["tree"]["children"]
    assert children[0]["name"] == "Папка"
    assert children[0]["children"] == [{"document_name": "keep.txt"}]
    assert children[1] == {"document_name": "other.txt"}
    assert children[2]["name"] == "я" * 80
    assert children[2]["children"] == []
    assert children[3] == {"document_name": "note.txt"}
    assert workspace.iter_files(saved["tree"]) == ["keep.txt", "other.txt", "note.txt"]
    assert saved["dialogs"][0]["turns"][0]["answer"] == "ответ"
    assert workspace.sanitize_tree(["no"], {"note.txt"}) == {"id": "root", "name": "", "children": []}


def test_broken_workspace_file_loads_as_empty(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    path.write_text("{", encoding="utf-8")
    assert workspace.load() == {"dialogs": [], "tree": {"id": "root", "name": "", "children": []}}
    path.write_text("[]", encoding="utf-8")
    assert workspace.load()["dialogs"] == []
    path.write_text('{"dialogs": {"id": "x"}, "tree": ["no"]}', encoding="utf-8")
    loaded = workspace.load()
    assert loaded["dialogs"] == []
    assert loaded["tree"] == {"id": "root", "name": "", "children": []}
    row = workspace.append_turn("d1", "вопрос", _answer("ответ"))
    assert row["id"] == "d1"
    assert row["turns"][0]["answer"] == "ответ"


def test_failed_replace_keeps_the_previous_workspace(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", _answer("ответ"))
    original = path.read_bytes()

    def fail_replace(self, target):
        raise OSError("нет места")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="нет места"):
        workspace.append_turn(row["id"], "ещё", _answer("потеря"))
    assert path.read_bytes() == original
    assert list(tmp_path.glob(".workspace.json.*.tmp")) == []


def test_append_turn_keeps_title_sources_and_order(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    older = workspace.create_dialog()
    newer = workspace.create_dialog()
    data = workspace.load()
    for item in data["dialogs"]:
        if item["id"] == older["id"]:
            item["updated_at"] = "2020-01-01T00:00:00+00:00"
            item["title"] = "Своё имя"
        if item["id"] == newer["id"]:
            item["updated_at"] = "2020-01-02T00:00:00+00:00"
    workspace.save(data)
    blank = workspace.append_turn(newer["id"], "   ", _answer("пусто"))
    assert blank["title"] == workspace.TITLE
    kept = workspace.append_turn(older["id"], "другой вопрос", {
        "answer": "4",
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": ""},
            {"document_name": "note.txt"},
            {"document_name": "other.txt"},
        ],
    })
    assert kept["title"] == "Своё имя"
    assert kept["turns"][-1]["document_names"] == ["note.txt", "other.txt"]
    plain = workspace.create_dialog()
    collapsed = workspace.append_turn(plain["id"], "  номер\tцеха  ", _answer("4"))
    assert collapsed["title"] == "номер цеха"
    long = ("описание " * 12).strip()
    titled = workspace.append_turn(plain["id"], long, _answer("ок"))
    assert titled["title"] == "номер цеха"
    fresh = workspace.create_dialog()
    titled = workspace.append_turn(fresh["id"], long, _answer("ок"))
    assert titled["title"].startswith("описание")
    assert titled["title"].endswith("…")
    assert 60 <= len(titled["title"]) <= 61
    ordered = workspace.load()["dialogs"]
    assert ordered[0]["id"] == fresh["id"]
    assert [item["id"] for item in ordered if item["id"] in (older["id"], newer["id"])] == [older["id"], newer["id"]]


def test_delete_dialog_keeps_the_other_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    first = workspace.create_dialog()
    second = workspace.create_dialog()
    workspace.append_turn(first["id"], "первый", _answer("один"))
    workspace.append_turn(second["id"], "второй", _answer("два"))
    dialog.reset()
    workspace.prepare_dialog(first["id"])
    workspace.prepare_dialog(second["id"])
    workspace.delete_dialog(first["id"])
    assert dialog.get_dialog(first["id"]) == []
    assert [turn["query"] for turn in dialog.get_dialog(second["id"])] == ["второй"]
    assert workspace.prepare_dialog(first["id"]) is None
    saved = workspace.load()["dialogs"]
    assert [item["id"] for item in saved] == [second["id"]]
    assert saved[0]["turns"][0]["answer"] == "два"


def test_prepare_dialog_loads_only_the_latest_twenty_turns(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    dialog.reset()
    row = workspace.create_dialog()
    for index in range(21):
        workspace.append_turn(row["id"], str(index), _answer("a"))
    dialog.reset()
    loaded = workspace.get_dialog_row(row["id"])
    assert [turn["query"] for turn in loaded["turns"]] == [str(index) for index in range(21)]
    assert [turn["query"] for turn in dialog.get_dialog(row["id"])] == [str(index) for index in range(1, 21)]
