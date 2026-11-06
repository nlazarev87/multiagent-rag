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


class TraceStep(TypedDict, total=False):
    """Один шаг трассы обработки вопроса.

    input и output — подробные данные шага (не только сводки). Поля
    подчиняются обрезке координатора: строка не длиннее 4000 символов,
    превью фрагментов — 600 символов и не больше 8, трасса целиком — 64 КБ.
    """

    node: str
    started_at: str
    duration_ms: float
    input: dict[str, Any]
    output: dict[str, Any]
    attempt: int
    timed_out: bool


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


class ProviderModel(TypedDict, total=False):
    """Одна модель внутри площадки (config/providers.json)."""

    id: str
    name: str
    context: int
    price_in: float
    price_out: float
    max_tokens: int
    temperature: float
    reasoning: bool
    chars_per_token: float


class ProviderCard(TypedDict, total=False):
    """Карточка площадки (config/providers.json)."""

    id: str
    name: str
    base_url: str
    requires_key: bool
    http_timeout_ms: int
    models: list[ProviderModel]


class ProviderSettings(TypedDict, total=False):
    """Операторский выбор площадки (пишется в data/ui/model.json рядом с выбором модели)."""

    provider_id: str
    base_url: str
    model_id: str
