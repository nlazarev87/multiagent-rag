"""Команды ingest и один вопрос без страницы.

Без --user команда не работает. Пароль берётся из CLI_PASSWORD и никуда не печатается.
"""
import os
import sys
from pathlib import Path

import audit
import auth
import kb
from access import build_scope, can, query_record, source_rows
from coordinator import run
from ingest import ingest_dir
from store import upsert_chunks


def _person(argv):
    if "--user" not in argv:
        print("Нужен --user", file=sys.stderr)
        return None, argv
    index = argv.index("--user")
    if index + 1 >= len(argv):
        print("Нужен --user", file=sys.stderr)
        return None, argv
    login = argv[index + 1]
    rest = argv[:index] + argv[index + 2:]
    password = os.environ.get("CLI_PASSWORD", "")
    user, error = auth.authenticate(login, password)
    if user is None or error:
        audit.write("login_fail", None if error != "blocked" else user, {"login": login}, ok=False)
        print("Неверный логин или пароль" if error != "blocked" else "Учётная запись заблокирована", file=sys.stderr)
        return None, rest
    return user, rest


def _copy_into(folder, inbox):
    inbox = Path(inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    folder = Path(folder)
    if folder.resolve() == inbox.resolve():
        return
    saved = []
    try:
        for path in sorted(folder.iterdir()):
            if not path.is_file():
                continue
            target = inbox / path.name
            if target.is_symlink() or target.resolve().parent != inbox.resolve():
                raise OSError("path")
            previous = target.read_bytes() if target.is_file() else None
            saved.append((target, previous))
            target.write_bytes(path.read_bytes())
    except Exception:
        for target, previous in reversed(saved):
            if previous is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(previous)
        raise


def main(argv=None):
    """ingest пишет индекс выбранной базы. Вопрос начинается с первого слова."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        return None
    user, argv = _person(argv)
    if user is None:
        return None
    if not argv:
        return None
    if argv[0] == "ingest":
        if "--kb" not in argv:
            print("Нужен --kb", file=sys.stderr)
            return None
        kb_at = argv.index("--kb")
        if kb_at + 1 >= len(argv):
            print("Нужен --kb", file=sys.stderr)
            return None
        kb_id = argv[kb_at + 1]
        rest = [item for index, item in enumerate(argv) if index not in (0, kb_at, kb_at + 1)]
        if not rest:
            print("Нужна папка", file=sys.stderr)
            return None
        folder = rest[0]
        if not can(user, kb_id, "upload"):
            audit.write("upload", user, {"kb_id": kb_id}, ok=False)
            print("Нет права загружать", file=sys.stderr)
            return None
        row = kb.get(kb_id)
        if row is None:
            print("База не найдена", file=sys.stderr)
            return None
        try:
            _copy_into(folder, row["inbox"])
            chunks = ingest_dir(row["inbox"])
            if row["legacy"]:
                upsert_chunks(chunks)
            else:
                from store import upsert_at
                upsert_at(row["chroma"], chunks)
        except Exception:
            audit.write("upload", user, {"kb_id": kb_id}, ok=False)
            print("Не удалось записать файл", file=sys.stderr)
            return None
        audit.write("upload", user, {"kb_id": kb_id, "names": [item.get("document_name") for item in chunks]})
        return None
    words = argv[1:] if argv[0] == "ask" else argv
    if not words:
        return None
    scope = build_scope(user)
    try:
        if not scope.kbs:
            result = {"answer": "В документах нет ответа.", "status": "нет ответа", "document_names": [], "sources": []}
        else:
            result = run(" ".join(words), "cli", scope)
    except Exception as exc:
        audit.write("query", user, query_record(
            user, scope,
            query=" ".join(words),
            answer="",
            status="нет",
            dialog_id="cli",
            sources=[],
            attempts=getattr(scope, "attempts", 0) or 0,
            error=type(exc).__name__,
        ), ok=False)
        print("Ошибка сервера", file=sys.stderr)
        return None
    audit.write("query", user, query_record(
        user, scope,
        query=" ".join(words),
        answer=result.get("answer", ""),
        status=result.get("status", ""),
        dialog_id="cli",
        sources=source_rows(result, getattr(scope, "found", None) or []),
        attempts=getattr(scope, "attempts", 0) or 0,
        feedback=getattr(scope, "feedback", "") or "",
    ))
    print(result["answer"], result["status"], " ".join(result["document_names"]))
    return result


if __name__ == "__main__":
    main()
