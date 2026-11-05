"""Имена и порядок параметров публичных функций.

Падает, если функцию переименовали, параметр переименовали,
обязательный параметр добавили или убрали, или известные
необязательные сдвинулись. Новый необязательный параметр в конце
список не ломает: позиционные вызовы остаются на своих местах.
"""

import inspect

import pytest

import agents
import store

# имя, функция, обязательные, известные необязательные
CONTRACTS = [
    ("select_agent", agents.select_agent, ["query", "turns"], []),
    ("clarify_agent", agents.clarify_agent, ["query", "work_turns"], []),
    ("search_agent", agents.search_agent, ["clear_query"], ["document_names"]),
    (
        "answer_agent",
        agents.answer_agent,
        ["query", "clear_query", "chunks", "work_turns"],
        ["feedback", "features", "usage_sink"],
    ),
    ("check_agent", agents.check_agent, ["answer", "chunks"], ["query", "known"]),
    (
        "build_prompt",
        agents.build_prompt,
        ["query", "chunks"],
        ["previous", "feedback", "count", "budget"],
    ),
    (
        "search_chunks",
        store.search_chunks,
        ["clear_query"],
        ["limit", "document_names", "debug", "features"],
    ),
]


@pytest.mark.parametrize(
    "name, fn, expected_required, expected_optional",
    CONTRACTS,
    ids=[row[0] for row in CONTRACTS],
)
def test_public_signature(name, fn, expected_required, expected_optional):
    """Префикс сигнатуры совпадает с тем, как функции зовут позиционно."""
    params = list(inspect.signature(fn).parameters.values())
    required = [item.name for item in params if item.default is inspect.Parameter.empty]
    optional = [item.name for item in params if item.default is not inspect.Parameter.empty]
    assert required == expected_required, (
        f"{name}: обязательные параметры изменились\n"
        f"  было: {expected_required}\n"
        f"  стало: {required}"
    )
    assert optional[: len(expected_optional)] == expected_optional, (
        f"{name}: известные необязательные параметры сдвинулись или переименованы\n"
        f"  было: {expected_optional}\n"
        f"  стало: {optional}"
    )
