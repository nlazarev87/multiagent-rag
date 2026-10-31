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


def test_corrupt_workspace_reads_as_empty_and_stays_on_disk(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    raw = "{not json"
    path.write_text(raw, encoding="utf-8")
    assert workspace.load() == workspace.empty()
    assert path.read_text(encoding="utf-8") == raw
    path.write_text("[]", encoding="utf-8")
    assert workspace.load() == workspace.empty()
    path.write_text('{"dialogs": {"id": "x"}, "tree": ["no"]}', encoding="utf-8")
    loaded = workspace.load()
    assert loaded["dialogs"] == []
    assert loaded["tree"] == {"id": "root", "name": "", "children": []}
    assert path.read_text(encoding="utf-8").startswith("{")


def test_failed_write_keeps_the_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    workspace.save(workspace.empty())
    original = path.read_text(encoding="utf-8")

    def fail_replace(self, target):
        raise OSError("disk")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="disk"):
        workspace.save({"dialogs": [{"id": "new"}], "tree": workspace.empty()["tree"]})
    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".workspace.json.*.tmp")) == []


def test_ratings_accept_only_one_to_five_and_keep_other_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    assert [workspace.score(value) for value in (None, "", 0, 1, 5, 6, "4", "нет")] == [
        None, None, None, 1, 5, None, 4, None,
    ]
    row = workspace.create_dialog()
    workspace.append_turn(row["id"], "вопрос", {
        "answer": "ответ",
        "sources": [
            {"document_name": "note.txt"},
            {"document_name": "note.txt"},
            {"document_name": ""},
            {"document_name": "other.txt"},
        ],
    })
    assert workspace.load()["dialogs"][0]["turns"][0]["document_names"] == ["note.txt", "other.txt"]
    workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 4,
        "answer_correct": 2,
        "links": {"1": 5},
        "documents": {"note.txt": 3},
    })
    patched = workspace.patch_ratings(row["id"], 0, {
        "answer_complete": 0,
        "answer_correct": "нет",
        "links": {"1": 9, "2": 1},
        "documents": {"../note.txt": 6, "other.txt": "3"},
    })
    assert patched["ratings"]["answer_complete"] is None
    assert patched["ratings"]["answer_correct"] is None
    assert patched["ratings"]["links"] == {"1": None, "2": 1}
    assert patched["ratings"]["documents"] == {"note.txt": None, "other.txt": 3}
    kept = workspace.patch_ratings(row["id"], 0, {"answer_complete": 1, "links": ["no"], "documents": "no"})
    assert kept["ratings"]["answer_complete"] == 1
    assert kept["ratings"]["answer_correct"] is None
    assert kept["ratings"]["links"] == {"1": None, "2": 1}
    assert kept["ratings"]["documents"]["other.txt"] == 3
    assert workspace.patch_ratings(row["id"], 3, {"answer_complete": 1}) is None
    assert workspace.patch_ratings("missing", 0, {"answer_complete": 1}) is None


def test_tree_drops_cycles_paths_and_blank_names(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    saved = workspace.put_tree({
        "id": "root",
        "name": "",
        "children": [
            {
                "id": "folder",
                "name": "",
                "children": [
                    {"id": "folder", "name": "снова", "children": [{"document_name": "buried.txt"}]},
                    {"document_name": "../note.txt"},
                    {"document_name": "missing.txt"},
                    "skip",
                ],
            },
            {"id": "named", "name": "П" * 90, "children": []},
        ],
    }, ["note.txt", "extra.txt"])
    folder, named = saved["tree"]["children"][0], saved["tree"]["children"][1]
    assert folder["name"] == "Папка"
    assert folder["children"] == [{"document_name": "note.txt"}]
    assert named["name"] == "П" * 80
    assert workspace.iter_files(saved["tree"]) == ["note.txt", "extra.txt"]


def test_append_turn_keeps_a_short_title_and_moves_the_dialog_first(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    clock = {"n": 0}

    def now():
        clock["n"] += 1
        return f"2020-01-01T00:00:{clock['n']:02d}+00:00"

    monkeypatch.setattr(workspace, "_now", now)
    first = workspace.create_dialog()
    second = workspace.create_dialog()
    saved = workspace.append_turn(first["id"], "а" * 61, _answer("ответ"))
    assert saved["title"] == "а" * 60 + "…"
    again = workspace.append_turn(first["id"], "другой вопрос", _answer("ещё"))
    assert again["title"] == saved["title"]
    blank = workspace.append_turn(second["id"], "   ", _answer("пусто"))
    assert blank["title"] == "Новый диалог"
    assert [item["id"] for item in workspace.load()["dialogs"]] == [second["id"], first["id"]]


def test_append_does_not_recreate_a_deleted_dialog(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PATH", tmp_path / "workspace.json")
    row = workspace.create_dialog()
    workspace.delete_dialog(row["id"])
    assert workspace.append_turn(row["id"], "вопрос", _answer("ответ"), create=False) is None
    assert all(item["id"] != row["id"] for item in workspace.load()["dialogs"])
    assert dialog.get_dialog(row["id"]) == []
