## Что делает этот PR

<1–2 строки сути>

Closes #<issue>
Milestone: Wave <N>

## Почему

<мотивация/контекст>

## Что изменено

- <файл/модуль> — <что>

## Проверка (приложить фактические выводы)

- [ ] `pytest -m "not slow and not holdout"` — зелёный (N passed)
- [ ] `python -m compileall -q src/`
- [ ] `ruff check src/ tests/`
- [ ] `mypy src/` (если менялись типы/контракты)
- [ ] Не добавлены `from .agents import _*` в coordinator.
- [ ] Новый порог → config + docs/thresholds.md (или обосновано).
- [ ] Для поиска приложен `git diff last.json`.
- [ ] data/prompts/*.json не менялись (или приложен e2e).

## Метрики поиска (если трогали поиск/промпт)

| Метрика | До | После | Δ |
|---|---|---|---|
| search_hit1_dev | | | |
| search_mrr_dev | | | |
| search_hit4_holdout | | | |
| search_latency_ms | | | |

## Что НЕ входит

## Заметки для ревьюера
