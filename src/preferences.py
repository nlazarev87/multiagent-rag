"""Настройки чата: data/ui/settings.json.

Файл хранит {trace_visible: bool, ratings_enabled: bool}. Битый JSON или
не-словарь читаются как дефолты, запись атомарная.
"""

import json
import threading
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "ui" / "settings.json"
DEFAULTS = {"trace_visible": True, "ratings_enabled": True}
_lock = threading.RLock()


def _flag(data, key):
    value = data.get(key)
    return value if isinstance(value, bool) else DEFAULTS[key]


def load():
    """Прочитать настройки. Битый JSON или не-словарь → дефолты."""
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return dict(DEFAULTS)
    if not isinstance(data, dict):
        return dict(DEFAULTS)
    return {
        "trace_visible": _flag(data, "trace_visible"),
        "ratings_enabled": _flag(data, "ratings_enabled"),
    }


def save(settings):
    """Атомарно записать настройки и вернуть нормализованный словарь."""
    source = settings if isinstance(settings, dict) else {}
    normalized = {
        "trace_visible": _flag(source, "trace_visible"),
        "ratings_enabled": _flag(source, "ratings_enabled"),
    }
    with _lock:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_name(f".{PATH.name}.{uuid.uuid4().hex}.tmp")
        try:
            tmp.write_text(
                json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            tmp.replace(PATH)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    return normalized


def filter_turns(data, settings):
    """Вернуть снимок с вырезанными trace/ratings по настройкам."""
    hide_trace = not settings.get("trace_visible", True)
    hide_ratings = not settings.get("ratings_enabled", True)
    if not hide_trace and not hide_ratings:
        return data
    dialogs = []
    for dialog in data.get("dialogs") or []:
        if not isinstance(dialog, dict):
            dialogs.append(dialog)
            continue
        turns = []
        for turn in dialog.get("turns") or []:
            if not isinstance(turn, dict):
                turns.append(turn)
                continue
            copied = dict(turn)
            if hide_trace:
                copied.pop("trace", None)
                copied.pop("trace_version", None)
            if hide_ratings:
                copied.pop("ratings", None)
            turns.append(copied)
        row = dict(dialog)
        row["turns"] = turns
        dialogs.append(row)
    out = dict(data)
    out["dialogs"] = dialogs
    return out
