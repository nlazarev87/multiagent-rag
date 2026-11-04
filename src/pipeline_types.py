"""Схемы пайплайна. Эти классы ничего не исполняют."""
from typing import Any, TypedDict


class Chunk(TypedDict, total=False):
    """Кусок, который отдаёт поиск.

    В индекс ещё пишутся group, head, checksum и version.
    Наружу поиск их не отдаёт.
    """
    id: str
    text: str
    document_name: str
    chunk_index: int
    section: str
    kind: str


class ChunkMeta(TypedDict, total=False):
    """Поля куска внутри индекса. Поиск их не возвращает."""
    document_name: str
    chunk_index: int
    checksum: str
    section: str
    kind: str
    group: str
    head: str
    version: int


class Source(TypedDict, total=False):
    """Один источник в вердикте проверки."""
    number: int
    document_name: str
    section: str
    chunk_index: int
    kb_id: str
    kb_name: str


class CheckResult(TypedDict):
    """Возврат check_agent. missing — список строк."""
    status: str
    missing: list[str]
    feedback: str
    sources: list[Source]


class Turn(TypedDict, total=False):
    """Один ход диалога в state['work']."""
    id: str
    query: str
    answer: str
    places: list[dict[str, Any]]


# select_agent возвращает список ходов, не словарь с ключом turns.
SelectResult = list[Turn]


class GraphState(TypedDict, total=False):
    """Состояние графа. Поля появляются по ходу, поэтому все необязательные."""
    query: str
    dialog_id: str
    features: dict[str, Any] | None
    trace_steps: list[dict[str, Any]]
    work: list[Turn]
    clear: str
    chunks: list[Chunk]
    document_names: list[str] | None
    search_fallback_used: bool
    attempts: int
    answer: str
    status: str
    feedback: str
    sources: list[Source]
