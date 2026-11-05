# Audit log

## Хранилище

`data/audit/log.sqlite` — append-only. Хеш-цепочка (`prev_hash`, `row_hash`), запрет `UPDATE`/`DELETE` через триггеры.

## Ротация (#180)

При `log.sqlite > 100 MB` — переименование в `log-YYYY-MM.sqlite`, новый `log.sqlite`. Уникальные имена: `-2`, `-3`, если за месяц дважды.

- `list_events(file=...)` — читает конкретный файл (текущий или архив).
- `get_event(id, file=...)` — читает из конкретного файла.
- `get_event(id)` без `file` — **первое совпадение**: текущий, потом архивы.

## Коллизии id (#222)

В каждом файле свой `AUTOINCREMENT`. `id=1` может быть в текущем и в архиве. **Без `file` нельзя гарантировать нужную строку.**

- UI (#223) **обязан** передавать `file` из `list_events` (dropdown файлов).
- `api.py` — везде, где `get_event(id)` без `file`, добавить `file` из query-параметра, если он известен.

## `trace_json` (#180)

В `payload` записи `query` — `trace_json` (полный trace, ~1.3 KB). Отключается через `config/runtime.json::audit.trace_json = false`.
