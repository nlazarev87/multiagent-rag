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
3. Новый публичный контракт → TypedDict в src/pipeline_types.py + tests/test_contracts.py.
4. Каждый PR — pytest локально.

## Формат
1. Issue по шаблону task.md.
2. Проверить Depends on.
3. Ветка wave<N>/<slug>.
4. Минимальный diff.
5. PR по шаблону.

## Протокол git/GitHub (обязателен для всех агентов)

### Пуш в main — только через PR
1. Никаких прямых коммитов в `main`. Любое изменение — в ветке `wave<N>/<slug>`.
2. Один issue — одна ветка — один PR.
3. Один раз настроить хуки: `pre-commit install` (ставит pre-commit + commit-msg + pre-push).

### Коммит
Формат сообщения (обязателен, проверяется хуком `commit-msg`):

```
<type>(<scope>): <краткое описание> (#<issue>)

Зачем: <1–2 строки — проблема/мотивация>
Что:
- <изменение 1>
- <изменение 2>
Как проверено: pytest -m "not slow and not holdout" — N passed
Closes #<issue>       # или "Refs #<issue>" для промежуточных коммитов
Milestone: Wave <N>
```

- `<type>`: `feat | fix | refactor | perf | test | docs | chore | ci | build`.
- `<scope>`: модуль (`llm`, `api`, `web`, `coordinator`, `model_registry`, `docs`…).
- `(#<issue>)` в заголовке и `Closes/Fixes/Resolves/Refs #<issue>` в теле — обязательны (кроме `Merge`/`Revert`).
- Хук `commit-msg` не пропустит сообщение без `#<issue>` в заголовке и без ссылки на issue в теле.

### PR
1. PR только из ветки `wave<N>/<slug>` в `main`.
2. Заполнить шаблон PR полностью: `Closes #N`, `Milestone`, блок «Проверка» с фактическими выводами.
3. Если PR трогал поиск/промпт/эвристику — приложить таблицу Δ метрик (scorecard) и `git diff last.json`.
4. Локально перед PR: `pytest -m "not slow and not holdout"` + `ruff check src/ tests/` + `mypy src/` (если менялись типы/контракты).

### Задачи и вехи
1. Любое изменение кода — сначала issue (шаблон task.md), потом ветка и PR.
2. Задача закрывается ключевым словом в PR/коммите: `Closes #N` / `Fixes #N` / `Resolves #N`.
3. Веха закрывается автоматически, когда все её issue закрыты.

### Гейты перед merge (CI на PR)
1. `pytest -m "not slow and not holdout"` — зелёный (job `pytest (fast)`).
2. `python -m compileall -q src/`.
3. `ruff check src/ tests/` (ruff.toml) и `mypy src/` (mypy.ini).
4. `pr-lint` — в PR есть `Closes/Fixes/Resolves #N` и строка `Milestone:`.
5. Метрики поиска — scorecard (Δ до/после), если трогали поиск/промпт (в CI — nightly/вручную; в PR — таблица Δ).
6. Модельные (`slow`/`holdout`) тесты — локально при изменении `src/llm.py`/`src/model_registry.py`; в CI — nightly/вручную.
