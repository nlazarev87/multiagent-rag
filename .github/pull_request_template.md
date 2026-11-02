## Что делает этот PR

Fixes #

## Чек-лист
- [ ] Один issue — один PR.
- [ ] `pytest -m "not slow and not holdout"` зелёный.
- [ ] Не добавлены `from .agents import _*` в coordinator.
- [ ] Новый порог → config + docs/thresholds.md (или обоснован).
- [ ] Для поиска приложен `git diff last.json`.
- [ ] data/prompts/*.json не менялись (или приложен e2e).

## Метрики (для поисковых PR)
| Метрика | До | После | Δ |
|---|---|---|---|
| search_hit1_dev | | | |
| search_mrr_dev | | | |
| search_hit4_holdout | | | |
| search_latency_ms | | | |

## Проверено вручную

## Что НЕ входит

## Заметки для ревьюера
