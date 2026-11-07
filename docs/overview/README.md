# Документация multiagent-rag

Точка входа в документацию. Документы упорядочены от общего к частному.

## Для технических партнёров — начните здесь

1. [Обзор](00-overview.md) — что это, зачем, как запустить.
2. [Архитектура](01-architecture.md) — компоненты, потоки данных, обоснования решений.
3. [Data Science Deep Dive](02-data-science-deep-dive.md) — retrieval, эмбеддинги, промпты, верификация, метрики.
4. [Эксплуатация](03-operations.md) — запуск, Docker, мониторинг, ограничения, roadmap.
5. [Глоссарий](glossary.md) — термины.

## Детали по компонентам

| Документ | О чём |
|---|---|
| [ingest.md](ingest.md) | Загрузка документов |
| [store.md](store.md) | Индекс и поиск |
| [coordinator.md](coordinator.md) | Сборка вопроса |
| [select.md](select.md) | Выбор прошлого хода |
| [clarify.md](clarify.md) | Уточнение вопроса |
| [answer.md](answer.md) | Ответ |
| [check.md](check.md) | Проверка ответа |
| [api.md](api.md) | Страница и запросы |
| [workspace.md](workspace.md) | Диалоги и папки |
| [ui.md](ui.md) | Страница |
| [llm.md](llm.md) | Модель |
| [settings.md](settings.md) | Настройки и тексты для модели |
| [eval.md](eval.md) | Как измерять качество |