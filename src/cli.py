"""Команды ingest и один вопрос без страницы.

Вопрос идёт в coordinator.run с dialog_id «cli» и не пишет workspace.json.
"""
import sys

from coordinator import run
from ingest import ingest_dir
from store import upsert_chunks


def main(argv=None):
    """ingest пишет индекс. Остальные аргументы — один вопрос."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[0] == "ingest":
        upsert_chunks(ingest_dir(argv[1]))
        return
    result = run(" ".join(argv[1:]), "cli")
    print(result["answer"], result["status"], " ".join(result["document_names"]))
    return result


if __name__ == "__main__":
    main()
