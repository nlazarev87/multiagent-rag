"""Скачивание чат-моделей (GGUF) с Hugging Face.

Запуск: python scripts/fetch_models.py [--check] [--model ID] [--force]

Файл качается во временный <name>.gguf.part с резюмом через Range, затем после
проверки размера и SHA-256 атомарно переименовывается в <name>.gguf. Повторный
запуск не качает уже корректные файлы. Бинарники в git не идут.
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# id модели -> список URL (по одному на файл из config/models.json).
DOWNLOAD_URLS: dict[str, list[str]] = {
    "qvikhr": [
        "https://huggingface.co/Vikhrmodels/QVikhr-3-1.7B-Instruction-noreasoning-GGUF/resolve/main/QVikhr-3-1.7B-Instruction-noreasoning-Q4_K_M.gguf"
    ],
    "rusmind": [
        "https://huggingface.co/DICPlay/RusMind-4.7-Momentum/resolve/main/RusMind-Momentum-4.7-Q4_K_M.gguf"
    ],
}

# Запас свободного места сверх суммы скачиваемого (байт).
DISK_MARGIN = 1 << 30
_CHUNK = 1 << 20
_TIMEOUT = 60
_RETRIES = 10


def _root() -> Path:
    return Path(os.environ.get("APP_ROOT", ROOT))


def _models_dir() -> Path:
    override = os.environ.get("MODELS_DIR")
    if override:
        return Path(override)
    return _root() / "data" / "models"


def _config_dir() -> Path:
    override = os.environ.get("CONFIG_DIR")
    if override:
        return Path(override)
    return _root() / "config"


def _models() -> dict[str, dict[str, Any]]:
    path = _config_dir() / "models.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(model["id"]): model for model in data.get("models", [])}


def _file_specs(model_id: str) -> list[tuple[str, str, int, str]]:
    """Список (файл, url, размер, sha256) для модели. Только однофайловые."""
    card = _models().get(model_id)
    if card is None:
        raise ValueError(f"неизвестная модель: {model_id}")
    urls = DOWNLOAD_URLS.get(model_id) or []
    files = [str(item) for item in card.get("files", [])]
    shas = [str(item) for item in card.get("sha256", [])]
    if not urls:
        raise ValueError(f"нет URL для скачивания модели: {model_id}")
    if len(files) != len(urls):
        raise ValueError(f"число файлов и URL не совпадает: {model_id}")
    if len(files) != 1:
        raise ValueError(f"поддерживается только однофайловая модель: {model_id}")
    sha = shas[0] if shas else ""
    return [(files[0], urls[0], int(card.get("size_bytes", 0)), sha)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _status(path: Path, size: int, sha: str) -> str:
    """ok / missing / bad-size / bad-sha для файла модели."""
    if not path.exists():
        return "missing"
    if size and path.stat().st_size != size:
        return "bad-size"
    if sha and _sha256(path) != sha:
        return "bad-sha"
    return "ok"


def _free_bytes(models_dir: Path) -> int:
    return shutil.disk_usage(models_dir).free


def _ensure_space(models_dir: Path, needed: int) -> None:
    free = _free_bytes(models_dir)
    if free < needed + DISK_MARGIN:
        raise RuntimeError(f"мало места: нужно ~{needed + DISK_MARGIN} байт, свободно {free}")


def _download_file(url: str, dest: Path, part: Path, size: int, sha: str, force: bool) -> None:
    """Скачать url в dest через part, с резюмом, таймаутом и повторами."""
    if force:
        for path in (part, dest):
            if path.exists():
                path.unlink()
    for attempt in range(_RETRIES):
        # Полный .part от прошлой попытки: докачивать нечего, сразу проверяем.
        if part.exists() and size and part.stat().st_size >= size:
            if _status(part, size, sha) == "ok":
                os.replace(part, dest)
                return
            part.unlink()
        existing = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={existing}-"} if existing else {}
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
                append = response.status == 206 and existing > 0
                with part.open("ab" if append else "wb") as handle:
                    shutil.copyfileobj(response, handle, _CHUNK)
        except OSError:
            if attempt + 1 == _RETRIES:
                raise
            continue
        if size and part.stat().st_size != size:
            if attempt + 1 == _RETRIES:
                raise RuntimeError(f"неверный размер после скачивания: {part.name}")
            continue
        if sha and _sha256(part) != sha:
            raise RuntimeError(f"неверный SHA-256 после скачивания: {part.name}")
        os.replace(part, dest)
        return
    raise RuntimeError(f"не удалось скачать: {part.name}")


def _fetch_model(model_id: str, force: bool) -> list[str]:
    """Скачать файлы модели. Уже корректные файлы пропускаются."""
    models_dir = _models_dir()
    lines: list[str] = []
    for filename, url, size, sha in _file_specs(model_id):
        if filename != Path(filename).name:
            raise ValueError(f"небезопасное имя файла: {filename}")
        dest = models_dir / filename
        part = models_dir / (filename + ".part")
        if not force and _status(dest, size, sha) == "ok":
            lines.append(f"{filename}: уже на месте")
            continue
        existing = part.stat().st_size if part.exists() else 0
        _ensure_space(models_dir, max(0, size - existing))
        print(f"скачиваю {filename} ...", flush=True)
        _download_file(url, dest, part, size, sha, force)
        lines.append(f"{filename}: готово")
    return lines


def check(model_ids: list[str]) -> bool:
    """Проверить размер и SHA-256. Возвращает True, если всё ok."""
    ids = model_ids or sorted(DOWNLOAD_URLS)
    models_dir = _models_dir()
    ok = True
    for model_id in ids:
        for filename, _url, size, sha in _file_specs(model_id):
            state = _status(models_dir / filename, size, sha)
            print(f"{filename}: {state}", flush=True)
            if state != "ok":
                ok = False
    return ok


def fetch(model_ids: list[str], force: bool) -> bool:
    """Скачать файлы. Возвращает True, если все цели достигнуты."""
    ids = model_ids or sorted(DOWNLOAD_URLS)
    for model_id in ids:
        for line in _fetch_model(model_id, force):
            print(line, flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Скачивание GGUF-моделей с Hugging Face")
    parser.add_argument("--model", action="append", default=[], help="id модели (можно несколько раз)")
    parser.add_argument("--check", action="store_true", help="только проверить размер и SHA-256")
    parser.add_argument("--force", action="store_true", help="скачать заново, даже если файл корректен")
    args = parser.parse_args(argv)
    if args.check:
        return 0 if check(args.model) else 1
    try:
        fetch(args.model, args.force)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
