# multiagent-rag

Локальный офлайн-поиск по своим документам. Ответ пишет Qwen2.5-1.5B на CPU. Эмбеддинги — `multilingual-e5-small`. Индекс — Chroma и лексический поиск, их ранги склеивает RRF. Сеть для ответа не нужна.

## Запуск

Из корня репозитория:

```powershell
.\start.ps1          # 1.5B, http://127.0.0.1:8000
.\start.ps1 restart  # остановить процесс на порту 8000 и запустить снова
.\start.ps1 big      # та же команда, но модель 7B, если файл уже лежит в data/models
```

Один вопрос из консоли, без интерфейса:

```powershell
$env:PYTHONPATH = "src"
python -m cli ingest data/inbox
python -m cli сколько насосов в цехе
```

Пока индекс строится, страница открывается сразу. Список диалогов берётся из сохранённого файла, дерево документов обновляется, когда `/ready` отвечает 200.

## Как устроен вопрос

Вопрос про состав корпуса («какие документы загружены») отвечает списком имён файлов и модель не вызывает. Остальные вопросы идут по цепочке:

```mermaid
flowchart LR
  query[Query] --> catalog{Catalog}
  catalog -->|names| done[Answer]
  catalog -->|content| select[select]
  select --> clarify[clarify]
  clarify --> search[search]
  search --> answer[answer]
  answer --> check[check]
  check -->|retry| answer
  check -->|new docs| search
  check --> finish[finish]
```

`check` может вернуть ответ на переписывание не больше двух раз. Если после этого ответ не подтверждён, пользователь видит «В документах нет ответа.» Вопрос «сколько» может остаться с числом из обзорной строки таблицы.

## Где что лежит

| Путь | Зачем |
| --- | --- |
| `data/inbox` | Исходные файлы. В индексе они плоские, папки только в интерфейсе. |
| `data/chroma` | Векторный индекс. |
| `data/ui/workspace.json` | Диалоги, оценки 1–5 и дерево папок. В git не входит. |
| `data/models` | GGUF и `multilingual-e5-small`. Файл 7B не удалять. |
| `config/` | Лимиты, маршруты каталога, словарь проверки. |
| `data/prompts/` | Системный текст ответа и примеры. |
| `src/` | Код пайплайна. Фактов из документов здесь быть не должно. |

## Компоненты

- [Загрузка документов](docs/ingest.md)
- [Индекс и поиск](docs/store.md)
- [Координатор](docs/coordinator.md)
- [Выбор истории](docs/select.md)
- [Уточнение вопроса](docs/clarify.md)
- [Ответ](docs/answer.md)
- [Проверка ответа](docs/check.md)
- [HTTP API](docs/api.md)
- [Диалоги и дерево](docs/workspace.md)
- [Интерфейс](docs/ui.md)
- [Модель](docs/llm.md)
- [Настройки и промпты](docs/settings.md)
- [Метрики](docs/eval.md)

## Что нельзя ломать

Не записывать в `src/` имена файлов корпуса и факты из них. Поведение, которое зависит от документов, живёт в `config/` и `data/prompts/`.

Не снижать полы в `tests/eval/floors.json` и не передавать `--write-floors` / `--raise-floors`, пока об этом не попросили и GATE не зелёный. `tests/eval/last.json` и `pytest tests/test_floors.py` качество заново не меряют.

После правки `src/`, `config/` или `data/prompts/` прогнать scorecard затронутых узлов. Как именно — в [docs/eval.md](docs/eval.md).
