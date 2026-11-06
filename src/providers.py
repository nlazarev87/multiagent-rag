"""Каталог площадок и хранилище ключа внешнего API.

Каталог — config/providers.json. Он копируется в образ и не лежит на томе ./data,
поэтому из запросов только читается. Секрет — data/secrets/llm_api_key (том ./data,
игнорируется git). Непустая LLM_API_KEY окружения важнее файла; пустая строка не
считается ключом. Автозагрузка корневого .env — отдельной функцией на старте,
не кодом при импорте модуля (иначе pytest подхватит настоящий ключ).
"""

import json
import os
import threading
from pathlib import Path
from typing import Any

import settings

SECRET_NAME = "llm_api_key"

# Последний ключ, записанный через save_key в этом процессе: чтобы «Проверить»
# работало сразу, без перезапуска. env-источник его перекрывает.
_memory_key: str | None = None
_lock = threading.Lock()


def _root() -> Path:
    return settings._root()


def _config_dir() -> Path:
    return settings._config_dir()


def _secrets_dir() -> Path:
    return _root() / "data" / "secrets"


def _secret_path() -> Path:
    return _secrets_dir() / SECRET_NAME


def read_catalog() -> dict[str, Any]:
    """Каталог площадок из config/providers.json (битый JSON → пустой)."""
    path = _config_dir() / "providers.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def providers() -> list[dict[str, Any]]:
    """Список карточек площадок из каталога."""
    raw = read_catalog().get("providers", [])
    return [item for item in raw if isinstance(item, dict)]


def default_provider_id() -> str:
    """id площадки по умолчанию из каталога."""
    return str(read_catalog().get("default", "hyperbolic"))


def get_provider(provider_id: str) -> dict[str, Any] | None:
    """Карточка площадки по id или None."""
    for card in providers():
        if str(card.get("id", "")) == provider_id:
            return card
    return None


def get_provider_model(provider_id: str, model_id: str) -> dict[str, Any] | None:
    """Карточка модели внутри площадки по id или None."""
    card = get_provider(provider_id)
    if card is None:
        return None
    for model in card.get("models", []) or []:
        if isinstance(model, dict) and str(model.get("id", "")) == model_id:
            return model
    return None


def _env_key() -> str | None:
    value = os.environ.get("LLM_API_KEY")
    if value and value.strip():
        return value.strip()
    return None


def _file_key() -> str | None:
    path = _secret_path()
    if not path.is_file():
        return None
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def load_key() -> str | None:
    """Ключ: непустая LLM_API_KEY окружения, затем память процесса, затем файл."""
    env = _env_key()
    if env is not None:
        return env
    if _memory_key:
        return _memory_key
    return _file_key()


def key_source() -> str:
    """Источник ключа: 'env', 'file' или 'none' (для UI — признак, не секрет)."""
    if _env_key() is not None:
        return "env"
    if _memory_key or _file_key() is not None:
        return "file"
    return "none"


def save_key(value: str) -> None:
    """Атомарно записать секрет в data/secrets/llm_api_key и в память процесса.

    Пустая строка игнорируется — поле «не менять» в UI не стирает ключ.
    """
    global _memory_key
    value = (value or "").strip()
    if not value:
        return
    folder = _secrets_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = _secret_path()
    tmp = target.with_name(SECRET_NAME + ".tmp")
    tmp.write_text(value, encoding="utf-8")
    os.replace(tmp, target)
    _memory_key = value


def reset_key() -> None:
    """Удалить файл секрета и память процесса.

    env-источник не трогается: при непустой LLM_API_KEY key_source() останется 'env'.
    """
    global _memory_key
    with _lock:
        _memory_key = None
        try:
            _secret_path().unlink(missing_ok=True)
        except OSError:
            pass


def load_env_file() -> None:
    """Прочитать корневой .env (если есть) в os.environ, не перезаписывая заданное.

    Удобство для start.ps1. Из HTTP не вызывается и сам .env не переписывается.
    """
    path = _root() / ".env"
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key not in os.environ:
            os.environ[key] = value
