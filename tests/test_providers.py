"""Тесты каталога площадок и хранилища ключа (src/providers.py)."""

import json

import pytest

import providers


@pytest.fixture(autouse=True)
def _clean_state():
    providers._memory_key = None
    yield
    providers._memory_key = None


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_read_catalog_hyperbolic(monkeypatch, tmp_path):
    config_dir = tmp_path / "config"
    _write(
        config_dir / "providers.json",
        {
            "default": "hyperbolic",
            "providers": [
                {
                    "id": "hyperbolic",
                    "name": "Hyperbolic AI",
                    "base_url": "https://api.hyperbolic.xyz/v1",
                    "requires_key": True,
                    "models": [{"id": "m", "context": 131072, "price_in": 0.4, "price_out": 1.6}],
                }
            ],
        },
    )
    monkeypatch.setattr(providers, "_config_dir", lambda: config_dir)
    assert providers.default_provider_id() == "hyperbolic"
    card = providers.get_provider("hyperbolic")
    assert card is not None
    assert card["base_url"].endswith("/v1")
    assert providers.get_provider("nope") is None
    assert providers.get_provider_model("hyperbolic", "m")["context"] == 131072
    assert providers.get_provider_model("hyperbolic", "nope") is None


def test_read_catalog_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "_config_dir", lambda: tmp_path / "config")
    assert providers.read_catalog() == {}
    assert providers.providers() == []
    assert providers.default_provider_id() == "hyperbolic"


def test_save_load_reset_key(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(providers, "_root", lambda: tmp_path)
    assert providers.load_key() is None
    assert providers.key_source() == "none"
    providers.save_key("  hk-123  ")
    assert providers.load_key() == "hk-123"
    assert providers.key_source() == "file"
    providers.reset_key()
    assert providers.load_key() is None
    assert providers.key_source() == "none"


def test_env_key_wins_over_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setattr(providers, "_root", lambda: tmp_path)
    providers.save_key("file-key")
    assert providers.load_key() == "env-key"
    assert providers.key_source() == "env"
    providers.reset_key()
    assert providers.key_source() == "env"  # reset не прячет env


def test_empty_env_not_a_key(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", "   ")
    monkeypatch.setattr(providers, "_root", lambda: tmp_path)
    assert providers.load_key() is None
    assert providers.key_source() == "none"


def test_load_env_file_does_not_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_API_KEY", "existing")
    monkeypatch.delenv("LLM_MODEL_PATH", raising=False)
    root = tmp_path
    (root / ".env").write_text("LLM_API_KEY=from-file\nLLM_MODEL_PATH=/x.gguf\n", encoding="utf-8")
    monkeypatch.setattr(providers, "_root", lambda: root)
    providers.load_env_file()
    import os

    assert os.environ["LLM_API_KEY"] == "existing"  # не перезаписан
    assert os.environ["LLM_MODEL_PATH"] == "/x.gguf"
