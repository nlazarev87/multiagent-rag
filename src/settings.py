"""Чтение config/ и data/prompts/ с памятью на процесс.

Факты из загруженных документов живут в этих JSON, не в src. reload() заставляет прочитать файлы заново.
"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_cache = {}


def _root():
    return Path(os.environ.get("APP_ROOT", ROOT))


def _config_dir():
    return Path(os.environ.get("CONFIG_DIR", _root() / "config"))


def _prompts_dir():
    return Path(os.environ.get("PROMPTS_DIR", _root() / "data" / "prompts"))


def reload():
    """Сбросить кэш JSON. Следующий вызов читает файлы заново."""
    _cache.clear()


def _read(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def runtime():
    """Лимиты из config/runtime.json."""
    if "runtime" not in _cache:
        _cache["runtime"] = _read(_config_dir() / "runtime.json", {})
    return _cache["runtime"]


def lexicon():
    """Основы единиц измерения из config/check_lexicon.json."""
    if "lexicon" not in _cache:
        _cache["lexicon"] = _read(_config_dir() / "check_lexicon.json", {})
    return _cache["lexicon"]


def routing():
    """Шаблоны каталога и фильтр where из config/routing.json."""
    if "routing" not in _cache:
        _cache["routing"] = _read(_config_dir() / "routing.json", {})
    return _cache["routing"]


def prompts():
    """Фразы ответа и отзыва из data/prompts/answer.json."""
    if "prompts" not in _cache:
        _cache["prompts"] = _read(_prompts_dir() / "answer.json", {})
    return _cache["prompts"]


def fewshot():
    """Примеры вопрос–фрагменты–ответ из data/prompts/fewshot.json."""
    if "fewshot" not in _cache:
        _cache["fewshot"] = _read(_prompts_dir() / "fewshot.json", [])
    return _cache["fewshot"]


def where():
    """Непустые фильтры маршрута. Пустое значение не становится условием Chroma."""
    extra = routing().get("where") or {}
    return {key: value for key, value in extra.items() if value not in (None, "", [])}
