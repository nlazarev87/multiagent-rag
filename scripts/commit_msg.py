#!/usr/bin/env python3
"""commit-msg hook: валидатор формата сообщения коммита.

Требования:
- заголовок: `<type>(<scope>): <описание> (#<issue>)` (Merge/Revert — исключение);
- в теле ссылка на issue: Closes / Fixes / Resolves / Refs #<N>.

Используется pre-commit (stage: commit-msg); pre-commit передаёт путь
к файлу с сообщением первым аргументом.
"""
import re
import sys

TYPES = "feat|fix|refactor|perf|test|docs|chore|ci|build"
SUBJECT_RE = re.compile(rf"^(?:{TYPES})(\([^)]+\))?:\s+.+?\s+\(#\d+\)$")
ISSUE_RE = re.compile(r"\b(?:Closes|Fixes|Resolves|Refs)\s+#\d+\b", re.IGNORECASE)
MERGE_RE = re.compile(r"^(Merge|Revert)\b")

HINT = (
    "Формат коммита:\n"
    "  <type>(<scope>): <краткое описание> (#<issue>)\n"
    "\n"
    "  Зачем: <проблема/мотивация>\n"
    "  Что:\n"
    "  - <изменение>\n"
    "  Как проверено: pytest -m \"not slow and not holdout\" — N passed\n"
    "  Closes #<issue>       # или Refs #<issue>\n"
    "  Milestone: Wave <N>\n"
    "\n"
    "type: feat|fix|refactor|perf|test|docs|chore|ci|build\n"
)


def fail(msg: str) -> None:
    sys.stderr.write("commit-msg: " + msg + "\n" + HINT)
    sys.exit(1)


def main() -> int:
    if len(sys.argv) < 2:
        fail("не передан файл с сообщением")
    with open(sys.argv[1], encoding="utf-8-sig") as f:
        text = f.read()

    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    if not lines:
        fail("пустое сообщение")

    subject = lines[0].strip()
    if MERGE_RE.match(subject):
        return 0
    if not SUBJECT_RE.match(subject):
        fail("заголовок не по формату: %r" % subject)

    body = "\n".join(lines[1:])
    if not ISSUE_RE.search(body):
        fail("в теле нет ссылки на issue (Closes/Fixes/Resolves/Refs #N)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
