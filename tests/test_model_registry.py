"""Тесты реестра локальных моделей.

Проверяют карточки из config/models.json, доступность файлов, fallback для
неизвестного GGUF, группировку шардов и защиту от ../ и symlink.
"""

import json

import pytest

import model_registry


def _write_config(tmp_path, cfg):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "models.json").write_text(json.dumps(cfg), encoding="utf-8")
    return config_dir


def _write_models(tmp_path, files):
    models = tmp_path / "models"
    models.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = models / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return models


def _setup(monkeypatch, tmp_path, cfg=None, files=None):
    config_dir = _write_config(tmp_path, cfg or {"default": "qvikhr", "models": []})
    models = _write_models(tmp_path, files or {})
    monkeypatch.setattr(model_registry, "_config_dir", lambda: config_dir)
    monkeypatch.setattr(model_registry, "_models_dir", lambda: models)
    return models


def test_config_has_four_models_with_default(monkeypatch, tmp_path):
    """Реальный config/models.json: 4 модели, дефолт qvikhr, 7B — два шарда."""
    monkeypatch.setattr(model_registry, "_models_dir", lambda: tmp_path / "empty")
    cards = model_registry.list_models()
    by_id = {card["id"]: card for card in cards}
    assert set(by_id) == {"qwen2.5-1.5b", "qwen2.5-7b", "qvikhr", "rusmind"}
    assert model_registry.default_model_id() == "qvikhr"
    assert len(by_id["qwen2.5-7b"]["files"]) == 2
    for card in cards:
        assert card["name"]
        assert card["quant"]
        assert card["description"]
        assert card["pros"]
        assert card["cons"]
        assert card["resources"]
        assert card["license"]
        assert card["source"]


def test_missing_file_marks_unavailable_not_removed(monkeypatch, tmp_path):
    cfg = {
        "default": "a",
        "models": [
            {
                "id": "a",
                "name": "A",
                "quant": "Q4_K_M",
                "files": ["a.gguf"],
                "size_bytes": 1,
                "sha256": [],
                "description": "d",
                "pros": [],
                "cons": [],
                "resources": {},
                "license": "l",
                "source": "s",
            }
        ],
    }
    _setup(monkeypatch, tmp_path / "with_file", cfg=cfg, files={"a.gguf": b"x"})
    present = model_registry.get_model("a")
    assert present is not None and present["available"] is True
    # Убираем файл: карточка остаётся, но available=false.
    _setup(monkeypatch, tmp_path / "without_file", cfg=cfg, files={})
    missing = model_registry.get_model("a")
    assert missing is not None
    assert missing["available"] is False


def test_unknown_gguf_becomes_fallback(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, files={"mystery.gguf": b"x"})
    cards = model_registry.list_models()
    assert [card["id"] for card in cards] == ["mystery"]
    assert cards[0]["available"] is True
    assert cards[0]["files"] == ["mystery.gguf"]
    assert cards[0]["license"] == "unknown"


def test_unknown_shards_grouped_into_one_card(monkeypatch, tmp_path):
    _setup(
        monkeypatch,
        tmp_path,
        files={
            "foo-00001-of-00002.gguf": b"one",
            "foo-00002-of-00002.gguf": b"two",
        },
    )
    cards = model_registry.list_models()
    assert len(cards) == 1
    assert cards[0]["files"] == [
        "foo-00001-of-00002.gguf",
        "foo-00002-of-00002.gguf",
    ]


def test_known_model_does_not_duplicate_its_shards(monkeypatch, tmp_path):
    cfg = {
        "default": "qwen2.5-7b",
        "models": [
            {
                "id": "qwen2.5-7b",
                "name": "Qwen2.5-7B-Instruct",
                "quant": "Q4_K_M",
                "files": [
                    "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf",
                    "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf",
                ],
                "size_bytes": 2,
                "sha256": [],
                "description": "d",
                "pros": [],
                "cons": [],
                "resources": {},
                "license": "l",
                "source": "s",
            }
        ],
    }
    _setup(
        monkeypatch,
        tmp_path,
        cfg=cfg,
        files={
            "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf": b"one",
            "qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf": b"two",
        },
    )
    cards = model_registry.list_models()
    assert len(cards) == 1
    assert cards[0]["id"] == "qwen2.5-7b"
    assert cards[0]["available"] is True
    assert len(cards[0]["files"]) == 2


def test_safe_filename_rejects_path_traversal():
    assert model_registry._safe_filename("../evil.gguf") is False
    assert model_registry._safe_filename("../../etc/passwd") is False
    assert model_registry._safe_filename("a/b.gguf") is False
    assert model_registry._safe_filename("") is False
    assert model_registry._safe_filename("..") is False
    assert model_registry._safe_filename("model.gguf") is True


def test_path_traversal_does_not_escape_models_dir(monkeypatch, tmp_path):
    cfg = {
        "default": "x",
        "models": [
            {
                "id": "x",
                "name": "X",
                "quant": "",
                "files": ["../outside.gguf"],
                "size_bytes": 0,
                "sha256": [],
                "description": "d",
                "pros": [],
                "cons": [],
                "resources": {},
                "license": "l",
                "source": "s",
            }
        ],
    }
    _setup(monkeypatch, tmp_path, cfg=cfg)
    card = model_registry.get_model("x")
    assert card is not None
    assert card["files"] == []
    assert card["available"] is False


def test_embedding_and_reranker_dirs_ignored(monkeypatch, tmp_path):
    _setup(
        monkeypatch,
        tmp_path,
        files={
            "chat.gguf": b"chat",
            "embedding/x.gguf": b"embed",
            "reranker/y.gguf": b"rerank",
        },
    )
    cards = model_registry.list_models()
    assert [card["id"] for card in cards] == ["chat"]


def test_symlink_is_ignored(monkeypatch, tmp_path):
    outside = tmp_path / "outside.gguf"
    outside.write_bytes(b"x")
    models = _setup(monkeypatch, tmp_path)
    link = models / "linked.gguf"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink недоступен на этой системе")
    assert model_registry.list_models() == []


def test_primary_file_is_first_shard(monkeypatch, tmp_path):
    cfg = {
        "default": "m",
        "models": [
            {
                "id": "m",
                "name": "M",
                "quant": "Q4_K_M",
                "files": ["m-00001-of-00002.gguf", "m-00002-of-00002.gguf"],
                "size_bytes": 2,
                "sha256": [],
                "description": "d",
                "pros": [],
                "cons": [],
                "resources": {},
                "license": "l",
                "source": "s",
            }
        ],
    }
    models = _setup(
        monkeypatch,
        tmp_path,
        cfg=cfg,
        files={"m-00001-of-00002.gguf": b"one", "m-00002-of-00002.gguf": b"two"},
    )
    card = model_registry.get_model("m")
    assert card is not None
    assert model_registry.primary_file(card) == (models / "m-00001-of-00002.gguf").resolve()
