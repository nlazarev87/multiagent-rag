"""OpenAI-совместимый клиент чат-дополнений внешней площадки.

Не зависит от providers.py: на вход — словарь настроек (base_url, api_key, model,
max_tokens, temperature, http_timeout_ms, retries, no_retry) и список сообщений.
ProviderError определён здесь один раз; llm.py его пробрасывает, /query ловит.
"""

import json
from typing import Any

import httpx

_CONNECT_TIMEOUT = 5.0
_RETRY_HEADER = "Retry-After"

_client: httpx.Client | None = None


class ProviderError(RuntimeError):
    """Ошибка внешней площадки.

    Поля: status (HTTP-код или None), model, text (уже очищенный от ключа),
    retryable (можно ли повторить в пределах timeouts.retries).
    """

    def __init__(self, status: int | None, model: str, text: str, retryable: bool = False):
        super().__init__(text)
        self.status = status
        self.model = model
        self.text = text
        self.retryable = retryable


def _client_get() -> httpx.Client:
    """Один httpx.Client на процесс; редиректы выключены (не уносить Authorization)."""
    global _client
    if _client is None:
        _client = httpx.Client(follow_redirects=False)
    return _client


def _chat_url(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _sanitize(text: str, api_key: str) -> str:
    """Вырезать ключ и префикс Bearer, чтобы тело ошибки не утекло в журнал."""
    if not isinstance(text, str):
        return ""
    if api_key:
        text = text.replace(f"Bearer {api_key}", "")
        text = text.replace(api_key, "")
    return text


def _extract_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                value = item.get("text")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts)
    return ""


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _parse_ok(data: dict[str, Any], model: str, api_key: str) -> dict[str, Any]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError(None, model, "пустой ответ площадки")
    first = choices[0]
    if not isinstance(first, dict):
        raise ProviderError(None, model, "некорректный ответ площадки")
    message = first.get("message")
    if not isinstance(message, dict):
        message = {}
    finish_reason = first.get("finish_reason")
    finish_reason = finish_reason if isinstance(finish_reason, str) else None
    if finish_reason == "content_filter":
        raise ProviderError(None, model, "ответ заблокирован фильтром площадки")
    if message.get("tool_calls"):
        raise ProviderError(
            None, model, "площадка вернула tool_calls, а инструменты не запрашивались"
        )
    text = _sanitize(_extract_text(message), api_key)
    reasoning = message.get("reasoning_content")
    reasoning = reasoning if isinstance(reasoning, str) else None
    usage = data.get("usage")
    tokens_in = tokens_out = None
    if isinstance(usage, dict):
        tokens_in = _as_int(usage.get("prompt_tokens"))
        tokens_out = _as_int(usage.get("completion_tokens"))
    return {
        "text": text,
        "reasoning": reasoning,
        "finish_reason": finish_reason,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }


def _error_details(resp: httpx.Response) -> tuple[str, dict[str, Any] | None]:
    body = resp.text or ""
    data: dict[str, Any] | None = None
    try:
        parsed = json.loads(body)
        if isinstance(parsed, dict):
            data = parsed
    except (json.JSONDecodeError, ValueError):
        data = None
    return body, data


def _error_message(status: int, body: str, data: dict[str, Any] | None, api_key: str) -> str:
    server = ""
    code = ""
    if data is not None:
        err = data.get("error")
        if isinstance(err, dict):
            code = str(err.get("code") or err.get("type") or "")
            server = str(err.get("message") or "")
        elif isinstance(err, str):
            server = err
        elif isinstance(data.get("message"), str):
            server = data["message"]
    server = _sanitize(server, api_key).strip()
    if status == 402 or "insufficient_quota" in code.lower() or "insufficient" in server.lower():
        return "недостаточно средств на балансе площадки" + (f": {server}" if server else "")
    if status == 401:
        return "площадка отклонила ключ (HTTP 401)" + (f": {server}" if server else "")
    if status == 403:
        return "модель недоступна для этого ключа (HTTP 403)" + (f": {server}" if server else "")
    if status == 404:
        return "модель не найдена на площадке (HTTP 404)"
    if status == 413:
        return "запрос длиннее окна модели (HTTP 413)"
    if status == 422:
        return (
            ("площадка отклонила запрос (HTTP 422): " + server)
            if server
            else "площадка отклонила запрос (HTTP 422)"
        )
    if status == 429:
        return "лимит запросов площадки (HTTP 429) — попробуйте позже"
    if status is not None and status >= 500:
        return f"площадка недоступна (HTTP {status})"
    return (
        (f"ошибка площадки (HTTP {status}): " + server)
        if server
        else f"ошибка площадки (HTTP {status})"
    )


def _retry_after_seconds(resp: httpx.Response) -> int | None:
    value = resp.headers.get(_RETRY_HEADER)
    if not value:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _error_from_response(resp: httpx.Response, model: str, api_key: str) -> ProviderError:
    status = resp.status_code
    body, data = _error_details(resp)
    is_json = data is not None
    retryable = is_json and (status in (408, 429) or (status is not None and status >= 500))
    if status == 429 and is_json:
        wait = _retry_after_seconds(resp)
        if wait is not None and wait > 2:
            retryable = False
    return ProviderError(
        status, model, _error_message(status, body, data, api_key), retryable=retryable
    )


def _request(settings: dict[str, Any], messages: list[dict[str, Any]]) -> httpx.Response:
    api_key = settings.get("api_key") or ""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": settings["model"],
        "messages": messages,
        "stream": False,
        "max_tokens": settings.get("max_tokens", 200),
        "temperature": settings.get("temperature", 0.0),
    }
    read_timeout = max(1.0, float(settings.get("http_timeout_ms", 60000)) / 1000.0)
    timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT, read=read_timeout, write=read_timeout, pool=read_timeout
    )
    return _client_get().post(
        _chat_url(settings["base_url"]), headers=headers, json=payload, timeout=timeout
    )


def _complete_once(settings: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    model = settings["model"]
    api_key = settings.get("api_key") or ""
    resp = _request(settings, messages)
    if resp.status_code == 200:
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            raise ProviderError(resp.status_code, model, "некорректный ответ площадки (не JSON)")
        if not isinstance(data, dict):
            raise ProviderError(resp.status_code, model, "некорректный ответ площадки")
        return _parse_ok(data, model, api_key)
    raise _error_from_response(resp, model, api_key)


def complete(settings: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Ответ площадки. Возвращает {text, reasoning, finish_reason, tokens_in, tokens_out}.

    Повторы: готовый JSON 408/429/5xx — в пределах retries (один); готовое не-JSON тело
    (включая HTML на 502) — не повторяется; оборванное соединение — один повтор.
    no_retry=True («Проверить подключение») отключает повторы.
    """
    model = settings["model"]
    retries = int(settings.get("retries", 1))
    no_retry = bool(settings.get("no_retry", False))
    attempts = 1 if no_retry else retries + 1
    for attempt in range(attempts):
        try:
            return _complete_once(settings, messages)
        except ProviderError as exc:
            if exc.retryable and not no_retry and attempt + 1 < attempts:
                continue
            raise
        except httpx.TransportError:
            if not no_retry and attempt + 1 < attempts:
                continue
            raise ProviderError(None, model, "площадка недоступна (сеть/таймаут)")
    raise ProviderError(None, model, "площадка недоступна (сеть/таймаут)")
