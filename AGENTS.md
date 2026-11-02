# AGENTS.md — правила для AI-агента

## Главное
**Один issue — один PR.** Затрагивает >2 модулей — разбей на подзадачи.

## Нельзя
1. Импортировать приватные имена из agents.py в coordinator.py.
2. Менять data/prompts/*.json без scorecard.py и `pytest -m "not slow and not holdout"`.
3. Поднимать floors.json без явного запроса.
4. Менять search_chunks поведение по умолчанию — только через debug=True или features.*.
5. Дублировать «код» (store._names, agents._codes, agents._anchors).

## Обязательно
1. Новый порог → config/runtime.json + docs/thresholds.md.
2. Поиск/промпт/эвристика → git diff last.json до/после.
3. Новый публичный контракт → TypedDict в src/types.py + tests/test_contracts.py.
4. Каждый PR — pytest локально.

## Формат
1. Issue по шаблону task.md.
2. Проверить Depends on.
3. Ветка wave<N>/<slug>.
4. Минимальный diff.
5. PR по шаблону.
