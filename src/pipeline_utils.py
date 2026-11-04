"""Разбор запроса и строка обзора. Сюда переехали приватные имена, которые звал coordinator.

Этот файл не импортирует agents: иначе загрузка замыкается в круг.
"""

import contextvars
import re

_extra_rows = contextvars.ContextVar("extra_rows", default=None)
_trace = contextvars.ContextVar("answer_trace", default=None)

SPAN = 30

_PRONOUNS = {
    "он",
    "она",
    "оно",
    "они",
    "его",
    "её",
    "ее",
    "их",
    "ему",
    "ей",
    "им",
    "него",
    "неё",
    "нее",
    "них",
    "это",
    "этот",
    "эта",
    "эти",
}
_TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[._/:\-][0-9A-Za-zА-Яа-яЁё]+)*")


def _words(text):
    skip = {
        "какой",
        "какая",
        "какое",
        "какие",
        "какова",
        "каков",
        "каком",
        "сколько",
        "такое",
        "такой",
        "такая",
        "такие",
        "этом",
    }
    words = []
    for word in text.lower().replace("?", " ").split():
        for piece in word.split("-"):
            piece = piece.strip(".,:;\"'«»()")
            if len(piece) > 3 and piece not in skip and piece not in _PRONOUNS:
                words.append(piece)
    return words


def _flat(text):
    return " ".join(text.lower().replace("ё", "е").split())


def is_code(token):
    """Ядро: две заглавные или буква и цифра.

    Хвосты остаются в обёртках:
    _names дополнительно берёт 1.2-99 (имена файлов).
    _codes зовёт только это ядро.
    _anchors дополнительно берёт любую цифру (8 нужна уточнению).

    Ядро не менять без test_clarify_* и test_contracts.
    """
    if not token:
        return False
    upper = sum(1 for char in token if char.isupper())
    has_digit = any(char.isdigit() for char in token)
    has_alpha = any(char.isalpha() for char in token)
    return upper >= 2 or (has_digit and has_alpha)


def _codes(text):
    """Коды из текста: только is_code, без хвоста 1.2 и без голой цифры."""
    found = []
    for token in _TOKEN.findall(text or ""):
        if is_code(token):
            key = token.lower().replace("ё", "е")
            if key not in found:
                found.append(key)
    return found


def _dependent(query):
    tokens = set(re.findall(r"[а-яёa-z]+", query.lower()))
    return bool(tokens & _PRONOUNS) or not _words(query)


_OVERVIEW_LINE = re.compile(
    r"Разных значений в столбце «([^»]+)»: (\d+)\. Список: (.+)", re.IGNORECASE
)
_LIST_MARK = re.compile(r"(?<![а-яёa-z])(скольк(?:о|их|ими|им)|какие|перечисли)", re.IGNORECASE)
_COUNT_MARK = re.compile(r"(?<![а-яёa-z])скольк(?:о|их|ими|им)(?![а-яёa-z])", re.IGNORECASE)
_ENDINGS = (
    "иями",
    "ями",
    "ами",
    "ого",
    "его",
    "ому",
    "ему",
    "ыми",
    "ими",
    "ой",
    "ий",
    "ый",
    "ая",
    "яя",
    "ое",
    "ее",
    "ия",
    "ие",
    "ые",
    "ию",
    "ии",
    "ых",
    "их",
    "ом",
    "ем",
    "ах",
    "ях",
    "ов",
    "ев",
    "ам",
    "ям",
    "а",
    "я",
    "ы",
    "и",
    "у",
    "ю",
    "е",
    "о",
)
_ASIDE = {"есть", "между", "входят", "находится", "используется", "используются"}


def _list_ask(query):
    return bool(_LIST_MARK.search(query or ""))


def _count_ask(query):
    return bool(_COUNT_MARK.search(query or ""))


def _word_stem(word):
    for ending in _ENDINGS:
        if len(word) > len(ending) + 2 and word.endswith(ending):
            return word[: len(word) - len(ending)]
    return word


def _focus_words(query):
    words = _words(query)
    if words and words[0] == "перечисли":
        words = words[1:]
    focus = []
    for word in words:
        if word in _ASIDE:
            break
        focus.append(word)
    return focus


def _stem_hit(word, text):
    stem = _word_stem(word)
    return any(_word_stem(token) == stem for token in re.findall(r"[0-9a-zа-яё]+", _flat(text)))


def _label_score(query, label):
    asked = _flat(query)
    name = _flat(label)
    score = 0
    for word in _words(query):
        stem = word[:4] if len(word) >= 4 else word
        if stem in name:
            score += 1
    for token in re.findall(r"[0-9a-zа-яё]+", name):
        stem = token[:4] if len(token) >= 4 else token
        if len(stem) >= 3 and stem in asked:
            score += 1
    return score


def _from_overview(query, chunks):
    if not _list_ask(query) or not chunks:
        return None
    focus = _focus_words(query)
    if not focus:
        return None
    ranked = []
    for number, chunk in enumerate(chunks, 1):
        text = chunk.get("text") or ""
        lines = text.splitlines()
        section = lines[0] if lines else ""
        for match in _OVERVIEW_LINE.finditer(text):
            section_hits = sum(_stem_hit(word, section) for word in focus)
            column_hits = sum(_stem_hit(word, match.group(1)) for word in focus)
            label_hits = 1 if _label_score(query, match.group(1)) else 0
            column_score = column_hits or label_hits
            if not section_hits and not column_score:
                continue
            ranked.append(
                (
                    section_hits,
                    column_score,
                    number,
                    match.group(2),
                    match.group(3).rstrip(" ."),
                    match.group(1).strip(),
                )
            )
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    chosen = None
    for section_hits, column_score, number, count, items, label in ranked:
        others = 0
        for index, chunk in enumerate(chunks, 1):
            if index == number:
                continue
            other_lines = (chunk.get("text") or "").splitlines()
            heading = other_lines[0] if other_lines else ""
            others = max(others, sum(_stem_hit(word, heading) for word in focus))
        if not _count_ask(query) and section_hits < others and column_score <= others:
            continue
        chosen = (number, count, items, label)
        break
    if chosen is None and _count_ask(query) and ranked:
        _, _, number, count, items, label = ranked[0]
        chosen = (number, count, items, label)
    if chosen is None:
        return None
    number, count, items, label = chosen
    if _count_ask(query):
        if any(ch.isdigit() for ch in query):
            return None
        listed = f"{count} {label} [{number}]."
    else:
        listed = f"{items} [{number}]."
    if len(_flat(re.sub(r"\[[\d,\s]+\]", " ", listed)).split()) >= SPAN:
        return None
    return listed
