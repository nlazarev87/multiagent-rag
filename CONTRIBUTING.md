# CONTRIBUTING

## Тесты
```bash
pytest -m "not slow and not holdout"   # как в CI
pytest                                  # всё
```

## Оценка поиска
```bash
python tests/eval/scorecard.py
```
Пишет last.json всегда (с Wave 0 #1). Exit 1 при провале порога.

## floors.json
Только отдельным PR после улучшившего PR. Опускать запрещено.

## Эвристика
1. Issue по task.md.
2. Флаг в config/runtime.json → features.<name>: false.
3. Реализация за флагом.
4. scorecard.py --disable <name> vs --enable <name>.
5. Не улучшилось — не мержить.
