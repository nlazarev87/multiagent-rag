# План работ команды агентов (multiagent-rag)

> Перепроверено 2026-11-05 после крупного обновления репозитория.
> Задачи выполняются командой по правилам из этого файла (раздел «Команда и координация»).

## 0. Нерешённые вопросы (согласовать до старта)

- QVikhr: берём официальный вариант `noreasoning` (другого GGUF нет)?
- RusMind: лицензия `rusmind-license`, файл 3.19 ГиБ — ок?
- Оценки: один тумблер «включены/выключены» (кнопки + показ) или два отдельных?
- Trace: показывать промпт и тексты фрагментов с обрезкой или только сводки?
- Права: `manage_users` для вкладок «Модель»/«Чат» или новое `manage_system`?

## 1. Что изменилось в репозитории (перепроверка 05.11)

- **Wave 6 закрыт:** Docker (Dockerfile, docker-compose, start.sh), ruff + mypy + pre-commit, rate limiting (slowapi, 10/min на /query + /v1/query), дедупликация чанков, K1/B в runtime.json, аудит-UI.
- **Wave 7 UI закрыт (#185–196):** тёмная тема, дизайн-токены, компоненты, админка. Но адаптивности НЕТ: в src/web/index.html (2777 строк) ноль @media, колонки и админка на фиксированных px.
- **Новое окружение:** requirements.txt пополнился slowapi/ruff/mypy/uvicorn/pre-commit; появились mypy.ini, ruff.toml, .pre-commit-config.yaml.
- **Свежие коммиты (05.11):** docker-compose монтирует весь ./data (rw), модели остаются :ro; src/kb.py считает пути баз как data/kbs/<id> (машинонезависимо, не хранит Windows-пути); в Dockerfile добавлен EMBED_PATH и нормализация start.sh в LF.
- **Модели:** по-прежнему только qwen2.5-1.5b и qwen2.5-7b (2 шарда). QVikhr и RusMind НЕ скачаны.
- **llm.py:** по-прежнему env LLM_MODEL_PATH + глобальный _llm; unload/switch/status нет.
- **trace:** только summary (input_summary/output_summary) уходит в audit; в ход диалога не сохраняется.
- **Настроек trace/оценок нет:** ratings всегда видны, PATCH ratings всегда разрешён.

## 2. Потоки работ и приоритет

1. **Wave 10 — Responsive UI** (сейчас главное для пользователя; фундамент для 8.6/9.4/9.5).
2. **Wave 8 — Models** (реестр, скачивание, горячая замена, API, админка «Модель»).
3. **Wave 9 — Trace & chat settings** (цепочка обработки, настройки видимости и оценок).

## 3. Wave 8 — Model runtime (модели)

- **8.1 Реестр моделей** · size M · effort low · config/models.json + src/model_registry.py + tests/test_model_registry.py. Что: карточки Qwen1.5/Qwen7B(2 шарда)/QVikhr/RusMind (id, файлы, размер, SHA-256, описание, плюсы/минусы, ресурсы, лицензия, источник); сканирование data/models/*.gguf; группировка шардов; fallback для неизвестного GGUF; игнор embedding/reranker каталогов; защита от ../ и symlink. Depends: —.
- **8.2 Скачивание моделей** · size M · effort off/low · scripts/fetch_models.py + docs/llm.md + tests/test_fetch_models.py. Что: резюм-скачивание с Hugging Face, проверка размера и SHA-256, атомарное переименование, режимы --check/--model/--force, проверка места на диске; реально скачать QVikhr (1107408608 B, sha 425495de…48f2) и RusMind (3427880800 B, sha 99684d0f…d01cb). Depends: 8.1. Бинарники в git не идут.
- **8.3 Смоук загрузки** · size S · effort low · tests/test_models_smoke.py (slow) + docs/llm.md. Что: загрузить каждую модель в отдельном процессе через реальный llm.complete(system, user, examples=...) и llm.count_tokens() (а не только Llama.create_chat_completion), один вопрос, замерить загрузку/ответ; подтвердить chat-template (QVikhr /no_think, Gemma4) и gemma4 на llama-cpp-python==0.3.36. Depends: 8.2. Стоп-сигнал для 8.4–8.6 при провале.
- **8.4 llm lifecycle** · size L · effort max · src/llm.py + tests/test_llm.py. Что: status()/load_model()/unload()/switch_model(); состояния unloaded/loading/ready/stopping/error; Llama.close(); откат на старую модель при ошибке; ModelBusy при активной генерации (ждать до 15 с); complete/count_tokens захватывают экземпляр; идентичность модели (model_name/current_model_id) берётся из состояния llm, а не из env; для 7B передавать первый шард. Depends: 8.3.
- **8.5a API моделей** · size M · effort high · src/api.py + tests/test_api.py. Что: GET /admin/models, GET /admin/models/status, POST /admin/models/switch|load|unload; /ready отдаёт отдельную причину 503 «model_loading» при переключении; ошибки без путей; audit; новые эндпоинты вне лимита slowapi. Depends: 8.4.
- **8.5b Выбор по умолчанию + лаунчеры** · size S · effort low · src/model_registry.py + start.ps1 + start.sh + Dockerfile + docker-compose.yml + docs. Что: сохранение выбора в data/ui/model.json (data/models в Docker смонтирован :ro); приоритет selected → LLM_MODEL_PATH → QVikhr; _files_ok/_warm/startup используют выбранную модель; start.ps1/start.sh/Dockerfile/compose по умолчанию QVikhr (скачать при отсутствии на хосте); EMBED_PATH и embedding-модель не трогаем (реестр только для chat-GGUF); дефолтный/выбранный путь работает и при монтировании ./data целиком. Depends: 8.4.
- **8.6 Админка «Модель»** · size M · effort high · src/web/index.html + tests/test_api.py. Что: вкладка, текущая модель + статус, выпадающий список с описаниями/ресурсами/лицензией, кнопки Загрузить/Остановить/Применить, поллинг только в loading/stopping. Depends: 8.5a + 8.5b + Wave 10 (фундамент UI).

## 4. Wave 9 — Trace & chat settings

- **9.1 Подробный trace узлов** · size M · effort high · src/coordinator.py + src/pipeline_types.py + tests/test_coordinator.py + tests/test_contracts.py. Что: TraceStep TypedDict; шаги catalog (всегда) и route; input/output у select/clarify/search/answer/check/finish; промпт/токены в answer; превью фрагментов; обрезка (строка 4000, фрагмент 600, 8 фрагментов, 64 КБ, truncated). Результат coordinator.run() не меняется; partial trace сохраняется и при таймауте/исключении (try/finally). Depends: —.
- **9.2 Сохранение trace** · size M · effort low · src/api.py + src/workspace.py + tests/test_api.py + tests/test_workspace.py. Что: workspace.append_turn(trace=None) → turn.trace + trace_version; api.query берёт scope.trace_steps; /ui и /ui/dialogs/{id} отдают trace; старые ходы без trace читаются. Depends: 9.1 + 8.5a (api.py).
- **9.3 Настройки чата + серверный гейтинг** · size M · effort high · src/preferences.py + src/api.py + tests/test_preferences.py + tests/test_api.py. Что: data/ui/settings.json {trace_visible:true, ratings_enabled:true}; атомарная запись; /ui добавляет settings; trace_visible=false вырезает turn.trace; ratings_enabled=false вырезает ratings и PATCH ratings → 403; GET/PUT /admin/ui-settings. Depends: 9.2.
- **9.4 Trace UI в чате** · size M · effort high · src/web/index.html + tests/test_api.py. Что: details.trace под ответом, вложенные details по шагам с блоками Вход/Выход; по умолчанию свёрнуто; без innerHTML. Depends: 9.2 + 9.3 + Wave 10 (фундамент UI).
- **9.5 Админка «Чат»** · size M · effort high · src/web/index.html + tests/test_api.py. Что: вкладка «Чат» с тумблерами trace/оценки; пояснения; сохранение; чат обновляется без перезагрузки. Depends: 9.3 + 9.4.

## 5. Wave 10 — Responsive UI (NEW)

Контекст: в index.html нет ни одного @media; главный shell — фиксированные колонки (--left:260px, --mid:380px), #admin — фиксированная навигация 216px, таблицы внутри .table-card{overflow:hidden} обрезаются, аудит/доступы имеют фиксированные ширины. Цель — резиновая (fluid) + адаптивная вёрстка без горизонтального скролла body; «Управление» — в первую очередь.

- **10.1 Fluid shell + breakpoints** · size M · effort high · src/web/index.html + tests/test_ui_responsive.py. Что: заменить фиксированные --left/--mid на clamp()/minmax(); ввести @media-брейкпоинты (1280/1080/900/720/560); саши получают min/max, а JS bindSash клампится к ширине окна (ниже брейкпоинта колонки сворачиваются/отключаются); ниже 900 — 2 панели (диалоги в overlay/дровере), ниже 720 — одна панель с табами; нет горизонтального скролла body. AC: 1440/1280/1024/800/600 без overflow; перетаскивание сашей в min/max; тёмная тема.
- **10.2 Админка: навигация/шапка/статус-бар** · size M · effort high · src/web/index.html. Что: #admin 216px+1fr → адаптивно (ниже 900 — навигация сверху/икон-рейл); admin-header и toolbar переносятся; #status переносится/скроллится; «Назад» всегда доступен. AC: админка корректна на 800/600 ширине.
- **10.3 Таблицы + аудит + матрица доступов** · size M · effort high · src/web/index.html. Что: .table-card overflow:hidden → overflow-x:auto; фиксированные ширины аудита (time/kind/who) → flex + перенос/чипы; .kb-matrix — горизонтальный скролл + sticky первая колонка; таблица пользователей стеком на узких экранах. AC: ничего не обрезается, скролл появляется где нужно, строки переносятся.
- **10.4 Карточки ролей/групп + тумблеры** · size S · effort low · src/web/index.html. Что: .rc-head/.rc-actions переносятся; .perm-grid остаётся auto-fill и проверен min; .access-row и label переносятся; длинные имена — ellipsis. AC: роли/группы/доступы не вылезают на узкой ширине.
- **10.5 Тёмная тема + доступность на узких ширинах** · size M · effort high · src/web/index.html. Что: проверить токены тёмной темы на всех брейкпоинтах; focus-visible; touch-цели ≥ 28px; увеличенная зона сашей; пустые состояния по центру. AC: фокус видим, тёмная тема корректна, попадание по сашу/кнопкам комфортно.
- **10.6 Регрессионные тесты + документация** · size S · effort low · tests/test_ui_responsive.py + docs/ui.md. Что: grep-тесты (в index.html есть @media; таблицы в прокручиваемом контейнере, а не overflow:hidden; нет фиксированного min-width окна); сохранить запрет innerHTML в test_api.py; описать брейкпоинты в docs/ui.md. AC: CI зелёный; docs/ui.md обновлён.

## 6. Команда и координация

Работу выполняет команда агентов (lead + исполнители), не один агент. Правила ниже обязательны для всех участников.

### 6.1 Состав и зоны ответственности

| Роль | Отвечает за | Write-scopes (файлы) |
|---|---|---|
| lead (этот агент) | план, оркестрация, ревью финального diff, гейты, мерж, публикация issue/PR | — (только ревью) |
| models-backend | Wave 8 бэкенд: реестр, скачивание, llm lifecycle, API моделей | src/llm.py, src/model_registry.py, config/, scripts/, часть src/api.py (8.5a) |
| trace-settings | Wave 9 бэкенд: trace узлов, сохранение в ходе, настройки чата | src/coordinator.py, src/workspace.py, src/preferences.py, часть src/api.py |
| ui | Wave 10 + 8.6 + 9.4 + 9.5 (весь UI) | src/web/index.html |
| qa | тесты новых модулей, смоук моделей, grep-проверки | tests/ |

### 6.2 Механика координации

- Одна общая доска (team_task): каждая из 17 задач — отдельная карточка с write_scopes и blocked_by.
- Исполнитель берёт задачу через claim (CAS по revision), выполняет, затем complete.
- Зависимости повторяют «Depends on» из разделов 3–5; заблокированные задачи не берутся.
- Write-scopes непересекающиеся: два агента не пишут один файл одновременно.

### 6.3 Правила исполнения (AGENTS.md + этот файл)

1. Один issue = одна ветка = один PR. Ветка: wave8|wave9|wave10/<slug>.
2. Минимальный diff; не править чужие зоны.
3. Перед сдачей — локально pytest -m "not slow and not holdout".
4. После PR lead ревьюит дифф, гоняет гейты раздела 8, мержит.

### 6.4 Последовательность (бутылочные горлышки)

- **src/web/index.html** — один владелец (ui), строго: 10.1→10.6 → 8.6 → 9.4 → 9.5.
- **src/api.py** — строго: 8.5a → 9.2 → 9.3.
- Бэкенд без UI идёт параллельно: 8.1→8.2→8.3→8.4; 9.1 (coordinator) параллельно.

### 6.5 Уровень рассуждений (reasoning_effort)

- Задаёт lead ОДИН раз при делегировании (off/low/high/max) по таблице раздела 7.
- Внутри задачи уровень не меняется; эскалация (low → high) — вручную при провале гейта.
- Сессия (lead) запускается на High.

## 7. Маршрутизация reasoning (стоимость без потери качества)

Принцип: качество держат проверки и приёмка, а не максимальный reasoning. Уровень задаётся ОДИН раз при делегировании (reasoning_effort: off/low/high/max); эскалация — вручную при провале гейта.

| Задача | Уровень |
|---|---|
| 8.1 Реестр, 8.2 Скачивание, 8.3 Смоук, 8.5b Выбор+лаунчеры, 9.2 Сохранение trace, 10.4 Карточки, 10.6 Тесты | low/off |
| 8.5a API, 8.6 Админка «Модель», 9.1 Trace, 9.3 Настройки, 9.4 Trace UI, 9.5 Админка «Чат», 10.1/10.2/10.3/10.5 UI | high |
| 8.4 llm lifecycle | max |

## 8. Гейты качества (обязательные, не зависят от уровня reasoning)

1. pytest -m "not slow and not holdout" — зелёный перед merge.
2. python -m compileall -q src/.
3. ruff check src/ tests/ (конфиг ruff.toml).
4. mypy src/ --ignore-missing-imports --check-untyped-defs (конфиг mypy.ini).
5. tests/test_contracts.py — при изменении публичного контракта.
6. В index.html нет innerHTML/insertAdjacentHTML (проверяет tests/test_api.py).
7. Не трогать data/prompts/*.json без scorecard; не опускать floors.json.
8. Смоук-гейт 8.3: QVikhr и RusMind реально загружаются.
9. Lead ревьюит финальный diff по AGENTS.md и acceptance criteria.

## 9. Бюджет (оценка)

С добавлением Wave 10 (18 задач) и маршрутизацией reasoning:

- Реалистичный (25M вход / 6M выход): ~$32 peak / ~$16 off-peak.
- С запасом на переделки: ~$40–55 peak / ~$20–30 off-peak.

Механические задачи (8.1/8.2/8.3/8.5b/9.2/10.4/10.6) — на low/off; сложные (8.4/8.5/9.x/10.1-10.3/10.5) — high/max.
## 11. Риски и принятые решения

- **Docker:** ./data монтируется rw целиком, поверх — data/models :ro → выбор модели и настройки пишем в data/ui/. Скачивание моделей — только на хосте.
- **Здоровье Docker:** /ready во время переключения кратко 503; healthcheck допускает (5×30 с), но UI не должен показывать «готово» в момент switch.
- **Таймауты/лимиты trace как константы**, а не в runtime.json, чтобы не трогать docs/thresholds.md; значения документируем в docs/llm.md и docs/ui.md.
- **n_ctx остаётся 4096 для всех моделей** (промпт-бюджет ~1500 токенов): память предсказуема; отдельное n_ctx per model — только если понадобится.
- **Payload /ui с trace:** trace хранится в ходе с обрезкой 64 КБ; если вырастет — вынесем в отдельный lazy-эндпоинт.
- **Проверка адаптивности без браузера:** автотесты grep-уровня + ручная визуальная проверка на 1440/1024/800/600. Playwright не добавляем (против «один файл, без сборки»).
- **slowapi:** лимит остаётся только на /query и /v1/query; статус модели не лимитируется (поллинг).
- **7B:** реестр отдаёт первый шард как primary; llama.cpp сам подхватывает второй.