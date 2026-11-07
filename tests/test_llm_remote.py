"""Тесты OpenAI-совместимого клиента (src/llm_remote.py) — mock transport."""

import json

import httpx
import pytest

import llm_remote
from llm_remote import ProviderError

SETTINGS = {
    "base_url": "https://api.hyperbolic.xyz/v1",
    "api_key": "hk-secret",
    "model": "Qwen/Qwen2.5-72B-Instruct",
    "max_tokens": 200,
    "temperature": 0.0,
    "http_timeout_ms": 60000,
    "retries": 1,
}

MESSAGES = [{"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def _clean_client():
    llm_remote._client = None
    yield
    llm_remote._client = None


def _client(handler):
    llm_remote._client = httpx.Client(transport=httpx.MockTransport(handler))


def _ok(payload):
    return httpx.Response(200, json=payload)


def test_200_string_content_and_usage():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        captured["auth"] = request.headers.get("Authorization")
        return _ok(
            {
                "choices": [{"message": {"content": " Ответ "}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            }
        )

    _client(handler)
    result = llm_remote.complete(SETTINGS, MESSAGES)
    assert result["text"] == " Ответ "
    assert result["tokens_in"] == 10
    assert result["tokens_out"] == 3
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["body"]["stream"] is False
    assert captured["body"]["model"] == SETTINGS["model"]
    assert captured["auth"] == "Bearer hk-secret"


def test_200_list_content_flattened():
    def handler(request):
        return _ok(
            {
                "choices": [
                    {
                        "message": {
                            "content": [
                                {"type": "text", "text": "часть1 "},
                                {"type": "text", "text": "часть2"},
                            ]
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        )

    _client(handler)
    assert llm_remote.complete(SETTINGS, MESSAGES)["text"] == "часть1 часть2"


def test_200_null_content_with_reasoning_returns_reasoning():
    def handler(request):
        return _ok(
            {
                "choices": [
                    {
                        "message": {"content": None, "reasoning_content": "думаю..."},
                        "finish_reason": "length",
                    }
                ]
            }
        )

    _client(handler)
    result = llm_remote.complete(SETTINGS, MESSAGES)
    assert result["text"] == ""
    assert result["reasoning"] == "думаю..."
    assert result["finish_reason"] == "length"


def test_401_no_retry():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert info.value.status == 401
    assert info.value.retryable is False
    assert "401" in info.value.text


def test_402_insufficient_funds():
    def handler(request):
        return httpx.Response(
            402, json={"error": {"code": "insufficient_quota", "message": "out of credits"}}
        )

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert info.value.status == 402
    assert "квота площадки исчерпана" in info.value.text


def test_429_retries_then_ok():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": {"message": "rate limited"}})
        return _ok({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    _client(handler)
    result = llm_remote.complete(SETTINGS, MESSAGES)
    assert result["text"] == "ok"
    assert calls["n"] == 2


def test_429_retry_after_long_no_retry():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(
            429, json={"error": {"message": "slow down"}}, headers={"Retry-After": "60"}
        )

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert info.value.status == 429
    assert calls["n"] == 1  # не повторили


def test_500_retries_then_ok():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={"error": {"message": "boom"}})
        return _ok({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})

    _client(handler)
    assert llm_remote.complete(SETTINGS, MESSAGES)["text"] == "ok"
    assert calls["n"] == 2


def test_502_html_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(502, text="<html>Bad Gateway</html>")

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert info.value.status == 502
    assert calls["n"] == 1  # не-JSON не повторяем


def test_network_error_retried_then_fail():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        raise httpx.ConnectError("boom")

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert info.value.status is None
    assert calls["n"] == 2  # один повтор


def test_200_non_json_body():
    def handler(request):
        return httpx.Response(200, text="not json")

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert "не JSON" in info.value.text


def test_empty_choices():
    def handler(request):
        return _ok({"choices": []})

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert "пустой ответ" in info.value.text


def test_content_filter():
    def handler(request):
        return _ok({"choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]})

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert "фильтром" in info.value.text


def test_unexpected_tool_calls():
    def handler(request):
        return _ok({"choices": [{"message": {"content": "", "tool_calls": [{"id": "1"}]}}]})

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert "tool_calls" in info.value.text


def test_key_sanitized_from_error_text():
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad Bearer hk-secret key"}})

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert "hk-secret" not in info.value.text
    assert "Bearer" not in info.value.text


def test_chat_url_full_path_not_doubled():
    full = dict(SETTINGS, base_url="https://api.hyperbolic.xyz/v1/chat/completions")
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        return _ok({"choices": [{"message": {"content": "x"}, "finish_reason": "stop"}]})

    _client(handler)
    llm_remote.complete(full, MESSAGES)
    assert captured["url"].endswith("/chat/completions")
    assert "/chat/completions/chat/completions" not in captured["url"]


def test_error_includes_url_and_server_message():
    def handler(request):
        return httpx.Response(
            404, json={"error": {"message": "This inference endpoint has been decommissioned"}}
        )

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert "chat/completions" in info.value.text
    assert "decommissioned" in info.value.text


def test_503_retry_after_long_not_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(
            503, json={"error": {"message": "overloaded"}}, headers={"Retry-After": "60"}
        )

    _client(handler)
    with pytest.raises(ProviderError) as info:
        llm_remote.complete(SETTINGS, MESSAGES)
    assert info.value.status == 503
    assert calls["n"] == 1
    assert "временно недоступна" in info.value.text
