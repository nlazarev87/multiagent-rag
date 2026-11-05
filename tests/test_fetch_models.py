"""Тесты scripts/fetch_models.py без реального скачивания."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import fetch_models  # noqa: E402


class FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        if n is None or n < 0:
            n = len(self._data)
        chunk, self._data = self._data[:n], self._data[n:]
        return chunk


def _write_config(tmp_path, models):
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "models.json").write_text(
        json.dumps({"default": "qvikhr", "models": models}), encoding="utf-8"
    )
    return config_dir


def _cfg(tmp_path, files, size, sha):
    return _write_config(
        tmp_path,
        [{"id": "qvikhr", "name": "Q", "quant": "Q4_K_M", "files": files,
          "size_bytes": size, "sha256": [sha]}],
    )


def test_file_specs_from_config(monkeypatch, tmp_path):
    config_dir = _cfg(tmp_path, ["a.gguf"], 5, "abc")
    monkeypatch.setattr(fetch_models, "_config_dir", lambda: config_dir)
    specs = fetch_models._file_specs("qvikhr")
    assert specs == [("a.gguf", fetch_models.DOWNLOAD_URLS["qvikhr"][0], 5, "abc")]


def test_file_specs_unknown_model(monkeypatch, tmp_path):
    config_dir = _cfg(tmp_path, ["a.gguf"], 5, "abc")
    monkeypatch.setattr(fetch_models, "_config_dir", lambda: config_dir)
    with pytest.raises(ValueError):
        fetch_models._file_specs("нет-такой")


def test_file_specs_no_url(monkeypatch, tmp_path):
    config_dir = _write_config(
        tmp_path, [{"id": "qwen2.5-7b", "files": ["x.gguf"], "size_bytes": 1, "sha256": ["a"]}]
    )
    monkeypatch.setattr(fetch_models, "_config_dir", lambda: config_dir)
    with pytest.raises(ValueError):
        fetch_models._file_specs("qwen2.5-7b")


def test_status(monkeypatch, tmp_path):
    path = tmp_path / "f.gguf"
    assert fetch_models._status(path, 5, "0" * 64) == "missing"
    path.write_bytes(b"hello")
    assert fetch_models._status(path, 5, hashlib.sha256(b"hello").hexdigest()) == "ok"
    assert fetch_models._status(path, 4, hashlib.sha256(b"hello").hexdigest()) == "bad-size"
    assert fetch_models._status(path, 5, "0" * 64) == "bad-sha"


def test_download_writes_part_then_renames(monkeypatch, tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setattr(fetch_models, "_models_dir", lambda: models)
    data = b"hello"
    monkeypatch.setattr(
        fetch_models.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse(data)
    )
    dest = models / "m.gguf"
    part = models / "m.gguf.part"
    fetch_models._download_file(
        "http://x", dest, part, len(data), hashlib.sha256(data).hexdigest(), force=False
    )
    assert dest.read_bytes() == data
    assert not part.exists()


def test_resume_sends_range_and_appends(monkeypatch, tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setattr(fetch_models, "_models_dir", lambda: models)
    part = models / "m.gguf.part"
    part.write_bytes(b"hel")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["headers"] = req.headers
        return FakeResponse(b"lo", status=206)

    monkeypatch.setattr(fetch_models.urllib.request, "urlopen", fake_urlopen)
    fetch_models._download_file(
        "http://x", models / "m.gguf", part, 5, hashlib.sha256(b"hello").hexdigest(),
        force=False,
    )
    assert captured["headers"]["Range"] == "bytes=3-"
    assert (models / "m.gguf").read_bytes() == b"hello"
    assert not part.exists()


def test_bad_sha_does_not_rename(monkeypatch, tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setattr(fetch_models, "_models_dir", lambda: models)
    data = b"hello"
    monkeypatch.setattr(
        fetch_models.urllib.request, "urlopen", lambda req, timeout=None: FakeResponse(data)
    )
    dest = models / "m.gguf"
    part = models / "m.gguf.part"
    with pytest.raises(RuntimeError):
        fetch_models._download_file("http://x", dest, part, len(data), "0" * 64, force=False)
    assert not dest.exists()
    assert part.exists()


def test_download_retries_after_network_error(monkeypatch, tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    monkeypatch.setattr(fetch_models, "_models_dir", lambda: models)
    data = b"hello"
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("connection reset")
        return FakeResponse(data)

    monkeypatch.setattr(fetch_models.urllib.request, "urlopen", fake_urlopen)
    dest = models / "m.gguf"
    part = models / "m.gguf.part"
    fetch_models._download_file(
        "http://x", dest, part, len(data), hashlib.sha256(data).hexdigest(), force=False
    )
    assert dest.read_bytes() == data
    assert len(calls) == 2
    assert not part.exists()


def test_ensure_space_raises_when_low(monkeypatch, tmp_path):
    monkeypatch.setattr(
        fetch_models.shutil, "disk_usage", lambda path: type("U", (), {"free": 10})()
    )
    with pytest.raises(RuntimeError):
        fetch_models._ensure_space(tmp_path, 1000)


def test_fetch_skips_when_file_already_ok(monkeypatch, tmp_path):
    data = b"hello"
    config_dir = _cfg(tmp_path, ["a.gguf"], len(data), hashlib.sha256(data).hexdigest())
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.gguf").write_bytes(data)
    monkeypatch.setattr(fetch_models, "_config_dir", lambda: config_dir)
    monkeypatch.setattr(fetch_models, "_models_dir", lambda: models)
    called = []
    monkeypatch.setattr(fetch_models, "_download_file", lambda *a, **k: called.append(1))
    assert fetch_models.fetch(["qvikhr"], force=False) is True
    assert called == []


def test_main_check_missing_returns_1(monkeypatch, tmp_path):
    config_dir = _cfg(tmp_path, ["a.gguf"], 5, "abc")
    monkeypatch.setattr(fetch_models, "_config_dir", lambda: config_dir)
    monkeypatch.setattr(fetch_models, "_models_dir", lambda: tmp_path / "models")
    assert fetch_models.main(["--model", "qvikhr", "--check"]) == 1
