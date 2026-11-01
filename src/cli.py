"""Команды ingest и один вопрос без страницы.

Вопрос идёт в coordinator.run с dialog_id «cli» и не пишет workspace.json.
"""
import sys

from coordinator import run
from ingest import ingest_dir
from store import upsert_chunks


def main(argv=None):
    """ingest пишет индекс. Вопрос начинается с первого слова; ask перед ним тоже годится."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return None
    if argv[0] == "ingest":
        upsert_chunks(ingest_dir(argv[1]))
        return None
    # «python -m cli сколько насосов в цехе» — вопрос целиком. «ask» оставлен
    # как старая команда, но первое слово вопроса выбрасывать нельзя: без
    # «сколько» обзор таблицы уже не считается вопросом о числе.
    words = argv[1:] if argv[0] == "ask" else argv
    if not words:
        return None
    result = run(" ".join(words), "cli")
    print(result["answer"], result["status"], " ".join(result["document_names"]))
    return result


if __name__ == "__main__":
    main()
