import json

import settings


def test_missing_config_uses_defaults_until_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(settings, "_prompts_dir", lambda: tmp_path / "prompts")
    settings.reload()
    try:
        assert settings.runtime() == {}
        assert settings.lexicon() == {}
        assert settings.routing() == {}
        assert settings.prompts() == {}
        assert settings.fewshot() == []
        assert settings.where() == {}
        (tmp_path / "runtime.json").write_text(json.dumps({"attempts": 1}), encoding="utf-8")
        assert settings.runtime() == {}
        settings.reload()
        assert settings.runtime() == {"attempts": 1}
    finally:
        monkeypatch.undo()
        settings.reload()
