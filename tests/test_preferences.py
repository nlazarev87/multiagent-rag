import json

import preferences


def _use(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setattr(preferences, "PATH", path)
    return path


def test_load_returns_defaults_when_missing(tmp_path, monkeypatch):
    path = _use(tmp_path, monkeypatch)
    assert preferences.load() == {"trace_visible": True, "ratings_enabled": True}
    assert not path.exists()


def test_load_returns_defaults_on_broken_json(tmp_path, monkeypatch):
    path = _use(tmp_path, monkeypatch)
    path.write_text("{broken", encoding="utf-8")
    assert preferences.load() == {"trace_visible": True, "ratings_enabled": True}


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    path = _use(tmp_path, monkeypatch)
    saved = preferences.save({"trace_visible": False, "ratings_enabled": False})
    assert saved == {"trace_visible": False, "ratings_enabled": False}
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == {"trace_visible": False, "ratings_enabled": False}
    assert preferences.load() == {"trace_visible": False, "ratings_enabled": False}


def test_save_normalizes_missing_keys(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    assert preferences.save({}) == {"trace_visible": True, "ratings_enabled": True}


def test_filter_turns_hides_trace_and_keeps_ratings():
    data = {
        "tree": {"id": "root"},
        "settings": {"trace_visible": False, "ratings_enabled": True},
        "dialogs": [
            {
                "id": "d",
                "turns": [
                    {
                        "query": "q",
                        "trace": [{"node": "catalog"}],
                        "trace_version": 1,
                        "ratings": {"answer_complete": 5},
                    }
                ],
            }
        ],
    }
    out = preferences.filter_turns(data, {"trace_visible": False, "ratings_enabled": True})
    turn = out["dialogs"][0]["turns"][0]
    assert "trace" not in turn
    assert "trace_version" not in turn
    assert turn["ratings"] == {"answer_complete": 5}
    assert out["tree"] == {"id": "root"}


def test_filter_turns_hides_ratings_and_keeps_trace():
    data = {
        "dialogs": [
            {
                "id": "d",
                "turns": [
                    {
                        "query": "q",
                        "trace": [{"node": "catalog"}],
                        "trace_version": 1,
                        "ratings": {"answer_complete": 5},
                    }
                ],
            }
        ]
    }
    out = preferences.filter_turns(data, {"trace_visible": True, "ratings_enabled": False})
    turn = out["dialogs"][0]["turns"][0]
    assert "ratings" not in turn
    assert turn["trace"] == [{"node": "catalog"}]
    assert turn["trace_version"] == 1


def test_filter_turns_returns_same_when_enabled():
    data = {"dialogs": [{"id": "d", "turns": [{"query": "q", "trace": [], "ratings": {}}]}]}
    out = preferences.filter_turns(data, {"trace_visible": True, "ratings_enabled": True})
    assert out is data
    assert out["dialogs"][0]["turns"][0]["trace"] == []


def test_filter_turns_does_not_mutate_source():
    data = {
        "dialogs": [
            {
                "id": "d",
                "turns": [
                    {
                        "query": "q",
                        "trace": [{"node": "catalog"}],
                        "ratings": {"answer_complete": 5},
                    }
                ],
            }
        ]
    }
    preferences.filter_turns(data, {"trace_visible": False, "ratings_enabled": False})
    turn = data["dialogs"][0]["turns"][0]
    assert "trace" in turn
    assert "ratings" in turn
