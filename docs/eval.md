# Метрики

Код: [tests/eval/scorecard.py](../tests/eval/scorecard.py). Короткая инструкция для агента: [.cursor/skills/scorecard/SKILL.md](../.cursor/skills/scorecard/SKILL.md). Полы: [tests/eval/floors.json](../tests/eval/floors.json).

Scorecard заново прогоняет узлы и пишет снимок в `tests/eval/last.json`.

## Что чем мерить

| Правка | Узлы |
| --- | --- |
| `src/ingest.py` | `ingest`, `search` |
| `src/store.py` | `search`, `univ` |
| `src/agents.py` | `select`, `clarify`, `search`, `check`; `answer`, если изменился путь ответа |
| `src/coordinator.py` | `coord` |
| `config/`, `data/prompts/` | `univ` и узел, чьё поведение сдвинулось |
| Неясно | `--nodes fast` |

`--nodes fast` — это `ingest`, `select`, `clarify`, `search`, `check`, `coord`, `univ`. Модель 1.5B там не отвечает.

`answer` и сквозные вопросы (`e2e`) долгие. Их гоняет `python scripts/release_check.py` перед PR: сначала утечка, подмена и guard, потом `--nodes all --holdout`.

## Инварианты

- `pytest tests/test_floors.py` сравнивает `floors.json` и `last.json`. Он не перемеривает код. Зелёный тест при старом `last.json` ничего не доказывает.
- Упавшая карточка чинится в своём узле. Полы не опускать. `--write-floors` и `--raise-floors` только по просьбе и только при GATE OK.
- В `src/` не добавлять имена и факты корпуса, чтобы поднять карточку.
- В отчёте писать `now / floor / room` по тем ключам, которые реально прогонялись.

Python: `C:\Users\Home\AppData\Local\Programs\Python\Python312\python.exe`. `PYTHONPATH=src` задаёт `pytest.ini` и сам scorecard.
