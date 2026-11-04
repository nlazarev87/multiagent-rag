"""Схемы пайплайна. Эти классы ничего не исполняют.

Файл лежит в `src/` и называется `types.py`. При `PYTHONPATH=src`
команда `import types` находит его раньше стандартной библиотеки.
Имена стандартного модуля копируются сразу: их читают `enum` и
`tests/test_llm.py` ещё до того, как этот файл догрузился.
Наши классы собираются при первом обращении. Иначе `import typing`
во время загрузки `re` замыкает круг.
"""
import sys

_sep = "\\" if "\\" in __file__ else "/"
_here = __file__
_stdlib_source = None
_stdlib_path = None
for _entry in sys.path:
    if not _entry:
        continue
    _candidate = _entry.rstrip("/\\") + _sep + "types.py"
    if _candidate == _here:
        continue
    try:
        with open(_candidate, encoding="utf-8") as _fh:
            _stdlib_source = _fh.read()
    except OSError:
        continue
    _stdlib_path = _candidate
    break
if _stdlib_source is None:
    raise ImportError("stdlib types.py")
_ns = {"__name__": "_stdlib_types", "__file__": _stdlib_path}
exec(compile(_stdlib_source, _stdlib_path, "exec"), _ns)
for _name, _value in _ns.items():
    if not _name.startswith("_"):
        globals()[_name] = _value
del _name, _value, _ns, _stdlib_source, _stdlib_path, _candidate, _entry, _sep, _here

_defined = False
_EXPORTS = {
    "Chunk",
    "ChunkMeta",
    "Source",
    "CheckResult",
    "Turn",
    "SelectResult",
    "GraphState",
}


def _define():
    global _defined
    if _defined:
        return
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

    globals().update(
        Chunk=Chunk,
        ChunkMeta=ChunkMeta,
        Source=Source,
        CheckResult=CheckResult,
        Turn=Turn,
        SelectResult=SelectResult,
        GraphState=GraphState,
    )
    _defined = True


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    _define()
    return globals()[name]
