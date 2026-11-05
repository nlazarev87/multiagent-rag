"""Локальная модель на процессоре. Числовую модель для поиска считает индекс, не этот модуль.

Видеокарта не используется. Файл 7B рядом с 1.5B не удалять: start.ps1 big его ждёт.
"""

import concurrent.futures
import contextvars
import os
import threading
from pathlib import Path
from typing import Any, cast

import model_registry
from settings import runtime

CONTEXT = 4096

# Состояния модели.
UNLOADED = "unloaded"
LOADING = "loading"
READY = "ready"
STOPPING = "stopping"
ERROR = "error"

# Сколько ждать завершения генерации перед выгрузкой/переключением.
_BUSY_TIMEOUT = 15.0

_llm = None
loaded = False
_state = UNLOADED
_model_id = None
_model_name = ""
_model_path = ""

_state_lock = threading.Lock()
_load_lock = threading.Lock()
_run_lock = threading.Lock()

# Повтор должен стартовать, пока предыдущий вызов ещё сидит в своём потоке.
_llm_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="llm-timeout"
)


class ModelBusy(RuntimeError):
    """Модель занята: идёт генерация или переключение/выгрузка."""


class ModelError(RuntimeError):
    """Ошибка загрузки или выгрузки модели."""


def _n_ctx():
    return runtime().get("n_ctx", CONTEXT)


def _set_state(state):
    global _state
    with _state_lock:
        _state = state


def _get_state():
    with _state_lock:
        return _state


def _set_identity(model_id, name, path):
    global _model_id, _model_name, _model_path
    with _state_lock:
        _model_id = model_id
        _model_name = name
        _model_path = path


def _assign_llm(model):
    global _llm, loaded
    _llm = model
    loaded = model is not None


def _build_model(path):
    """Создать экземпляр Llama на CPU с кэшем и параметрами из runtime."""
    from llama_cpp import Llama, LlamaRAMCache

    model = Llama(
        model_path=path,
        n_ctx=_n_ctx(),
        n_threads=int(os.environ.get("LLM_THREADS", max(1, (os.cpu_count() or 2) // 2))),
        n_gpu_layers=0,
        verbose=False,
    )
    model.set_cache(LlamaRAMCache(capacity_bytes=256 << 20))
    return model


def _resolve_path(path, model_id):
    """Путь к GGUF: явный path, либо первый шард из реестра по model_id."""
    if path:
        return str(path), model_id
    if model_id:
        card = model_registry.get_model(model_id)
        if card is None:
            raise ModelError(f"неизвестная модель: {model_id}")
        primary = model_registry.primary_file(card)
        if primary is None:
            raise ModelError(f"модель {model_id} недоступна: нет файла")
        return str(primary), model_id
    return "", None


def _capture_model():
    """Текущий экземпляр модели; типизированная ошибка при неготовности."""
    state = _get_state()
    if state == LOADING:
        raise ModelBusy("модель загружается или переключается")
    if state == STOPPING:
        raise ModelBusy("модель выгружается")
    if state == ERROR:
        raise ModelError("модель в состоянии ошибки")
    if _llm is None:
        raise ModelError("модель не загружена")
    return _llm


def load():
    """Открыть GGUF один раз: выбранная модель -> env LLM_MODEL_PATH -> default."""
    if _llm is None:
        with _load_lock:
            if _llm is None:
                path, model_id = model_registry.startup_model()
                if not path:
                    raise ModelError("модель не найдена: нет выбранной, env или файла по умолчанию")
                _set_state(LOADING)
                try:
                    _assign_llm(_build_model(path))
                except Exception:
                    _set_state(ERROR)
                    raise
                _set_identity(model_id, Path(path).stem, path)
                _set_state(READY)


def count_tokens(text):
    """Число токенов модели. Нужно, чтобы промпт уложился в бюджет."""
    load()
    model = _capture_model()
    with _run_lock:
        return len(model.tokenize(text.encode("utf-8"), add_bos=False))


def model_name():
    """Имя файла текущей модели (из состояния; fallback на env)."""
    with _state_lock:
        name = _model_name
    if name:
        return name
    return Path(os.environ.get("LLM_MODEL_PATH", "")).stem


def current_model_id():
    """id текущей модели из состояния (None, если не из реестра)."""
    with _state_lock:
        return _model_id


def status():
    """Состояние и идентичность текущей модели."""
    with _state_lock:
        return {
            "state": _state,
            "model_id": _model_id,
            "model_name": _model_name,
            "model_path": _model_path,
        }


def load_model(path=None, model_id=None):
    """Загрузить модель (заменить текущую). При ошибке новой — откат на старую."""
    resolved_path, resolved_id = _resolve_path(path, model_id)
    if not resolved_path:
        raise ModelError("не задан путь к модели")
    return _replace_model(resolved_path, resolved_id)


def switch_model(path=None, model_id=None):
    """Переключиться на новую модель. Синоним load_model."""
    return load_model(path=path, model_id=model_id)


def unload():
    """Закрыть и выгрузить текущую модель."""
    if not _run_lock.acquire(timeout=_BUSY_TIMEOUT):
        raise ModelBusy("модель занята генерацией")
    try:
        _unload_locked()
    finally:
        _run_lock.release()


def _unload_locked():
    model = _llm
    if model is None:
        _set_state(UNLOADED)
        _set_identity(None, "", "")
        _assign_llm(None)
        return
    _set_state(STOPPING)
    try:
        model.close()
    finally:
        _set_identity(None, "", "")
        _assign_llm(None)
        _set_state(UNLOADED)


def _replace_model(path, model_id):
    """Создать новую модель и подменить старую (с откатом при ошибке)."""
    if not _run_lock.acquire(timeout=_BUSY_TIMEOUT):
        raise ModelBusy("модель занята генерацией")
    try:
        old_model = _llm
        _set_state(LOADING)
        try:
            new_model = _build_model(path)
        except Exception as exc:
            if old_model is not None:
                _set_state(READY)
            else:
                _set_state(ERROR)
            raise ModelError(f"не удалось загрузить модель: {exc}") from exc
        if old_model is not None:
            try:
                old_model.close()
            except Exception:
                pass
        _assign_llm(new_model)
        _set_identity(model_id, Path(path).stem, path)
        _set_state(READY)
    finally:
        _run_lock.release()


def _complete_sync(system, user, max_tokens, examples, usage_sink):
    """Тело ответа. Вызывается из соседнего потока и само не смотрит на предел времени."""
    load()
    model = _capture_model()
    data = runtime()
    if max_tokens is None:
        max_tokens = data.get("max_tokens", 200)
    temperature = data.get("temperature", 0.0)
    messages = [{"role": "system", "content": system}]
    for question, reply in examples:
        messages += [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]
    messages.append({"role": "user", "content": user})
    with _run_lock:
        reply = cast(Any, model).create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    usage = reply.get("usage") if isinstance(reply, dict) else None
    if usage_sink is not None and isinstance(usage, dict):
        usage_sink["tokens_in"] = usage.get("prompt_tokens")
        usage_sink["tokens_out"] = usage.get("completion_tokens")
    return reply["choices"][0]["message"]["content"].strip()


def complete(system, user, max_tokens=None, examples=(), *, usage_sink=None, timeout_s=None):
    """Ответ модели. Примеры идут парами user/assistant перед вопросом.

    usage_sink, если передан, получает tokens_in и tokens_out из ответа модели.
    Старый вызов без этого аргумента возвращает только текст.
    Предел времени — timeouts.llm_ms. Повтор один, если в конфиге retries=1.
    Поток с моделью после предела не обрывается: он дописывает ответ уже без слушателя.
    """
    limits = runtime().get("timeouts") or {}
    if timeout_s is None:
        timeout_s = limits.get("llm_ms", 90000) / 1000
    retries = limits.get("retries", 1)
    last_error: BaseException | None = None
    for attempt in range(retries + 1):
        ctx = contextvars.copy_context()
        future = _llm_executor.submit(
            ctx.run, _complete_sync, system, user, max_tokens, examples, usage_sink
        )
        try:
            return future.result(timeout=timeout_s)
        except TimeoutError:
            if future.done():
                raise
            last_error = TimeoutError(f"llm timeout after {timeout_s}s ({retries + 1} attempts)")
            if attempt < retries:
                continue
            raise last_error
    if not isinstance(last_error, BaseException):
        raise TypeError("exceptions must derive from BaseException")
    raise last_error
