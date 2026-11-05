"""Локальная модель на процессоре. Числовую модель для поиска считает индекс, не этот модуль.

Видеокарта не используется. Файл 7B рядом с 1.5B не удалять: start.ps1 big его ждёт.
"""

import concurrent.futures
import contextvars
import os
import threading
from pathlib import Path
from typing import Any, cast

from settings import runtime

CONTEXT = 4096
_llm = None
loaded = False
_load_lock = threading.Lock()
_run_lock = threading.Lock()
# Повтор должен стартовать, пока предыдущий вызов ещё сидит в своём потоке.
# Одного работника на это не хватает: вторая попытка стояла бы в очереди и не началась.
_llm_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="llm-timeout"
)


def _n_ctx():
    return runtime().get("n_ctx", CONTEXT)


def load():
    """Открыть GGUF один раз, на CPU, с контекстом из runtime."""
    global _llm, loaded
    if _llm is None:
        with _load_lock:
            if _llm is None:
                from llama_cpp import Llama, LlamaRAMCache

                model = Llama(
                    model_path=os.environ["LLM_MODEL_PATH"],
                    n_ctx=_n_ctx(),
                    n_threads=int(
                        os.environ.get("LLM_THREADS", max(1, (os.cpu_count() or 2) // 2))
                    ),
                    n_gpu_layers=0,
                    verbose=False,
                )
                model.set_cache(LlamaRAMCache(capacity_bytes=256 << 20))
                _llm = model
    loaded = True


def count_tokens(text):
    """Число токенов модели. Нужно, чтобы промпт уложился в бюджет."""
    load()
    model = _llm
    if model is None:
        raise AttributeError("'NoneType' object has no attribute 'tokenize'")
    with _run_lock:
        return len(model.tokenize(text.encode("utf-8"), add_bos=False))


def model_name():
    """Имя файла модели без суффикса. Пусто, если путь не задан."""
    return Path(os.environ.get("LLM_MODEL_PATH", "")).stem


def _complete_sync(system, user, max_tokens, examples, usage_sink):
    """Тело ответа. Вызывается из соседнего потока и само не смотрит на предел времени."""
    load()
    data = runtime()
    if max_tokens is None:
        max_tokens = data.get("max_tokens", 200)
    temperature = data.get("temperature", 0.0)
    messages = [{"role": "system", "content": system}]
    for question, reply in examples:
        messages += [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]
    messages.append({"role": "user", "content": user})
    model = _llm
    if model is None:
        raise AttributeError("'NoneType' object has no attribute 'create_chat_completion'")
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
