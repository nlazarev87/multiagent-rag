# Архитектура

## Карта модулей
| Модуль | Что | Кого берёт | Кто берёт |
|---|---|---|---|
| settings | config + prompts | — | почти все |
| permit | подпись допуска | — | access |
| auth | люди, сессии, права | settings | kb, audit, access, api, cli, trees |
| audit | append-only журнал | auth | api, cli |
| kb | реестр баз | auth, store | access, api, cli, trees |
| dialog | ходы в памяти | — | coordinator, workspace |
| workspace | диалоги на диске | dialog | api, trees |
| trees | дерево папок | auth, kb, workspace | api |
| ingest | файл → куски | settings, store | api, cli; store обратно |
| store | Chroma + BM25 | settings, ingest | agents, coordinator, api, cli |
| llm | модель | settings | agents |
| agents | select/clarify/search/answer/check | llm, settings, store | coordinator |
| coordinator | граф | agents, dialog, settings, store | api, cli |
| access | какие базы, слияние | auth, kb, permit, store | api, cli |

**Цикл:** ingest ↔ store, спрятан в функциях. Разрывать — Wave 2 TypedDict.

## Граф
select → clarify → search → answer → check → (answer|search|finish) → end

## Поля state
query, dialog_id, work, clear, chunks, attempts, answer, status, feedback, sources, document_names.

Наружу: answer, status, document_names, sources.

## Контракт search_chunks
search_chunks(query, limit=4, document_names=None, debug=False) -> list[Chunk]|dict

Chunk: id, text, document_name, chunk_index, section, kind, group, head.

⚠️ document_names=None = весь индекс. Пустой список — тоже весь индекс. Если нужно «ничего» — вернуть [] до вызова.
