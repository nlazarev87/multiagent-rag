"""Реестр локальных чат-моделей.

Карточки моделей лежат в config/models.json, файлы сканируются в data/models/*.gguf.
Реестр совмещает два источника: статичные метаданные из конфига и наличие файлов
на диске. Неизвестный .gguf превращается в fallback-карточку, поэтому модель не
исчезает из списка, а лишь отмечается как отсутствующая (available=false).
"""

import json
import os
import re
from pathlib import Path
from typing import Any, TypedDict

import providers
import settings

# Каталоги эмбеддингов/реранкеров и служебные не являются чат-моделями.
IGNORED_DIRS = {"embedding", "reranker", ".cache"}
# Шард вида <base>-00001-of-00002.gguf группируется по base.
_SHARD_RE = re.compile(r"^(?P<base>.+)-(?P<index>\d{5})-of-(?P<total>\d{5})\.gguf$")


class ModelCard(TypedDict, total=False):
    """Карточка чат-модели. available вычисляется по файлам на диске."""

    id: str
    name: str
    quant: str
    files: list[str]
    size_bytes: int
    sha256: list[str]
    description: str
    pros: list[str]
    cons: list[str]
    resources: dict[str, Any]
    license: str
    source: str
    available: bool


def _root() -> Path:
    return settings._root()


def _config_dir() -> Path:
    return settings._config_dir()


def _models_dir() -> Path:
    override = os.environ.get("MODELS_DIR")
    if override:
        return Path(override)
    return _root() / "data" / "models"


def _ui_dir() -> Path:
    return _root() / "data" / "ui"


def _read_config() -> dict[str, Any]:
    path = _config_dir() / "models.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_models() -> list[dict[str, Any]]:
    return _read_config().get("models", [])


def default_model_id() -> str:
    """Идентификатор модели по умолчанию из config/models.json."""
    return _read_config().get("default", "qvikhr")


def _read_model_json() -> dict[str, Any]:
    """Выбор из data/ui/model.json. Битый JSON или не-словарь → {}."""
    path = _ui_dir() / "model.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def selected_model_id() -> str | None:
    """id выбранной модели из data/ui/model.json, или None."""
    value = _read_model_json().get("model_id")
    return str(value) if value else None


def selected_backend() -> str:
    """Текущий backend выбора: 'local' | 'remote'. Старый файл без backend = local."""
    backend = _read_model_json().get("backend")
    return backend if backend in ("local", "remote") else "local"


def selected_provider() -> tuple[str | None, str | None]:
    """Операторский выбор площадки: (provider_id, base_url), каждый может быть None."""
    data = _read_model_json()
    provider_id = data.get("provider_id")
    base_url = data.get("base_url")
    return (str(provider_id) if provider_id else None, str(base_url) if base_url else None)


def save_selected_model(
    model_id: str,
    backend: str = "local",
    provider_id: str | None = None,
    base_url: str | None = None,
) -> None:
    """Атомарно сохранить выбор модели в data/ui/model.json.

    Одноаргументный вызов (его делает load_model) пишет backend="local".
    Поля оператора (provider_id, base_url) пишет та же функция в тот же файл.
    """
    payload: dict[str, Any] = {"model_id": model_id, "backend": backend}
    if provider_id:
        payload["provider_id"] = provider_id
    if base_url:
        payload["base_url"] = base_url
    folder = _ui_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "model.json"
    tmp = target.with_name("model.json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)


def startup_model() -> tuple[str, str | None]:
    """Путь и id модели для старта.

    Явный remote — без GGUF и без LLM_MODEL_PATH (путь пустой, id внешней модели).
    Иначе локальная цепочка: выбранный model_id (если GGUF на диске) -> env
    LLM_MODEL_PATH -> default реестра; битый/пустой файл попадает в эту цепочку.
    Признак remote смотри отдельно через selected_backend(): пустой путь бывает и
    у remote, и когда локальной модели нет совсем.
    """
    if selected_backend() == "remote":
        return "", selected_model_id()
    selected = selected_model_id()
    if selected:
        card = get_model(selected)
        if card is not None and card.get("available"):
            primary = primary_file(card)
            if primary is not None:
                return str(primary), selected
    env_path = os.environ.get("LLM_MODEL_PATH")
    if env_path:
        return env_path, None
    default_id = default_model_id()
    card = get_model(default_id)
    if card is not None and card.get("available"):
        primary = primary_file(card)
        if primary is not None:
            return str(primary), default_id
    return "", None


def _safe_filename(name: str) -> bool:
    """Только простое имя файла: без пути, .., диска и пустых значений."""
    if not isinstance(name, str) or not name:
        return False
    if name in (".", ".."):
        return False
    try:
        path = Path(name)
    except (OSError, ValueError):
        return False
    if path.is_absolute() or path.name != name:
        return False
    return True


def _resolve_file(filename: str) -> Path | None:
    """Путь к файлу модели внутри data/models или None, если имя опасно/symlink."""
    if not _safe_filename(filename):
        return None
    models = _models_dir()
    path = models / filename
    if path.is_symlink():
        return None
    resolved = path.resolve()
    if resolved.parent != models.resolve():
        return None
    return resolved


def _scan_files() -> dict[str, Path]:
    """Безопасные существующие .gguf в корне data/models: имя -> путь."""
    found: dict[str, Path] = {}
    models = _models_dir()
    if not models.is_dir():
        return found
    for path in models.glob("*.gguf"):
        if not path.is_file() or path.is_symlink():
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        found[path.name] = path
    return found


def _build_card(raw: dict[str, Any]) -> ModelCard:
    files = [str(f) for f in raw.get("files", []) if _safe_filename(str(f))]
    return ModelCard(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        quant=str(raw.get("quant", "")),
        files=files,
        size_bytes=int(raw.get("size_bytes", 0)),
        sha256=[str(h) for h in raw.get("sha256", [])],
        description=str(raw.get("description", "")),
        pros=[str(p) for p in raw.get("pros", [])],
        cons=[str(c) for c in raw.get("cons", [])],
        resources=dict(raw.get("resources", {}) or {}),
        license=str(raw.get("license", "")),
        source=str(raw.get("source", "")),
        available=False,
    )


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "unknown"


def _fallback_cards(files: dict[str, Path]) -> list[ModelCard]:
    """Неизвестные .gguf собираются в карточки, шарды группируются по базовому имени."""
    grouped: dict[str, list[tuple[str, Path]]] = {}
    for name, path in files.items():
        match = _SHARD_RE.match(name)
        key = match.group("base") if match else Path(name).stem
        grouped.setdefault(key, []).append((name, path))
    cards: list[ModelCard] = []
    for key in sorted(grouped):
        entries = sorted(grouped[key])
        names = [name for name, _ in entries]
        total = sum(path.stat().st_size for _, path in entries)
        cards.append(
            ModelCard(
                id=_slugify(key),
                name=key,
                quant="",
                files=names,
                size_bytes=total,
                sha256=[],
                description="Неизвестный локальный GGUF (нет карточки в config/models.json).",
                pros=[],
                cons=[],
                resources={},
                license="unknown",
                source="",
                available=True,
            )
        )
    return cards


def list_models() -> list[ModelCard]:
    """Все чат-модели: карточки из конфига плюс fallback для неизвестных GGUF.

    Отсутствующий файл даёт available=false, но карточка остаётся в списке.
    """
    files = _scan_files()
    cards: list[ModelCard] = []
    seen: set[str] = set()
    for raw in _raw_models():
        card = _build_card(raw)
        if not card["id"] or card["id"] in seen:
            continue
        seen.add(card["id"])
        card["available"] = bool(card["files"]) and all(f in files for f in card["files"])
        cards.append(card)
        for f in card["files"]:
            files.pop(f, None)
    cards.extend(_fallback_cards(files))
    return cards


def list_external_models() -> list[dict[str, Any]]:
    """Карточки внешних моделей выбранной площадки из config/providers.json."""
    provider_id, _base_url = selected_provider()
    provider_id = provider_id or providers.default_provider_id()
    card = providers.get_provider(provider_id)
    if card is None:
        return []
    result: list[dict[str, Any]] = []
    for model in card.get("models", []) or []:
        if not isinstance(model, dict) or not model.get("id"):
            continue
        result.append(
            {
                "id": str(model["id"]),
                "name": str(model.get("name") or model["id"]),
                "backend": "remote",
                "context": int(model.get("context", 0) or 0),
                "provider_id": provider_id,
                "price_in": model.get("price_in"),
                "price_out": model.get("price_out"),
                "reasoning": bool(model.get("reasoning")),
                "available": True,
            }
        )
    return result


def get_model(model_id: str) -> ModelCard | None:
    """Карточка модели по id или None, если такой модели нет."""
    for card in list_models():
        if card["id"] == model_id:
            return card
    return None


def primary_file(card: ModelCard) -> Path | None:
    """Первый файл модели (для многотомных моделей это первый шард)."""
    files = card.get("files") or []
    if not files:
        return None
    path = _resolve_file(files[0])
    if path is None or not path.exists():
        return None
    return path
