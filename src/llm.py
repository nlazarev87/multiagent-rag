"""Локальная модель на процессоре. Числовую модель для поиска считает индекс, не этот модуль.

Видеокарта не используется. Файл 7B рядом с 1.5B не удалять: start.ps1 big его ждёт.
"""

import concurrent.futures
import contextvars
import os
import re
import threading
from pathlib import Path
from typing import Any, cast

import llm_remote
import model_registry
import providers
from llm_remote import ProviderError
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


def _remote_active() -> bool:
    """Выбран ли remote-бэкенд (отдельное чтение data/ui/model.json)."""
    return model_registry.selected_backend() == "remote"


def _remote_settings(
    provider_id: str | None = None,
    base_url: str | None = None,
    model_id: str | None = None,
) -> dict[str, Any] | None:
    """Настройки remote из выбора (или переданных значений) + каталога. None, если не настроено.

    Свой адрес (не из каталога, например Ollama/vLLM) ключа не требует; неизвестный
    provider_id с заданными адресом и id модели не отбрасывается.
    """
    model_id = (model_id if model_id is not None else model_registry.selected_model_id()) or ""
    if provider_id is None:
        provider_id, base_url = model_registry.selected_provider()
        provider_id = provider_id or providers.default_provider_id()
    card = providers.get_provider(provider_id)
    if card is None and not (base_url and model_id):
        return None
    card_base = str((card or {}).get("base_url", ""))
    custom_endpoint = base_url is not None and base_url.rstrip("/") != card_base.rstrip("/")
    api_key = providers.load_key()
    requires_key = card is not None and not custom_endpoint and bool(card.get("requires_key"))
    if requires_key and not api_key:
        return None
    base_url = base_url or card_base
    if not base_url or not model_id:
        return None
    model_card = providers.get_provider_model(provider_id, model_id) if card is not None else None
    model_card = model_card or {}
    data = runtime()
    max_tokens = int(model_card.get("max_tokens") or data.get("max_tokens", 200))
    raw_temperature = model_card.get("temperature")
    if raw_temperature is None:
        raw_temperature = data.get("temperature", 0.0)
    temperature = float(raw_temperature)
    return {
        "base_url": base_url,
        "api_key": api_key or "",
        "model": model_id,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "http_timeout_ms": int((card or {}).get("http_timeout_ms", 60000)),
        "retries": int((data.get("timeouts") or {}).get("retries", 1)),
        "chars_per_token": model_card.get("chars_per_token"),
    }


def _estimate_tokens(text: str) -> int:
    """Консервативная оценка токенов для remote: len//2 или chars_per_token из карточки."""
    settings = _remote_settings()
    chars = (settings or {}).get("chars_per_token")
    if isinstance(chars, (int, float)) and float(chars) > 0:
        return max(1, int(len(text) / float(chars)))
    return max(1, len(text) // 2)


def complete_remote(
    provider_id: str | None,
    base_url: str | None,
    model_id: str,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Проверочный/прямой вызов внешней модели по явным настройкам (не сохранённым).

    Возвращает результат llm_remote.complete как есть — не бросает на
    finish_reason=length, поэтому годится для «Проверить подключение»:
    200 от площадки означает, что связь и ключ работают.
    """
    settings = _remote_settings(provider_id=provider_id, base_url=base_url, model_id=model_id)
    if settings is None:
        raise ModelError("внешняя модель не настроена")
    settings["max_tokens"] = 16
    settings["no_retry"] = True
    return llm_remote.complete(settings, messages)


def _add_usage(usage_sink, tokens_in, tokens_out):
    """Прибавить токены к общему счётчику (сумма всех вызовов за вопрос)."""
    if tokens_in is not None:
        usage_sink["tokens_in"] = (usage_sink.get("tokens_in") or 0) + int(tokens_in)
    if tokens_out is not None:
        usage_sink["tokens_out"] = (usage_sink.get("tokens_out") or 0) + int(tokens_out)


def _mark_remote_ready() -> None:
    """Состояние READY для remote без загрузки GGUF."""
    global loaded
    model_id = model_registry.selected_model_id() or ""
    _set_state(READY)
    _set_identity(model_id, model_id.rsplit("/", 1)[-1] if model_id else "", "")
    loaded = True


def load():
    """Открыть GGUF один раз: выбранная модель -> env LLM_MODEL_PATH -> default."""
    if _remote_active():
        _mark_remote_ready()
        return
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
    if _remote_active():
        return _estimate_tokens(text)
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


def model_display_name() -> str:
    """Человекочитаемое имя текущей модели (имя карточки или stem файла)."""
    with _state_lock:
        model_id = _model_id
        name = _model_name
    if model_id:
        card = model_registry.get_model(model_id)
        if card is not None and card.get("name"):
            return card["name"]
    if name:
        return name
    return Path(os.environ.get("LLM_MODEL_PATH", "")).stem


def current_model_id():
    """id текущей модели из состояния (None, если не из реестра)."""
    with _state_lock:
        return _model_id


def status():
    """Состояние и идентичность текущей модели."""
    backend = "remote" if _remote_active() else "local"
    with _state_lock:
        return {
            "state": _state,
            "model_id": _model_id,
            "model_name": _model_name,
            "model_path": _model_path,
            "backend": backend,
        }


def load_model(path=None, model_id=None):
    """Загрузить модель (заменить текущую). При ошибке новой — откат на старую."""
    resolved_path, resolved_id = _resolve_path(path, model_id)
    if not resolved_path:
        raise ModelError("не задан путь к модели")
    _replace_model(resolved_path, resolved_id)
    if resolved_id:
        model_registry.save_selected_model(resolved_id)


def switch_model(path=None, model_id=None, backend="local", provider_id=None, base_url=None):
    """Переключиться на модель. remote — сохранить выбор без GGUF; local — load_model."""
    if backend == "remote":
        return _switch_remote(model_id, provider_id, base_url)
    return load_model(path=path, model_id=model_id)


def _switch_remote(model_id, provider_id, base_url):
    """Переключение на remote: выгрузить локальную GGUF, сохранить выбор одним вызовом."""
    global loaded
    if not _run_lock.acquire(timeout=_BUSY_TIMEOUT):
        raise ModelBusy("модель занята генерацией")
    try:
        if _llm is not None:
            _set_state(STOPPING)
            try:
                _llm.close()
            except Exception:
                pass
            _assign_llm(None)
        model_registry.save_selected_model(
            model_id, backend="remote", provider_id=provider_id, base_url=base_url
        )
        _set_identity(model_id, model_id.rsplit("/", 1)[-1] if model_id else "", "")
        _set_state(READY)
        loaded = True
    finally:
        _run_lock.release()


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


def _strip_thinking(text: str) -> str:
    """Remove reasoning artifacts from a model reply."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    markers = (" response", " response", " response")
    last = -1
    tail = text
    for marker in markers:
        pos = text.rfind(marker)
        if pos > last:
            last = pos
            tail = text[pos + len(marker) :]
    text = tail
    for tag in ("</think>", "<think>"):
        text = text.replace(tag, "")
    return text.strip()


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
        _add_usage(usage_sink, usage.get("prompt_tokens"), usage.get("completion_tokens"))
    return _strip_thinking(reply["choices"][0]["message"]["content"])


def _complete_remote_locked(system, user, max_tokens, examples, usage_sink, no_retry):
    """Тело remote-ответа. Вызывается при удерживаемом _run_lock (снимок бэкенда один)."""
    messages = [{"role": "system", "content": system}]
    for question, reply in examples:
        messages += [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]
    messages.append({"role": "user", "content": user})
    settings = _remote_settings()
    if settings is None:
        raise ProviderError(
            None, "", "внешняя модель не настроена: укажите площадку, ключ и модель"
        )
    if max_tokens is not None:
        settings["max_tokens"] = max_tokens
    settings["no_retry"] = no_retry
    result = llm_remote.complete(settings, messages)
    text = _strip_thinking(result["text"])
    if not text:
        if result.get("finish_reason") == "length":
            raise ProviderError(
                None,
                settings["model"],
                "лимит ответа исчерпан рассуждением — поднимите потолок модели или выберите модель без reasoning",
            )
        raise ProviderError(None, settings["model"], "пустой ответ площадки")
    if usage_sink is not None:
        _add_usage(usage_sink, result.get("tokens_in"), result.get("tokens_out"))
    return text


def complete(
    system, user, max_tokens=None, examples=(), *, usage_sink=None, timeout_s=None, no_retry=False
):
    """Ответ модели. Примеры идут парами user/assistant перед вопросом.

    usage_sink, если передан, получает сумму tokens_in/tokens_out всех вызовов.
    Выбор remote/local читается один раз под _run_lock и по нему выбирается ветка.
    remote идёт обычным вызовом с таймаутом httpx (повторы — внутри llm_remote;
    no_retry — для «Проверить подключение»). Локальный путь не меняется.
    """
    with _run_lock:
        if _remote_active():
            return _complete_remote_locked(system, user, max_tokens, examples, usage_sink, no_retry)
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
