# multiagent-rag

[![CI](https://github.com/nlazarev87/multiagent-rag/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/nlazarev87/multiagent-rag/actions/workflows/ci.yml)

Локальный поиск по своим документам, без интернета. Ответ пишет Qwen2.5-1.5B на процессоре. Похожесть текста считает модель `multilingual-e5-small`. Поиск идёт двумя списками, Chroma и поиск по словам, и складывает их в один. Сеть для ответа не нужна.

## Запуск

Из корня репозитория:

```powershell
.\start.ps1          # 1.5B, http://127.0.0.1:8000
.\start.ps1 restart  # остановить процесс на порту 8000 и запустить снова
.\start.ps1 big      # та же команда, но модель 7B, если файл уже лежит в data/models
```

Один вопрос из консоли, без страницы. Без `--user` команда отказывает. Пароль лежит в `CLI_PASSWORD` и не печатается.

```powershell
$env:PYTHONPATH = "src"
$env:CLI_PASSWORD = "пароль"
python -m cli --user ИМЯ ingest --kb ИД data/inbox
python -m cli --user ИМЯ сколько насосов в цехе
```

Пока индекс строится, страница открывается сразу. Список диалогов берётся из сохранённого файла. Дерево документов обновляется, когда `/ready` отвечает 200.

## Как устроен вопрос

Вопрос «какие документы загружены» отвечает списком имён файлов и модель не вызывает. Остальные вопросы идут по цепочке:

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

Проверка может вернуть ответ на переписывание не больше двух раз. Если после этого ответ не подтверждён, человек видит «В документах нет ответа.» Вопрос «сколько» может остаться с числом из обзорной строки таблицы.

## Где что лежит

| Путь | Зачем |
| --- | --- |
| `data/inbox` | Исходные файлы. В индексе они лежат плоским списком, папки только на странице. |
| `data/chroma` | Индекс для поиска по смыслу. |
| `data/ui/workspace.json` | Диалоги, оценки 1–5 и дерево папок. В git не входит. |
| `data/models` | Файлы моделей. Файл 7B не удалять. |
| `config/` | Лимиты, когда отвечать списком файлов, словарь проверки чисел. |
| `data/prompts/` | Текст, который видит модель перед ответом, и примеры. |
| `src/` | Код. Названий и фактов из ваших документов здесь быть не должно. |

## Части системы

- [Загрузка документов](docs/ingest.md)
- [Индекс и поиск](docs/store.md)
- [Сборка вопроса](docs/coordinator.md)
- [Выбор прошлого хода](docs/select.md)
- [Уточнение вопроса](docs/clarify.md)
- [Ответ](docs/answer.md)
- [Проверка ответа](docs/check.md)
- [Страница и запросы](docs/api.md)
- [Диалоги и папки](docs/workspace.md)
- [Страница](docs/ui.md)
- [Модель](docs/llm.md)
- [Настройки и тексты для модели](docs/settings.md)
- [Как измерять качество](docs/eval.md)

## Что нельзя ломать

Не записывать в `src/` имена файлов и факты из них. То, что зависит от конкретных документов, живёт в `config/` и `data/prompts/`.

Не опускать нижнюю границу в `tests/eval/floors.json` и не передавать `--write-floors` / `--raise-floors`, пока об этом не попросили и проверка не написала, что порог пройден. `tests/eval/last.json` и `pytest tests/test_floors.py` качество заново не меряют: они сравнивают уже записанные числа.

После правки `src/`, `config/` или `data/prompts/` заново измерить то, что сдвинулось. Как именно — в [docs/eval.md](docs/eval.md).

## Запуск через Docker

Нужны Docker Desktop (Windows/macOS) или Docker Engine (Linux) и Docker Compose.

### Требования

1. Модели в `data/models/`:
   - `multilingual-e5-small/` (около 2.1 GB)
   - `qwen2.5-1.5b-instruct-q4_k_m.gguf` (около 1.0 GB)

   Модели не входят в образ, их монтирует volume.

2. Файлы документов в `data/inbox/` (`.txt`, `.md`, `.doc`, `.docx`, `.pdf`, `.xlsx`).

### Запуск

```bash
docker compose up --build -d
```

Первая сборка занимает 10–20 минут: ставятся torch, sentence-transformers и llama-cpp-python.

### Проверка

```bash
curl http://localhost:8000/ready
```

`{"ready": true}` и код 200 — модель и индекс готовы. Код 503 с `elapsed_sec` и `eta_sec` — ещё грузится. Первый прогрев может занять больше пяти минут.

Страница на `http://localhost:8000`.

### Данные

Каталоги на этой машине:

- `data/models/` — только чтение.
- `data/inbox/` — документы.
- `data/chroma/` — индекс.
- `data/audit/` — журнал.
- `data/ui/`, `data/users/` — диалоги и пользователи.

### Остановка

```bash
docker compose down
```
