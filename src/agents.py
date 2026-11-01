"""Выбор прошлого хода, уточнение, поиск, ответ и проверка.

Фактов из загруженных документов здесь нет: пороги и словарь единиц читаются
из config и prompts. Проверка не вызывает модель.
"""
import contextvars
import re

from llm import complete, count_tokens
from settings import fewshot, lexicon, prompts, runtime
from store import chunks_for_document, search_chunks

_extra_rows = contextvars.ContextVar("extra_rows", default=None)
_trace = contextvars.ContextVar("answer_trace", default=None)

NO_ANSWER = "В документах нет ответа."
CONFIRMED = "подтверждён"
UNCONFIRMED = "не подтверждён"
MISSING = "нет ответа"
SYSTEM = TASK = YES_NO = RETRY = COPIED = INVERT = LIST_GAP = DEFINE = ""
PROMPT_TOKENS = 1500
SPAN = 30
EXAMPLES = []


def _bind_prompts():
    data = prompts()
    global SYSTEM, TASK, YES_NO, RETRY, COPIED, INVERT, LIST_GAP, DEFINE, PROMPT_TOKENS, SPAN
    SYSTEM = data.get("system") or SYSTEM
    TASK = data.get("task") or TASK
    YES_NO = data.get("yes_no") or YES_NO
    RETRY = data.get("retry") or RETRY
    COPIED = data.get("copied") or COPIED
    INVERT = data.get("invert") or INVERT
    LIST_GAP = data.get("list_gap") or LIST_GAP
    DEFINE = data.get("define") or DEFINE
    PROMPT_TOKENS = runtime().get("prompt_tokens", PROMPT_TOKENS)
    SPAN = runtime().get("span", SPAN)


_bind_prompts()
_PRONOUNS = {"он", "она", "оно", "они", "его", "её", "ее", "их", "ему", "ей", "им", "него", "неё", "нее", "них", "это", "этот", "эта", "эти"}
_TOKEN = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[._/:\-][0-9A-Za-zА-Яа-яЁё]+)*")


def _words(text):
    skip = {"какой", "какая", "какое", "какие", "какова", "каков", "каком", "сколько", "такое", "такой", "такая", "такие", "этом"}
    words = []
    for word in text.lower().replace("?", " ").split():
        for piece in word.split("-"):
            piece = piece.strip(".,:;\"'«»()")
            if len(piece) > 3 and piece not in skip and piece not in _PRONOUNS:
                words.append(piece)
    return words


def _flat(text):
    return " ".join(text.lower().replace("ё", "е").split())


def _codes(text):
    found = []
    for token in _TOKEN.findall(text or ""):
        upper = sum(ch.isupper() for ch in token)
        coded = any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token)
        if upper >= 2 or coded:
            key = token.lower().replace("ё", "е")
            if key not in found:
                found.append(key)
    return found


def _anchors(text):
    found = []
    clean = re.sub(r"\[[\d,\s]+\]", " ", text or "")
    for token in _TOKEN.findall(clean):
        upper = sum(ch.isupper() for ch in token)
        coded = any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token)
        numbered = any(ch.isdigit() for ch in token)
        if upper >= 2 or coded or numbered:
            if token not in found:
                found.append(token)
    return found


def _dependent(query):
    tokens = set(re.findall(r"[а-яёa-z]+", query.lower()))
    return bool(tokens & _PRONOUNS) or not _words(query)


def select_agent(query, turns):
    """Один прошлый ход или пусто. Зависимый вопрос берёт последний ход."""
    if not turns:
        return []
    if _dependent(query):
        return [turns[-1]]
    words = set(_words(query))
    codes = set(_codes(query))
    chosen = None
    for turn in turns:
        same_code = codes & set(_codes(turn["query"]))
        same_words = words & set(_words(turn["query"]))
        if same_code or len(same_words) >= 2:
            chosen = turn
    return [chosen] if chosen else []


def clarify_agent(query, work_turns):
    """Строка для поиска. Независимый вопрос возвращается как есть."""
    if not work_turns or not _dependent(query):
        return query
    previous = work_turns[-1]
    extra = _anchors(previous.get("answer", ""))
    if extra:
        return f"{previous['query']} {query} {' '.join(extra)}"
    return f"{previous['query']} {query}"


def search_agent(clear_query, document_names=None):
    """Найти куски текста. Имена передаются в индекс только когда список непустой."""
    limit = runtime().get("search_limit", 4)
    if document_names:
        return search_chunks(clear_query, limit, document_names)
    return search_chunks(clear_query, limit)


def _trim(text, budget, count):
    lines = text.split("\n")
    while len(lines) > 3 and count("\n".join(lines)) > budget:
        del lines[-2]
    if count("\n".join(lines)) <= budget:
        return "\n".join(lines)
    words = "\n".join(lines).split(" ")
    while words and count(" ".join(words)) > budget:
        words = words[: max(1, int(len(words) * 0.85))] if len(words) > 1 else []
    return " ".join(words)


def _fragment(number, document_name, text):
    return f"Фрагмент {number} (документ {document_name}):\n{text}"


def _frame(query, previous=None, feedback=None):
    head = [f"Вопрос: {query}"]
    if previous:
        head.append(f"Прошлый вопрос: {previous['query']}\nПрошлый ответ: {previous['answer']}")
    tail = [f"Вопрос: {query}"]
    if feedback:
        tail.append(feedback)
    tail.append(f"{TASK} {YES_NO}" if "ли" in re.findall(r"[а-яё]+", query.lower()) else TASK)
    tail.append("Ответ:")
    return head, tail


def _example(query, fragments, reply):
    head, tail = _frame(query)
    parts = [_fragment(number, "example.txt", text) for number, text in enumerate(fragments, 1)]
    return "\n\n".join(head + parts + tail), reply


def _bind_examples():
    global EXAMPLES
    EXAMPLES = [_example(item["query"], item["fragments"], item["reply"]) for item in fewshot()]


def reload_behavior():
    _bind_prompts()
    _bind_examples()


_bind_examples()


_OVERVIEW_LINE = re.compile(r"Разных значений в столбце «([^»]+)»: (\d+)\. Список: (.+)", re.IGNORECASE)
_LIST_MARK = re.compile(r"(?<![а-яёa-z])(скольк(?:о|их|ими|им)|какие|перечисли)", re.IGNORECASE)
_COUNT_MARK = re.compile(r"(?<![а-яёa-z])скольк(?:о|их|ими|им)(?![а-яёa-z])", re.IGNORECASE)
_ENDINGS = (
    "иями", "ями", "ами", "ого", "его", "ому", "ему",
    "ыми", "ими", "ой", "ий", "ый", "ая", "яя", "ое", "ее",
    "ия", "ие", "ые", "ию", "ии", "ых", "их",
    "ом", "ем", "ах", "ях", "ов", "ев", "ам", "ям",
    "а", "я", "ы", "и", "у", "ю", "е", "о",
)
_ASIDE = {"есть", "между", "входят", "находится", "используется", "используются"}


def _list_ask(query):
    return bool(_LIST_MARK.search(query or ""))


def _count_ask(query):
    return bool(_COUNT_MARK.search(query or ""))


def _chunk_score(query, text):
    body = _flat(text)
    score = 0
    for word in _words(query):
        if word in body or (len(word) >= 4 and word[:4] in body):
            score += 1
    return score


def _word_stem(word):
    for ending in _ENDINGS:
        if len(word) > len(ending) + 2 and word.endswith(ending):
            return word[:len(word) - len(ending)]
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
            ranked.append((
                section_hits,
                column_score,
                number,
                match.group(2),
                match.group(3).rstrip(" ."),
                match.group(1).strip(),
            ))
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


def _with_cite(answer, chunks):
    if not chunks or not answer:
        return answer
    if _flat(NO_ANSWER).rstrip(".") in _flat(answer):
        return answer
    if re.search(r"\[\d+\]", answer):
        return answer
    best = max(range(1, len(chunks) + 1), key=lambda number: _chunk_score(answer, chunks[number - 1].get("text", "")))
    return answer.rstrip() + f" [{best}]"


def build_prompt(query, chunks, previous=None, feedback=None, count=None, budget=PROMPT_TOKENS):
    count = count or count_tokens
    head, tail = _frame(query, previous, feedback)
    room = budget - count("\n\n".join(head + tail))
    parts = []
    for number, chunk in enumerate(chunks, 1):
        label = chunk["document_name"]
        bases = {item.get("kb_id") for item in chunks if item.get("kb_id")}
        if len(bases) > 1 and chunk.get("kb_name"):
            label = f"{chunk['kb_name']} / {label}"
        part = _fragment(number, label, chunk["text"])
        cost = count(part)
        if cost > room:
            part = _trim(part, room, count)
            if part:
                parts.append(part)
            break
        parts.append(part)
        room -= cost
    return "\n\n".join(head + parts + tail)


_LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]{2,}")


def _latin_tokens(query):
    return [token.lower() for token in _LATIN_TOKEN.findall(query or "")]


def _latin_missing_from_chunks(query, chunks):
    blob = _flat(" ".join(chunk.get("text") or "" for chunk in chunks))
    return any(token not in blob for token in _latin_tokens(query))


def _document_names(chunks):
    names = []
    for chunk in chunks or []:
        name = chunk.get("document_name")
        if name and name not in names:
            names.append(name)
    return names


def _rows(name, kb_id=""):
    fn = _extra_rows.get()
    if fn is not None:
        return fn(name, kb_id)
    return chunks_for_document(name)


def _kb_of(chunks, name):
    for chunk in chunks:
        if chunk.get("document_name") == name and chunk.get("kb_id"):
            return chunk.get("kb_id") or ""
    return ""


def _as_chunk(name, row):
    item = {
        "text": row.get("text") or "",
        "document_name": name,
        "section": row.get("section", ""),
        "chunk_index": row.get("chunk_index", 0),
    }
    if row.get("kb_id"):
        item["kb_id"] = row.get("kb_id")
        item["kb_name"] = row.get("kb_name") or ""
    return item


def _cover_latin(query, chunks):
    if not _latin_missing_from_chunks(query, chunks):
        return chunks
    missing = [token for token in _latin_tokens(query) if token not in _flat(" ".join(chunk.get("text") or "" for chunk in chunks))]
    found = []
    for name in _document_names(chunks):
        for row in _rows(name, _kb_of(chunks, name)):
            text = (row.get("text") or "").lower()
            if all(token in text for token in missing):
                found.append(_as_chunk(name, row))
                break
    if not found:
        return None
    return found + list(chunks)


def _role_only(chunk):
    section = _flat(chunk.get("section") or "")
    text = _flat(chunk.get("text") or "")
    return "протокол" in section and bool(re.search(r"получател|отправител", text))


def _prefer_name(query, chunks):
    if not re.search(r"что\s+так", _flat(query)):
        return chunks
    tokens = _latin_tokens(query) or [word for word in _words(query) if len(word) >= 4]
    found = []
    for name in _document_names(chunks):
        for row in _rows(name, _kb_of(chunks, name)):
            section = _flat(row.get("section") or "")
            text = (row.get("text") or "").lower()
            if "наименован" not in section and "характеристик" not in section:
                continue
            if tokens and not any(token in text for token in tokens):
                continue
            found.append(_as_chunk(name, row))
            break
    if not found:
        return chunks
    return found + [chunk for chunk in chunks if not _role_only(chunk)]


def _dangling_list(answer):
    body = re.sub(r"\s*\[[\d\s,]+\]", "", answer or "").strip().rstrip(".").lower().replace("ё", "е")
    return body.endswith(":") or body.endswith("следующие") or body.endswith("следующее")


def _split_cites(answer):
    return re.sub(
        r"\[(\d+(?:\s*,\s*\d+)+)\]",
        lambda match: " ".join(f"[{number}]" for number in re.findall(r"\d+", match.group(1))),
        answer or "",
    )


def _drop_repeat_cite(answer):
    text = _split_cites(answer)
    groups = list(re.finditer(r"\s*\[(\d+)\]", text))
    if len(groups) < 2:
        return text
    last = int(groups[-1].group(1))
    prior = {int(group.group(1)) for group in groups[:-1]}
    if last in prior:
        return text[:groups[-1].start()].rstrip()
    return text


def answer_agent(query, clear_query, chunks, work_turns, feedback=None):
    """Текст ответа. Пустые куски дают отказ, обзор таблицы может обойтись без модели."""
    if not chunks:
        return NO_ANSWER
    chunks = _cover_latin(query, chunks)
    if not chunks:
        return NO_ANSWER
    chunks = _prefer_name(query, chunks)
    if not feedback:
        listed = _from_overview(query, chunks)
        if listed:
            return listed
    previous = work_turns[-1] if work_turns and clear_query != query else None
    prompt = build_prompt(query, chunks, previous, feedback)
    sink = _trace.get()
    if sink is not None:
        sink.append(prompt)
    return _drop_repeat_cite(_with_cite(complete(SYSTEM, prompt, examples=EXAMPLES), chunks))


def _pure_number(token):
    return bool(token) and any(ch.isdigit() for ch in token) and all(ch.isdigit() or ch in " ,." for ch in token)


def _whole_number(text, start):
    # «6,5» and «12 000» are one measurement. The token scan otherwise keeps
    # 5 and 12, and either piece is enough to confirm the whole value.
    found = re.match(r"\d{1,3}(?: \d{3})+(?:[,.]\d+)?|\d+(?:[,.]\d+)?", text[start:])
    return found.group(0) if found else ""


def _signs(text):
    return (text or "").replace("\u2212", "-").replace("\u2013", "-")


def _negated(text, start):
    # «-12», «−12» and «минус 12» are one value. A hyphen between digits is a
    # range: «6-10» still has both ends. A spaced dash is punctuation, not a
    # sign: «давление - 6» and «давление – 6» still mean 6. The signed matcher
    # already requires the hyphen to touch the digits, so a space must not
    # swallow the bare number. The minus in «50+-0,2» belongs to the tolerance
    # sign, so 0,2 is not a negative value.
    prefix = text[:start]
    if re.search(r"(?:±|\+/-|\+-)\s*$", prefix):
        return False
    if re.search(r"(?<![0-9a-zа-яё])минус\s*$", prefix, re.IGNORECASE):
        return True
    if re.search(r"(?<!\d)\u2212\s?$", prefix):
        return True
    return re.search(r"(?<!\d)[-\u2013]$", prefix) is not None


def _hits(text, token):
    # Sign normalization is one character for one character, so match offsets
    # still point at the original text. Negation has to see that original:
    # a unicode minus is a sign, and a spaced en-dash is not.
    raw = text or ""
    text = _signs(raw)
    token = _signs(token)
    signed = token[1:].lstrip() if token.startswith("-") and _pure_number(token[1:].lstrip()) else ""
    if signed:
        # The magnitude alone is a different measurement. «минус 12» and «−12»
        # are the same value as «-12».
        pattern = (
            rf"(?<![0-9a-zа-я_])(?:-|минус\s*)"
            rf"{re.escape(signed)}"
            rf"(?![0-9a-zа-я_])(?!,\d)(?!\.\d)(?! \d{{3}}(?!\d))"
            rf"(?![\-/][a-zа-я])(?![:/]\d)"
        )
    elif _pure_number(token):
        grouped = r"(?<!\d )" if re.fullmatch(r"\d{3}", token) else ""
        # «AB-99», «9/299419» and «6:00» are one value. The digit scan otherwise
        # keeps 12, 9, or 6, and that piece confirms the whole value.
        pattern = (
            rf"(?<![0-9a-zа-я_]){grouped}(?<!\d[,.])"
            rf"(?<![a-zа-я][\-/])(?<!\d[:/])"
            rf"{re.escape(token)}"
            rf"(?![0-9a-zа-я_])(?!,\d)(?!\.\d)(?! \d{{3}}(?!\d))"
            rf"(?![\-/][a-zа-я])(?![:/]\d)"
        )
    else:
        pattern = rf"(?<![0-9a-zа-я_]){re.escape(token)}(?![0-9a-zа-я_])"
    found = list(re.finditer(pattern, text))
    if signed or not _pure_number(token):
        return found
    return [match for match in found if not _negated(raw, match.start())]


def _facts(answer):
    text = re.sub(r"\[[\d,\s]+\]", " ", answer)
    facts = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        wide = tuple(word[:5] for word in _words(sentence) if len(word) >= 5)
        covered = 0
        previous = 0
        for match in _TOKEN.finditer(sentence):
            if match.start() < covered:
                continue
            token = match.group(0)
            before = sentence[:match.start()].rstrip()
            start = not before or before[-1] in ".!?:\n«\"("
            if any(ch.isdigit() for ch in token):
                origin = match.start()
                finish = match.end()
                if _pure_number(token):
                    whole = _whole_number(sentence, match.start())
                    if len(whole) > len(token):
                        token = whole
                        finish = match.start() + len(token)
                        covered = finish
                    if _negated(sentence, match.start()):
                        token = "-" + token
                # A short number belongs to the words written with it, not to every
                # word in the sentence. «давление 6 и ток 80» must not lend давление
                # to 80. «от 6 до 10» has no name of its own, so 10 keeps давление.
                window = _number_window(sentence, previous, origin, finish)
                # «по данным завода 1600 — рабочее давление». The words in front
                # are not the measurement; the name after the dash is.
                # «2019 — давление 6» is the other way: давление names 6.
                if not _names_measurement(window):
                    trail = _trailing_name(sentence, finish)
                    if _names_measurement(trail):
                        window = trail
                local = _stems_in(window)
                context = tuple(local) if local else wide
                # «равно 50 ± 0,2» claims 50, and 0,2 only as its half-width.
                # «равно 0,2» is a different claim: there the half-width is the value.
                base = _number_before_tolerance(sentence, origin)
                attached = bool(base) and previous >= len(base) and sentence[previous - len(base):previous] == base
                previous = finish
                if attached:
                    parent = context
                    for earlier in reversed(facts):
                        if earlier[0] == "near" and earlier[1].lstrip("-−\u2212") == base:
                            parent = earlier[2]
                            break
                    facts.append(("near", token, parent, True))
                    continue
                # «AB-9.2» and «3-8» are the value written in the fragment, not a
                # measurement named by the letters of the code or the words around it.
                coded = any(ch.isalpha() for ch in token) and any(ch.isdigit() for ch in token)
                ranged = bool(re.fullmatch(r"\d+\s*-\s*\d+", token.replace("\u2212", "-")))
                if coded or ranged:
                    facts.append(("exact", token))
                    continue
                # 1–3 digit values have to sit with the claim. A longer exact match is how
                # «выпущен в 2019» still meets the line «Год выпуска: 2019». A measurement
                # claim does not get that shortcut: «давление равно 2019» must not take
                # the year, and «давление равно 1000» must not take the density.
                short = sum(ch.isdigit() for ch in token) <= 3
                bound = bool(context) and (short or _names_measurement(window))
                # A year can match by its digits: «выпущен в 2019» meets
                # «Год выпуска: 2019». A qualifier still belongs to this
                # occurrence. «на выходе значение 2000» must not take the inlet,
                # so the words in front travel with the exact number.
                if bound:
                    facts.append(("near", token, context))
                elif local and not short:
                    facts.append(("exact", token, tuple(local)))
                else:
                    facts.append(("exact", token))
            elif sum(ch.isupper() for ch in token) >= 2:
                facts.append(("exact", token))
            elif token[:1].isupper() and len(token) >= 4 and not start:
                facts.append(("stem", token))
    return facts


def _specific(query):
    found = []
    for position, match in enumerate(_TOKEN.finditer(query)):
        token = match.group(0)
        latin = any("a" <= ch.lower() <= "z" for ch in token)
        upper = sum(ch.isupper() for ch in token) >= 2
        named = position > 0 and token[:1].isupper()
        if latin or upper or named or any(ch.isdigit() for ch in token):
            found.append(token)
    return found


def _case(text):
    return (text or "").lower().replace("ё", "е")


def _bounds(text, start):
    # The next line's number is a different fact. A fixed 80-character window
    # still reaches it after newlines are flattened, and then "номер: 4" confirms
    # "давление равно 4".
    def cuts(index):
        char = text[index]
        if char not in ".!?,;\n":
            return False
        decimal = char in ",." and 0 < index < len(text) - 1 and text[index - 1].isdigit() and text[index + 1].isdigit()
        if decimal:
            return False
        # «в 14 ч. 30 мин. составляет 6» is one clause. The dot is the
        # abbreviation, so it must not hide 6. «Пауза 30 мин. Давление 6»
        # still splits: a new noun after the dot is the next fact.
        return not (char == "." and _clock_dot(text, index))

    left = 0
    for index in range(start - 1, -1, -1):
        if cuts(index):
            left = index + 1
            break
    right = len(text)
    for index in range(start, len(text)):
        if cuts(index):
            right = index
            break
    return left, right


def _span(text, start):
    left, right = _bounds(text, start)
    return text[left:right]


# A clock, a fraction, a designation and a grouped figure are one value.
# The digit inside them is not a second measurement.
_PLAIN_NUMBER = re.compile(
    r"(?<![0-9a-zа-я_])(?<!\d[,.])(?<![a-zа-я][\-/])(?<!\d[:/])"
    r"\d+(?:[,.]\d+)?"
    r"(?![0-9a-zа-я_])(?!,\d)(?!\.\d)(?! \d{3}(?!\d))"
    r"(?![\-/][a-zа-я])(?![:/]\d)"
)
# «12 000» is one value. The plain scan keeps only «000», and a qualifier check
# then looks at the wrong place.
_VALUE = re.compile(
    r"(?<![0-9a-zа-я_])(?<!\d[,.])(?<![a-zа-я][\-/])(?<!\d[:/])"
    r"(?:\d{1,3}(?: \d{3})+(?:[,.]\d+)?|\d+(?:[,.]\d+)?)"
    r"(?![0-9a-zа-я_])(?!,\d)(?!\.\d)(?! \d{3}(?!\d))"
    r"(?![\-/][a-zа-я])(?![:/]\d)"
)


def _plain_number(text):
    return _PLAIN_NUMBER.search(text or "")


# Verbs and adverbs that sit next to any measurement. They are not its name.
_LINKS = {
    "равно", "равна", "равен", "равны", "равняется",
    "составляет", "составляют", "имеет", "имеют", "иметь", "имел", "имела", "имело", "имели",
    "должен", "должна", "должно", "должны",
    "около", "примерно", "порядка",
    "достигает", "достигают", "превышает", "превышают",
    "соответствует", "соответствуют",
    "держится", "держатся", "находится", "находятся",
}


def _kinds():
    return lexicon().get("kinds") or ()


def _measures():
    return lexicon().get("measures") or ()


def _deltas():
    return lexicon().get("deltas") or ()


def _sizes():
    return lexicon().get("sizes") or ()


def _delta_endings():
    return set(lexicon().get("delta_endings") or ())


def _case_endings():
    return set(lexicon().get("case_endings") or ())


_BRIDGES = ("уров", "значен", "показател", "величин")
# Prepositions, conjunctions and units. They stand next to a number without naming it.
_GLUE = {
    "от", "до", "из", "за", "по", "на", "при", "для", "или", "над", "под", "без", "про",
    "не", "ни", "но", "да", "же", "ко", "об", "со", "во", "то", "как", "это", "либо",
    "между", "через", "после", "перед", "около", "свыше", "менее", "более",
    "бар", "мпа", "кпа", "атм", "мм", "см", "дм", "кг", "гц", "квт", "мвт",
    "мин", "сек", "час", "шт", "рад", "град", "мл", "вт", "па",
}
_ASKED = {
    "какой", "какая", "какое", "какие", "какова", "каков", "каком", "сколько",
    "такое", "такой", "такая", "такие", "этом",
}
# Endings of adjectives. «рабочее» and «полезного» do not name a measurement.
# «давление» and «действие» do not end this way.
_ADJECTIVE = re.compile(
    r"(?:ый|ий|ой|ая|ое|ее|ые|ого|его|ому|ему|ым|им|ом|ем|ую|юю|ых|их|ыми|ими|ей)$"
)
_CONJUNCTIONS = {"и", "а", "или", "либо", "но", "да"}


def _word_at(span, start):
    found = re.match(r"[a-zа-яё]+", span[start:])
    return found.group(0) if found else ""


def _kind_word(word):
    return any(word.startswith(kind) for kind in _kinds())


def _kind_noun(word):
    # «температура» names the value; «температурных» only modifies another noun.
    if not _kind_word(word):
        return False
    return re.search(
        r"н(?:ый|ий|ой|ая|ое|ее|ые|ого|его|ому|ему|ым|им|ом|ем|ую|юю|ых|их|ыми|ими)$",
        word,
    ) is None


# A condition after «при» can name its number with a word outside the kind list.


def _brief(extra):
    return extra == "" or (len(extra) <= 3 and extra[0] in "аеёиоуыэюя")


def _fold(word):
    # «время» and «угол» change inside the stem: «времени», «угле».
    # A five-letter prefix of one form is not a prefix of the other.
    # «углубление» is not «угол», and «временно» is not «время».
    if word == "время" or (word.startswith("времен") and _brief(word[6:])):
        return "времен"
    if word == "угол" or (word.startswith("угл") and _brief(word[3:])):
        return "угл"
    return word


def _delta_word(word):
    # «допускается» and «потерять» are not «допуск» and «потеря».
    if not word:
        return False
    for stem in _deltas():
        if word.startswith(stem) and word[len(stem):] in _delta_endings():
            return True
    return False


def _size_word(word):
    if not word:
        return False
    for stem in _sizes():
        if word.startswith(stem) and word[len(stem):] in _case_endings():
            return True
    return False


def _measure_word(word):
    if not word:
        return False
    if _fold(word) != word:
        return True
    for stem in _measures():
        if stem in {"времен", "угл"}:
            continue
        if len(stem) >= 5:
            if word.startswith(stem):
                return True
            continue
        if _inflected(word, stem):
            return True
    return False


def _measure_noun(word):
    # «временно» and «напряженно» share a measure prefix, but they are adverbs.
    # They must not take the number away from the noun they modify.
    if not _measure_word(word):
        return False
    return _fold(word) != word or not word.endswith("о")


def _kind_stem(stem):
    return any(kind.startswith(stem) or stem.startswith(kind) for kind in _kinds())


def _bridge_word(word):
    return any(word.startswith(bridge) for bridge in _BRIDGES)


def _name_before(span, number_start):
    # The name of a number may sit behind a linking verb: «ток равен 80».
    # Stop at another digit, so «от 6 до 10» does not walk back to давление.
    pos = number_start
    for _ in range(6):
        prefix = span[:pos].rstrip(" \t:;—–-\u2212()«»\",")
        found = re.search(r"([a-zа-яё]{2,})$", prefix)
        if not found:
            return ""
        word = found.group(1)
        if word in _GLUE or word in _LINKS or word in _ASKED or _bridge_word(word):
            pos = found.start()
            continue
        return word
    return ""


def _inflected(word, stem):
    # «ток» and «тока» are one name. «холод» is not «ход», and «параметр» is not «пар».
    # «угол» and «угле» are one name, and so are «время» and «времени».
    if not word or not stem:
        return False
    word, stem = _fold(word), _fold(stem)
    if word == stem:
        return True
    longer, shorter = (word, stem) if len(word) >= len(stem) else (stem, word)
    if not longer.startswith(shorter):
        return False
    extra = longer[len(shorter):]
    return _brief(extra) and extra != ""


def _other_name(span, number_start, stem):
    # The word naming the number. «ток», «ход», «тип» and «кпд» are shorter than
    # five letters, so the gap scan never sees them. «ток равен 80» hides ток
    # behind the verb.
    word = _name_before(span, number_start)
    if not word or word.startswith(stem):
        return False
    return True


def _split_gap(middle):
    # «давление и ток: 80» coordinates two names. «давление на выходе: 6» does not.
    return re.search(r"(?<![0-9a-zа-яё])(?:или|либо|но|и|а)(?![0-9a-zа-яё])", middle or "") is not None


def _stems_in(region):
    stems = []
    for word in re.findall(r"[a-zа-яё]{3,}", (region or "").lower().replace("ё", "е")):
        if word in _GLUE or word in _LINKS or word in _PRONOUNS or word in _ASKED or _bridge_word(word):
            continue
        stem = word[:5]
        if stem not in stems:
            stems.append(stem)
    return stems


def _tail_label(head):
    without = re.sub(r"\d[\d ,.]*$", "", head or "")
    return re.split(r"\d[\d ,.]*", without)[-1]


def _next_number_at(sentence, finish):
    found = re.search(r"\d", sentence[finish:])
    return finish + found.start() if found else len(sentence)


def _number_window(sentence, previous, start, finish):
    window = sentence[previous:start]
    if _stems_in(window):
        return window
    if previous:
        inherited = _tail_label(sentence[:previous])
        if _stems_in(inherited):
            return inherited
    return sentence[finish:_next_number_at(sentence, finish)]


def _trailing_name(sentence, finish):
    # «1600 — рабочее давление» and «1600 бар — рабочее давление» name 1600.
    # A later number owns the words in front of it: «2019 — давление 6».
    if _next_number_at(sentence, finish) != len(sentence):
        return ""
    rest = sentence[finish:]
    if re.match(r"(?:\s+[a-zа-яё°%]{1,8}){0,2}\s*[:—–\-]\s+\S", _case(rest)):
        return rest
    return ""


def _names_measurement(region):
    # «давление», «ход», «радиус» and «перепад» name the number beside them.
    # «выпущен», «год» and «фонд» do not, so a bare year can still match exactly.
    for word in re.findall(r"[a-zа-яё]{2,}", _case(region)):
        if word in _GLUE or word in _LINKS or word in _PRONOUNS or word in _ASKED or _bridge_word(word):
            continue
        if _kind_noun(word) or _measure_noun(word) or _size_word(word) or _delta_word(word):
            return True
    return False


def _restates_earlier_kind(span, start, stem):
    # «давление держится на уровне 80»: «уровне» repeats давление. It does not
    # name a new measurement, so it must not confirm температура 80.
    # «при температуре 20 уровень 8» is different: 20 already took температура.
    for found in reversed(list(re.finditer(r"[a-zа-яё]{5,}", span[:start]))):
        word = found.group(0)
        if word in _LINKS or word.startswith(stem):
            continue
        if not _kind_word(word):
            return False
        return _plain_number(span[found.end():start]) is None
    return False


def _measure_label(words, stem):
    # The nearest name of a number. A genitive such as «контура» is not a
    # different measurement; «номер», «массой» and «температура» are.
    # «на уровне» restates the name before it: «температура на уровне».
    names = [word for word in words if word not in _LINKS]
    while names and _bridge_word(names[-1]):
        names.pop()
    if not names or names[-1].startswith(stem):
        return False
    if _kind_word(names[-1]):
        return True
    # «рабочая температура масла»: масла is a genitive, температура still names 80.
    return len(names) >= 2 and _kind_noun(names[-2]) and not names[-2].startswith(stem)


# «1 января», «в январе» and «12 мая». «майор» is not «май», and «маршрута» is not «март».
_MONTH_NAME = re.compile(
    r"январ(?:ь|я|е|ю|ем)|феврал(?:ь|я|е|ю|ем)|март(?:а|е|у|ом)?|"
    r"апрел(?:ь|я|е|ю|ем)|ма(?:ем|й|я|е|ю)|июн(?:ь|я|е|ю|ем)|"
    r"июл(?:ь|я|е|ю|ем)|август(?:а|е|у|ом)?|сентябр(?:ь|я|е|ю|ем)|"
    r"октябр(?:ь|я|е|ю|ем)|ноябр(?:ь|я|е|ю|ем)|декабр(?:ь|я|е|ю|ем)"
)


def _month_word(word):
    return _MONTH_NAME.fullmatch(word or "") is not None


def _calendar_day(token):
    return bool(re.fullmatch(r"\d{1,2}", token or "")) and 1 <= int(token) <= 31


def _word_after(text):
    found = re.match(r"\s*([a-zа-яё]+)", _case(text))
    return found.group(1) if found else ""


def _word_before(text):
    found = re.search(r"([a-zа-яё]+)\s*$", _case(text))
    return found.group(1) if found else ""


def _numeric_date(text, start, end):
    # «01.01.2019» is one date. The digit scan otherwise keeps 01 and 2019,
    # and either piece hides the value written next to the measurement.
    token = text[start:end]
    before = text[:start]
    after = text[end:]
    if re.fullmatch(r"(?:19|20)\d{2}", token) and re.search(r"(?<!\d)\d{1,2}\.\d{1,2}\.$", before):
        return True
    if re.fullmatch(r"\d{1,2}", token) and re.search(r"(?<!\d)\d{1,2}\.$", before) and re.match(
        r"\.(?:19|20)\d{2}(?!\d)", after
    ):
        return True
    return bool(re.fullmatch(r"\d{1,2}", token) and re.match(r"\.\d{1,2}\.(?:19|20)\d{2}(?!\d)", after))


def _date_number(text, start, end):
    # «с 2019 года», «в 2019 году» and «до 2019» name a date. That year is not
    # the reading, so «давление с 2019 года составляет 6» is давление 6, and
    # «с 2019 года давление составляет 6» is not давление 2019. «2019 бар» and
    # «от 2000 до 2019 бар» are readings: a unit or a range keeps the number.
    # «с 1 января 2019 года составляет 6» is the same date. The day is not
    # давление 1, and it must not hide 6. «в январе 2019» and «01.01.2019»
    # are not readings either. «1 мм», «1 бар» and «от 1 до 6 бар» still are.
    token = text[start:end]
    after = text[end:]
    before = text[:start]
    year = bool(re.fullmatch(r"(?:19|20)\d{2}", token))
    if year and re.match(r"\s*(?:года|году|годом|год|г\.?)(?![0-9a-zа-яё])", after, re.IGNORECASE):
        return True
    if _numeric_date(text, start, end):
        return True
    if re.match(
        r"\s*(?:бар|мпа|кпа|атм|мм|см|дм|кг|гц|квт|мвт|мин|сек|час|шт|мл|вт|па|м|л|%)(?![0-9a-zа-яё])",
        _case(after),
    ):
        return False
    if _calendar_day(token) and _month_word(_word_after(after)):
        return True
    if _calendar_day(token):
        later = re.match(r"\s*(?:по|до)\s+(\d{1,2})\s+([a-zа-яё]+)", _case(after))
        if later and _calendar_day(later.group(1)) and _month_word(later.group(2)):
            return True
    if not year:
        return False
    if re.search(r"(?<![0-9a-zа-яё])от\s*$", before, re.IGNORECASE) and re.match(
        r"\s*до(?![0-9a-zа-яё])", after, re.IGNORECASE
    ):
        return False
    if re.search(r"(?<![0-9a-zа-яё])до\s*$", before, re.IGNORECASE) and re.search(
        r"(?<![0-9a-zа-яё])от\s+\d", before, re.IGNORECASE
    ):
        return False
    if _month_word(_word_before(before)):
        return True
    return re.search(r"(?<![0-9a-zа-яё])(?:в|во|с|со|до|от|к|ко|по)\s*$", before, re.IGNORECASE) is not None


# «в 6 часов», «в 14 ч», «в 14 ч.», «к 8 часам», «по 18 часов».
# «часового» is not «час», and «часть» is not either: the short form is only «ч».
_HOUR_STEM = r"(?:час(?:а|ов|ам|у|ах|ами|ом|е)?|ч)"
_HOUR_WORD = re.compile(rf"{_HOUR_STEM}(?![0-9a-zа-яё])\.?")
_TIME_PREP = r"(?:около|во|ко|со|от|до|по|в|к|с)"
# «30 минут», «30 мин», «30 мин.», «1 минуту», «15 секунд», «15 сек».
# «минутный» is not «минут», and «минимум» is not «мин».
_MINUTE_STEM = r"(?:минут(?:а|ы|у|е|ой|ою|ам|ах|ами)?|мин)"
_SECOND_STEM = r"(?:секунд(?:а|ы|у|е|ой|ою|ам|ах|ами)?|сек)"
_CLOCK_PART_WORD = re.compile(rf"(?:{_MINUTE_STEM}|{_SECOND_STEM})(?![0-9a-zа-яё])\.?")
# The hour this minute or second belongs to: «в 14 часов 30 минут»,
# «в 14 ч 30 мин», «к 8 часам 15 секунд», «в 14 часов 30 мин 15 сек».
_CLOCK_PART_BEFORE = re.compile(
    rf"(?<![0-9a-zа-яё]){_TIME_PREP}\s+(\d{{1,2}})\s+{_HOUR_WORD.pattern}"
    rf"(?:\s+\d{{1,2}}\s+{_MINUTE_STEM}(?![0-9a-zа-яё])\.?)?\s*$"
)


def _hour_range_after(after):
    # «до 18 часов», «по 18 часов», «до 18 ч» and «по 18 ч.».
    # «до 18 бар» and «по 18 бар» have no hour word.
    found = re.match(rf"\s*(?:до|по)\s+(\d{{1,2}})\s+{_HOUR_WORD.pattern}", _case(after))
    return found is not None and int(found.group(1)) <= 24


def _hour_range_before(before):
    # «с 8 часов до», «от 6 ч по», «с 8 ч. до»: the unit sits on the start,
    # so the end number has no hour word after it.
    return re.search(
        rf"(?<![0-9a-zа-яё])(?:от|с|со)\s+\d{{1,2}}\s+{_HOUR_WORD.pattern}\s+(?:до|по)\s*$",
        _case(before),
    ) is not None


def _hour_range_end_unit(after):
    # «с 8 часов до 18 бар» is a reading. «с 8 часов до 18» and
    # «с 8 часов до 18 составляет 6» are still the clock end.
    found = re.match(r"\s*([a-zа-яё]+)", _case(after))
    if not found:
        return False
    word = found.group(1)
    if _HOUR_WORD.fullmatch(word):
        return False
    return word in _GLUE or _unit_word(word)


def _clock_number(text, start, end):
    # «в 6 часов», «к 8 часам», «до 18 часов» and «в 14:30» name a time of day.
    # That hour is not the reading, so «давление в 6 часов составляет 10» is
    # давление 10, and «в 18 часов рабочее давление: 6» is not давление 18.
    # «с 8 до 18 часов», «с 8 по 18 часов», «от 6 до 10 часов» and
    # «с 8 часов до 18» are the same kind of hour, on both ends.
    # A duration still owns its range:
    # «наработка от 6 до 10 часов» and «наработка с 8 по 18 часов».
    # «давление с 8 по 18 часов составляет 6» does not, so 8 and 18 must not
    # hide 6. «с 8 по 18 бар» and «с 8 часов до 18 бар» stay readings.
    # «6.5» and «14.30 бар» stay readings: a dot is a time only after a time preposition.
    # «в 14 часов 30 минут» and «в 14 ч 30 мин» are the same clock: 30 is not
    # the reading. «часть» and «минутный» are not those units.
    token = text[start:end]
    after = text[end:]
    before = text[:start]
    if _clock_part(token, before, after):
        return True
    if re.fullmatch(r"\d{2}", token) and re.search(r"(?<!\d)\d{1,2}:$", before):
        return True
    if re.fullmatch(r"\d{1,2}", token) and re.match(r":\d{2}(?!\d)", after):
        return True
    if re.fullmatch(r"\d{2}", token) and re.search(
        rf"(?<![0-9a-zа-яё]){_TIME_PREP}\s+\d{{1,2}}\.$", before, re.IGNORECASE
    ):
        return True
    if (
        re.fullmatch(r"\d{1,2}", token)
        and re.match(r"\.\d{2}(?!\d)", after)
        and re.search(rf"(?<![0-9a-zа-яё]){_TIME_PREP}\s*$", before, re.IGNORECASE)
    ):
        return True
    if not re.fullmatch(r"\d{1,2}", token) or int(token) > 24:
        return False
    if _hour_range_after(after) and re.search(
        rf"(?<![0-9a-zа-яё])(?:от|с|со)\s*$", before, re.IGNORECASE
    ):
        return True
    if _hour_range_before(before) and not _hour_range_end_unit(after):
        return True
    if not re.match(rf"\s*{_HOUR_WORD.pattern}", _case(after)):
        return False
    return re.search(rf"(?<![0-9a-zа-яё]){_TIME_PREP}\s*$", before, re.IGNORECASE) is not None


def _clock_dot(text, index):
    # A dot after «ч», «час», «мин» or «сек» continues the same clause when
    # a minute, a second, or a linking verb follows. «с 8 ч. до 18» is the
    # same window: the abbreviation sits before the other end.
    # «ч. 12 насосов» and «мин. давление» stay separate facts.
    if re.search(r"(?<![0-9a-zа-яё])(?:час|мин|сек|ч)$", _case(text[:index])) is None:
        return False
    rest = _case(text[index + 1:])
    links = "|".join(re.escape(word) for word in sorted(_LINKS, key=len, reverse=True))
    if re.match(rf"\s*(?:{links})(?![0-9a-zа-яё])", rest):
        return True
    if re.match(rf"\s*\d{{1,2}}\s+(?:{_MINUTE_STEM}|{_SECOND_STEM})(?![0-9a-zа-яё])", rest):
        return True
    return re.match(r"\s*(?:до|по)\s+\d{1,2}(?!\d)", rest) is not None


def _part_hour_at(span, start):
    # Start of the clock hour that «30» continues in «в 14 часов 30 минут»
    # or «в 14 ч 30 мин». A duration with no time preposition,
    # «составляет 6 ч 30 мин», has none.
    found = _CLOCK_PART_BEFORE.search(_case(span[:start]))
    if not found or int(found.group(1)) > 24:
        return None
    return found.start(1)


def _clock_part(token, before, after):
    # «в 14 часов 30 минут», «в 14 ч 30 мин» and «в 14 ч 30 мин 15 сек» name
    # a time of day. That minute is not the reading, so «давление в 14 часов
    # 30 мин составляет 6» is давление 6, and not давление 30. «время в 6 ч
    # 30 мин» still belongs to время: the hour does, so the minute does too.
    # «наработка составляет 6 ч 30 мин» has no time preposition.
    if not re.fullmatch(r"\d{1,2}", token or "") or int(token) > 59:
        return False
    if not re.match(rf"\s*{_CLOCK_PART_WORD.pattern}", _case(after)):
        return False
    return _part_hour_at(before, len(before)) is not None


def _clock_unit(word):
    # «часов» and «минут» sit inside «с 8 часов до 18» and «с 8 ч 30 мин до 18».
    # They are the unit, not the noun that owns the duration. «часового» is not.
    folded = _case(word)
    return _HOUR_WORD.fullmatch(folded) is not None or _CLOCK_PART_WORD.fullmatch(folded) is not None


def _hour_owner(span, start):
    # The noun a duration measures: «срок службы в 6 часов» → срок,
    # «наработка до 6 часов» → наработка. A leading «в 6 часов» has none.
    # «наработка от 6 до 10 часов»: the end has to walk past 6 and «до».
    # «наработка с 8 часов до 18» also walks past the hour unit.
    pos = start
    for _ in range(8):
        prefix = span[:pos].rstrip(" \t:;—–-\u2212()«»\",")
        number = re.search(r"\d+(?:[,.]\d+)?$", prefix)
        if number:
            pos = number.start()
            continue
        found = re.search(r"([a-zа-яё]+)$", prefix)
        if not found:
            return ""
        word = found.group(1)
        if (
            word in _GLUE
            or word in _LINKS
            or word in _ASKED
            or word in {"в", "к", "с", "о", "у"}
            or _clock_unit(word)
        ):
            pos = found.start()
            continue
        nouns, _dropped = _naming_nouns(span, found.end())
        return _phrase_owner(nouns)
    return ""


def _owns_hours(span, start, stem):
    # «смена в 8 часов», «срок службы в 6 часов» and «наработка до 6 часов»
    # belong to that noun. «давление в 6 часов» and «ток в 6 часов» do not:
    # a physical kind is not measured in hours. «количество до 6 часов» is
    # the count of those hours, and «время в 6 часов» is the duration itself.
    # «время в 6 часов 30 минут»: the minute belongs to whoever owns the hour.
    hour_at = _part_hour_at(span, start)
    if hour_at is not None and hour_at != start:
        return _owns_hours(span, hour_at, stem)
    owner = _hour_owner(span, start)
    if not owner or not _matches(owner, stem):
        return False
    if _kind_noun(owner) and not owner.startswith("количеств"):
        return False
    if _measure_noun(owner) and not _matches(owner, "время"):
        return False
    if _delta_word(owner):
        return False
    if _size_word(owner) and not (owner.startswith("ресурс") or owner.startswith("срок")):
        return False
    return True


def _reading(text, follow=""):
    # A date or a clock between a name and its value is not another measurement.
    # «время работы от 6 до 10 часов»: the slice before 10 stops at «до», so
    # the hour word after 10 still has to show that 6 is the other end.
    if not text:
        return None
    whole = text + (follow or "")
    for match in re.finditer(r"(?<![0-9a-zа-я_\-])\d+(?![0-9a-zа-я_\-])", text):
        if _date_number(whole, match.start(), match.end()) or _clock_number(whole, match.start(), match.end()):
            continue
        return match
    return None


def _other_label(span, number_start, stem_at):
    # «при температуре 80 рабочее давление составляет 6» is one clause. 80 is
    # labeled by «температуре», and the pressure is the later 6. The same is
    # true of «номер 6», «частота 50» and «4 насоса» written before the
    # attribute. A value with no label of its own still belongs to the name
    # that follows: «6 бар — рабочее давление». «от 6 до 10» is not this case:
    # both numbers follow the attribute. «1600 — давление с 2019 года» keeps
    # 1600: the year is not a second reading of давление.
    # These sit between a name and its number. They are not another measurement.
    tail = span[stem_at.end():]
    if _reading(tail) is None:
        return False
    stem = stem_at.group(0)
    if _other_name(span, number_start, stem):
        return True
    labels = re.findall(r"[a-zа-яё]{5,}", span[:number_start])
    while labels and labels[-1] in _LINKS:
        labels.pop()
    if labels and not labels[-1].startswith(stem):
        return True
    middle = re.sub(r"[a-zа-яё]+\s*$", "", span[number_start:stem_at.start()])
    return any(word not in _LINKS for word in re.findall(r"[a-zа-яё]{5,}", middle))


def _matches(word, stem):
    if not word or not stem:
        return False
    # «давление» matches «давлен», «точности» matches «точно».
    # The stem must not swallow a shorter different word: «параметр» is not «пар».
    if word.startswith(stem):
        return True
    return _inflected(word, stem)


def _naming_nouns(span, number_start):
    # Nouns of the phrase that names this number, nearest first.
    # «температура масла: 80» → масла, температура.
    # «класс точности: 80» → точности, класс.
    # «давление на выходе: 6» stops at «на» and keeps «выходе».
    # «при температуре составляет 6» drops температуре: the verb shows that
    # 6 belongs to the head before «при».
    pos = number_start
    nouns = []
    dropped = []
    saw_verb = False
    for _ in range(8):
        prefix = span[:pos].rstrip(" \t:;—–-\u2212()«»\",")
        found = re.search(r"([a-zа-яё]{2,})$", prefix)
        if not found:
            break
        between = prefix[found.end():]
        if nouns and re.search(r"(?<![a-zа-яё])(?:и|а)(?![a-zа-яё])", between):
            break
        word = found.group(1)
        pos = found.start()
        if word in _LINKS:
            saw_verb = True
            continue
        if word in _ASKED or _bridge_word(word):
            continue
        if word in _GLUE:
            if not nouns:
                continue
            if word in _CONJUNCTIONS:
                break
            if saw_verb:
                dropped.append(nouns[0])
                nouns.clear()
                saw_verb = False
                continue
            break
        if _ADJECTIVE.search(word) and not _kind_noun(word):
            continue
        nouns.append(word)
        if len(nouns) >= 3:
            break
    return nouns, dropped


def _generic_head(word):
    # «класс точности», «степень защиты», «коэффициент действия».
    # The head only classifies the next noun. «классификация» is not «класс».
    return any(_inflected(word, stem) for stem in ("класс", "степень", "коэффициент"))


def _adverb_head(word):
    # «временно», «напряженно» and «постоянно» modify the next noun.
    # «число» and «масло» do not end in «нно».
    return word.endswith("нно")


def _phrase_owner(nouns):
    if not nouns:
        return ""
    if len(nouns) == 1:
        return nouns[0]
    # «давление масла» and «диаметр патрубка»: the kind is the measurement.
    # «ход поршня», «ток двигателя», «угол поворота» and «время работы» too.
    # «радиус поршня», «толщина стенки» and «шаг резьбы» name themselves.
    # A head outside the kind list is still the measurement, so the object does not own the number.
    # «класс точности» and «степень защиты»: the word next to the generic head is.
    # «насос номер» and «градусов … давление»: the kind written next to another noun is.
    # «постоянно радиус поршня»: the adverb does not take the number from радиус.
    # «перепад давления», «погрешность давления», «допуск диаметра» and
    # «амплитуда хода»: the difference, error, or swing owns the number.
    head = nouns[-1]
    follower = nouns[-2]
    if _kind_word(head) or _measure_noun(head) or _delta_word(head):
        return head
    if _generic_head(head) or _adverb_head(head) or _kind_noun(follower) or _measure_noun(follower):
        return follower
    return head


def _foreign_phrase(span, number_start, stem):
    # «масла» in «температура масла: 80» does not make the number a pressure.
    # «класс» in «класс точности: 80» does not make it «класс давления».
    # «температуре» in «давление при температуре составляет 6» does not own 6.
    nouns, dropped = _naming_nouns(span, number_start)
    owner = _phrase_owner(nouns)
    if not owner:
        return False
    if _matches(owner, stem):
        return False
    if any(_matches(word, stem) for word in nouns) or any(_matches(word, stem) for word in dropped):
        return True
    # «давление при температуре 80» and «давление при ходе 80»: the condition
    # owns the number, so the head before «при» does not. The same is true of
    # «ток», «зазор», «угол», «кпд», «напряжение», «ход поршня», «радиус»,
    # «толщина», «ресурс», «производительность», «шаг», «емкость», «срок»,
    # «площадь» and «глубина».
    # «перепад», «погрешность», «допуск», «отклонение», «потеря», «падение»,
    # «пульсация», «амплитуда», «снижение», «разность», «неравномерность»,
    # «колебание» and «градиент» do too: «давление при перепаде 2 бар» is not
    # давление 2.
    # «давление на выходе: 6», «давление на площадке: 6» and «давление при работе: 6»
    # name no other measurement.
    if any(_measure_word(word) and not _matches(word, stem) for word in nouns):
        return True
    if _delta_word(owner) or _size_word(owner):
        return True
    return _kind_noun(owner)


def _stated_condition(middle):
    # «при температуре 80 градусов составляет» only qualifies the value that
    # follows. The number inside it is not a second value of the head.
    number = r"\d{1,3}(?: \d{3})+(?:[,.]\d+)?|\d+(?:[,.]\d+)?"
    links = "|".join(re.escape(word) for word in sorted(_LINKS, key=len, reverse=True))
    unit = r"(?:\s+[^\s]*[a-zа-яё°%][^\s]*){0,2}"
    pattern = rf"\s*при(?:\s+[a-zа-яё]{{3,}}){{1,3}}\s+(?:{number}){unit}\s+(?:{links})\s*[:;—–\-]*\s*"
    return re.fullmatch(pattern, middle or "") is not None


def _number_before_tolerance(span, number_start):
    # «6 ± 0,5», «50+/-0,2» and «50+-0,2» put the half-width after the value.
    # «6 бар ± 0,5» may keep a unit in between. «погрешность: ±0,5» has no
    # value before the sign, so 0,5 is the reading itself. A hyphen is a range
    # or a dash, not this sign: «6-10» and «давление - 6» stay as they are.
    if not span or number_start <= 0:
        return ""
    prefix = span[:number_start]
    if re.search(r"(?:±|\+/-|\+-)\s*$", prefix) is None:
        return ""
    body = re.sub(r"(?:±|\+/-|\+-)\s*$", "", prefix)
    found = None
    for match in re.finditer(r"(?<!\d)\d{1,3}(?: \d{3})+(?:[,.]\d+)?|(?<!\d)\d+(?:[,.]\d+)?", body):
        found = match
    if not found:
        return ""
    tail = body[found.end():].strip()
    if tail:
        words = re.findall(r"[0-9a-zа-яё°%./]+", tail.lower().replace("ё", "е"))
        if not words or len(words) > 3 or any(_kind_word(word) or _measure_word(word) for word in words):
            return ""
    return found.group(0)


def _short_owns(span, number_start, stem):
    # «ток: 80» touches the name. «ход поршня: 80» and «угол поворота: 80» do not:
    # the object sits in between, but the short name still owns the number.
    # That object is not a second measurement, so «диаметр поршня» does not keep 80.
    nouns, _dropped = _naming_nouns(span, number_start)
    owner = _phrase_owner(nouns)
    if _inflected(owner, stem):
        return True
    # «амплитуда хода: 80». The short object is not the measurement, so «ход» does not keep 80.
    if owner and (_kind_word(owner) or _measure_noun(owner) or _delta_word(owner)):
        return False
    return _inflected(_name_before(span, number_start), stem)


def _keeps(span, stem, token):
    # The half-width in «диаметр: 50 ± 0,2» is not диаметр 0,2. The value in
    # front of the sign still is. «погрешность: ±0,5» keeps 0,5: nothing numeric
    # stands before the sign.
    numbers = [
        number
        for number in _hits(span, token)
        if not _number_before_tolerance(span, number.start())
        and not _date_number(span, number.start(), number.end())
        and not (
            _clock_number(span, number.start(), number.end())
            and not _owns_hours(span, number.start(), stem)
        )
    ]
    if len(stem) < 5:
        # «срок службы в 6 часов»: срок is shorter than five letters, and «в»
        # hides it from the short-name walk. The duration still belongs to срок.
        return any(
            _owns_hours(span, number.start(), stem) or _short_owns(span, number.start(), stem)
            for number in numbers
        )
    # «давление: 6 бар и температура: 80» is one clause, so the line window still
    # sees both numbers. 80 belongs to давление only when no other value with its
    # own label sits between them. «от 6 до 10» has no such label. A value that
    # stands before the attribute is kept only when it is not someone else's.
    # «рабочая температура: 80» shares «рабоч» with «рабочее давление», and
    # «температура составляет 80» shares the verb. Those words do not name 80.
    # «давление при температуре составляет 6» still keeps 6, and so does
    # «давление при температуре 80 градусов составляет 6»: 80 belongs to
    # температуре, and 6 is the only value of давление. «ток», «ход», «тип»
    # and «кпд» name the other number even though they are shorter than five
    # letters: «давление: 6 бар и ток: 80» is not давление 80.
    sought = _fold(stem)
    pattern = re.escape(stem) if sought == stem else rf"(?:{re.escape(stem)}|{re.escape(sought)})"
    stems = list(re.finditer(rf"(?<![0-9a-zа-я]){pattern}", span))
    for number in numbers:
        for found in stems:
            word = _word_at(span, found.start())
            if word in _LINKS:
                continue
            if _bridge_word(word) and _restates_earlier_kind(span, found.start(), stem):
                continue
            if found.end() <= number.start():
                left = found.end()
                if 0 < left < number.start() and span[left - 1].isalpha() and span[left].isalpha():
                    while left < number.start() and span[left].isalpha():
                        left += 1
                middle = span[left:number.start()]
                follow = span[number.start():]
                # «на входе и 6»: the qualifier before «и» names the earlier
                # value, so it must not confirm the later one. «давление 16 бар
                # и 6» still keeps давление, because another number sits in the gap.
                if _split_gap(middle) and _reading(middle, follow) is None:
                    continue
                # «насос номер 6 ... давление 8» and «6 бар — давление и
                # температура 80». The number's own name is another measurement.
                # «при температуре 80 градусов составляет» is not: it qualifies
                # the value that follows.
                if not _stated_condition(middle):
                    names = re.findall(r"[a-zа-яё]{5,}", middle)
                    # «перепад давления: 2»: давления is the object of перепад, not
                    # another measurement standing between the name and its number.
                    if (
                        _measure_label(names, stem)
                        and not _delta_word(word)
                        and (
                            not _kind_stem(stem)
                            or _plain_number(span[number.end():])
                            or _plain_number(span[:found.start()])
                        )
                    ):
                        continue
                    if _other_name(span, number.start(), stem) and (_reading(middle, follow) or _split_gap(middle)):
                        continue
            elif number.end() <= found.start():
                if _other_label(span, number.start(), found):
                    continue
                # «перепад давления 2 бар и рабочее давление 6». The 2 already
                # belongs to перепад, so the later давление does not take it.
                if _foreign_phrase(span, number.start(), stem):
                    continue
                middle = span[number.end():found.start()]
                follow = span[found.start():]
            else:
                continue
            other = _reading(middle, follow)
            label = re.search(r"[a-zа-яё]{5,}", middle)
            if other and label and not (found.end() <= number.start() and _stated_condition(middle)):
                continue
            # The stem has to be the noun that owns the number. A shared object
            # («масла», «насоса», «поршня»), a generic head («класс», «степень»,
            # «коэффициент») or a side mention («при температуре составляет»)
            # does not. «радиус поршня» owns 80; the object does not.
            if found.end() <= number.start() and _foreign_phrase(span, number.start(), stem):
                continue
            return True
    return False


def _from_question(fact, asked):
    token = fact[1]
    if any(ch.isdigit() for ch in token) and not any(ch.isalpha() for ch in token):
        return False
    return _grounded(fact, asked)


# Declined units. «градусов» does not pick one pressure out of two; «бар» is
# already glue, but the full word is not. «части» is not «час».
_UNITS = (
    "градус", "процент", "метр", "литр", "секунд", "минут", "час",
    "килограмм", "ампер", "вольт", "ватт", "паскал", "герц",
)


def _unit_word(word):
    for stem in _UNITS:
        if word.startswith(stem) and word[len(stem):] in _case_endings():
            return True
    return False


def _content_words(region):
    # Words that can tell two values of one measurement apart.
    # «на выходе» keeps «выходе», «максимальное» keeps «максимальное».
    # A unit, a preposition or a linking verb does not.
    words = []
    for word in re.findall(r"[a-zа-яё]{3,}", (region or "").lower().replace("ё", "е")):
        if word in _GLUE or word in _LINKS or word in _PRONOUNS or word in _ASKED or _bridge_word(word) or _unit_word(word):
            continue
        words.append(word)
    return words


def _gap_parts(region):
    # «2 бар на входе и 6» — the conjunction gives «на входе» to 2.
    # «2 бар и на выходе 6» — «на выходе» names 6. A comma does the same:
    # «2 бар, давление на выходе 6».
    found = re.search(
        r"(?<![0-9a-zа-яё])(?:,|" + "|".join(sorted(_CONJUNCTIONS, key=len, reverse=True)) + r")(?![0-9a-zа-яё])",
        region or "",
        re.IGNORECASE,
    )
    if not found:
        return None
    return region[:found.start()], region[found.end():]


def _label_words(span, start, end):
    # Words written with this number, up to the neighboring number.
    # «давление на входе 2 бар и давление на выходе 6» gives «входе» to 2
    # and «выходе» to 6. «6 бар — давление» has nothing before it, so the
    # name after the dash belongs to 6.
    # «давление 2 бар на входе и 6 бар на выходе» puts the qualifier after
    # the value. The words in front are only «давление», so the inlet was
    # left on 6 and the outlet claim took the inlet pressure.
    previous = 0
    for match in _PLAIN_NUMBER.finditer(span):
        if match.start() >= start:
            break
        previous = match.end()
    nxt = len(span)
    for match in _PLAIN_NUMBER.finditer(span):
        if match.start() >= end:
            nxt = match.start()
            break
    before = span[previous:start]
    after = span[end:nxt]
    split_before = _gap_parts(before)
    # No conjunction: the words in front name this number.
    # «бар на входе и» keeps «входе» with the earlier value.
    preface = split_before[1] if split_before else before
    split_after = _gap_parts(after)
    if split_after:
        postfix = split_after[0]
    elif nxt == len(span):
        # «6 бар на выходе» and «6 бар — давление»: nothing follows the name.
        postfix = after
    else:
        # «80 градусов рабочее давление составляет 6»: those words name 6.
        # «от 6 до 10»: «до» is not a new claim, and 10 keeps the name in front.
        postfix = ""
    words = _content_words(preface)
    for word in _content_words(postfix):
        if word not in words:
            words.append(word)
    return words


def _head_key(word):
    # The measurement itself, not the qualifier that picks one of its values.
    # «давлении» is «давлен», «ходе» is «ход», «радиусе» is «радиус».
    folded = _fold(word)
    if _kind_noun(word):
        for kind in _kinds():
            if folded.startswith(kind):
                return kind
    if _measure_noun(word):
        for stem in _measures():
            if _inflected(word, stem) or folded.startswith(stem):
                return stem
    if _size_word(word):
        for stem in _sizes():
            if word.startswith(stem):
                return stem
    if _delta_word(word):
        for stem in _deltas():
            if word.startswith(stem):
                return stem
    return ""


def _answers_head(stem, heads):
    return any(stem == head or stem == head[:5] for head in heads)


def _genitive_shape(word):
    # «масла» and «воды» are the object of a measurement whose name was left
    # out. «насос» and «выход» end on a consonant and name the number itself.
    return any(word.endswith(ending) and len(word) > len(ending) + 2 for ending in ("а", "я", "ы", "и", "ов", "ев", "ей"))


def _qualifier_only(text, number_start):
    # A later value still belongs to the measurement named before a clause
    # break when it adds only a qualifier. «на выходе: 6», «16 бар
    # максимальное» and «масла: 16» do. «насос №4» and «4 насоса» name a
    # different fact, so the pressure must not inherit them.
    left, right = _bounds(text, number_start)
    span = _case(text[left:right])
    local = number_start - left
    for match in re.finditer(r"[a-zа-яё]{3,}", span):
        word = match.group(0)
        if word in _GLUE or word in _LINKS or word in _PRONOUNS or word in _ASKED or _bridge_word(word) or _unit_word(word):
            continue
        if _head_key(word):
            return False
        if _ADJECTIVE.search(word) and not _kind_noun(word):
            continue
        preceded = span[:match.start()].rstrip(" \t:;—–-\u2212()«»\",")
        prev = re.search(r"([a-zа-яё]+)$", preceded)
        if prev and prev.group(1) in _PREPOSITIONS:
            continue
        if match.end() <= local and _genitive_shape(word) and not re.search(r"[a-zа-яё]", span[match.end():local]):
            continue
        return False
    return True


def _carried_heads(text, earlier, later):
    # «На входе давление: 2 бар; на выходе: 6 бар». The break makes two
    # spans, and the second never repeats давление. It is still that
    # measurement, so 2 must not confirm the outlet. «Давление: 6 бар;
    # температура: 80» names a new measurement. «4 насоса; давление 8»
    # has nothing to carry forward.
    _, _, token, span, words = earlier
    later_at, _, _, _, later_words = later
    heads = {key for word in words if (key := _head_key(word))}
    later_heads = {key for word in later_words if (key := _head_key(word))}
    if not heads or later_heads - heads:
        return set()
    kept = {head for head in heads if _keeps(span, head, token)}
    if not kept or not _qualifier_only(text, later_at):
        return set()
    return kept


def _qualifier_conflict(text, start, answer_stems, end=None):
    # «давление на выходе равно 2» is not the inlet pressure, and
    # «максимальное давление равно 6» is not the minimum. The head is the
    # same measurement, so the word that picks the value has to sit with
    # the number. «давление насоса» may still be 6 when the pump is named
    # on another line, and «рабочее давление» may still be 6 beside
    # «рабочая температура»: those are different measurements.
    # «12 000» is one value. A plain scan starts at «000», misses the hit,
    # and then «давление на выходе 12 000» takes the inlet. A signed hit
    # starts on the minus while the digits start one character later, so
    # «давление на выходе -12» would take the inlet the same way. The hit
    # and the value overlap in both cases.
    signed = _signs(text or "")
    found = []
    for match in _VALUE.finditer(signed):
        left, right = _bounds(signed, match.start())
        span = signed[left:right]
        words = _label_words(span, match.start() - left, match.end() - left)
        # The magnitude of «-12» is not that value. The keep-check has to see
        # the sign, or the inlet's «-12» looks like a different number.
        number = match.group(0)
        if _negated(text or "", match.start()):
            number = "-" + number
        found.append((match.start(), match.end(), number, span, words))
    stop = start + 1 if end is None else end
    current = next((item for item in found if item[0] < stop and item[1] > start), None)
    if current is None:
        return False
    current_at, _, token, span, words = current
    # «максимальное давление 16 бар и 6 бар»: 6 has no words of its own,
    # so it still carries максимальное. A different word, as in
    # «и на выходе 6», is another value and must not inherit.
    if not words:
        return False
    here_stems = {word[:5] for word in words}
    here_heads = {key for word in words if (key := _head_key(word))}
    for other_item in found:
        other_start, _, other_token, other_span, other_words = other_item
        if other_start == current_at:
            continue
        other_heads = {key for word in other_words if (key := _head_key(word))}
        shared = {
            head for head in here_heads | other_heads
            if _keeps(span, head, token) and _keeps(other_span, head, other_token)
        }
        # «давление: 2 бар; на выходе: 6». The break drops the repeated name,
        # so the outlet is invisible unless the first head is carried over.
        if not shared and span != other_span:
            first, second = (current, other_item) if current_at < other_start else (other_item, current)
            shared = _carried_heads(signed, first, second)
        # «давление на входе 2 бар и на выходе 6» leaves the second value
        # without its own head. Those words still belong to the same measurement.
        # A headless number earlier in the clause does not: «в цехе 4 насоса
        # с давлением 8» may still be давление 8.
        elided = (
            not shared
            and span == other_span
            and other_start > start
            and not other_heads
            and bool(other_words)
        )
        if not shared and not elided:
            continue
        other_stems = {word[:5] for word in other_words}
        for stem in answer_stems:
            if _answers_head(stem, shared):
                continue
            if stem in other_stems and stem not in here_stems:
                return True
    return False


def _borrowed(text, start, end, stems):
    # An exact digit match. «на выходе значение равно 2000» is not the inlet,
    # and not the year, when «выходе» is written on another number.
    # «выпущен в 2019» stays: «выпущен» labels neither the year nor the pressure.
    signed = _signs(text or "")
    labels = []
    for match in _VALUE.finditer(signed):
        left, right = _bounds(signed, match.start())
        span = signed[left:right]
        words = _label_words(span, match.start() - left, match.end() - left)
        labels.append((match.start(), match.end(), {word[:5] for word in words}))
    current = next((keys for pos, stop, keys in labels if pos <= start < stop or start <= pos < end), None)
    if current is None:
        return False
    wanted = {stem[:5] for stem in stems if len(stem) >= 3}
    for pos, stop, keys in labels:
        if pos <= start < stop or start <= pos < end:
            continue
        if any(stem in keys and stem not in current for stem in wanted):
            return True
    return False


def _tolerance_grounded(token, stems, text):
    # «диаметр равен 50 ± 0,2» is grounded when 50 belongs to диаметр and the
    # same clause carries ± 0,2. A different half-width, or a bare 0,2, is not.
    for match in _hits(text, token):
        base = _number_before_tolerance(text, match.start())
        if not base:
            continue
        left, right = _bounds(text, match.start())
        nearby = text[left:right]
        if any(_keeps(nearby, stem, base) for stem in stems):
            return True
    return False


def _grounded(fact, text):
    kind, token = fact[0], _flat(fact[1])
    if kind == "stem":
        return re.search(rf"(?<![0-9a-zа-я]){re.escape(token[:5])}", text) is not None
    if len(fact) > 3 and fact[3]:
        return _tolerance_grounded(token, fact[2], text)
    places = list(_hits(text, token))
    if kind == "exact" or not places:
        if places and kind == "exact" and len(fact) > 2 and not any(ch.isalpha() for ch in token):
            return any(not _borrowed(text, match.start(), match.end(), fact[2]) for match in places)
        return bool(places)
    for match in places:
        nearby = _span(text, match.start())
        if not any(_keeps(nearby, stem, token) for stem in fact[2]):
            continue
        if _qualifier_conflict(text, match.start(), fact[2], match.end()):
            continue
        return True
    return False


def _source(number, chunk):
    row = {
        "number": number,
        "document_name": chunk["document_name"],
        "section": chunk.get("section", ""),
        "chunk_index": chunk.get("chunk_index", 0),
    }
    if chunk.get("kb_id"):
        row["kb_id"] = chunk["kb_id"]
        row["kb_name"] = chunk.get("kb_name") or ""
    if chunk.get("text"):
        row["text"] = chunk["text"]
    return row


def _copied(text, flats):
    words = _flat(re.sub(r"\[[\d,\s]+\]", " ", text)).split()
    spans = {" ".join(words[start:start + SPAN]) for start in range(len(words) - SPAN + 1)}
    grams = [" ".join(words[start:start + 4]) for start in range(len(words) - 3)]
    repeated = any(grams.count(gram) >= 3 for gram in set(grams))
    return text.strip().count("\n") >= 2 or repeated or any(span in flat for span in spans for flat in flats)


def _verdict(status, missing=(), feedback="", sources=()):
    return {"status": status, "missing": list(missing), "feedback": feedback, "sources": list(sources)}


def _predicate(query):
    tokens = re.findall(r"[а-яё]+", _flat(query))
    if "ли" not in tokens:
        return ""
    index = tokens.index("ли")
    return tokens[index - 1] if index else ""


def _clause(text, start):
    marks = ".!?,;\n"
    left = max(text.rfind(mark, 0, start) for mark in marks)
    right = len(text)
    for mark in marks:
        pos = text.find(mark, start)
        if pos != -1:
            right = min(right, pos)
    return text[left + 1:right]


_PREPOSITIONS = {"у", "в", "во", "на", "для", "от", "из", "с", "со", "к", "ко", "по", "о", "об", "при", "за", "до", "без", "под", "над", "про", "через"}
_INFLECTION = {"ен", "на", "но", "ны", "ая", "ое", "ые", "ий", "ый", "ой", "яя", "ее"}
_PREDICATE_ENDINGS = ("", "а", "о", "е", "ы", "и", "у", "я", "й", "н", "ен", "на", "но", "ны", "ный", "ная", "ное", "ные")


def _forms(word):
    # нужно/нужна/нужен and должен/должна differ inside the first five letters,
    # so a fixed five-letter prefix misses the negation and a false «Да» passes.
    forms = {word}
    if len(word) < 4:
        return forms
    bases = []
    if word[-1] in "аеёиоуыэюя":
        bases.append(word[:-1])
    if len(word) >= 5 and word[-2:] in _INFLECTION:
        bases.append(word[:-2])
    for base in bases:
        if len(base) < 3:
            continue
        for ending in _PREDICATE_ENDINGS:
            form = base + ending
            if len(form) >= 4:
                forms.add(form)
    return forms


def _focus_stem(query):
    tokens = re.findall(r"[а-яёa-z]+", _flat(query))
    if "ли" not in tokens:
        return ""
    for token in tokens[tokens.index("ли") + 1:]:
        if token in _PREPOSITIONS or len(token) <= 2:
            continue
        return token[:5]
    return ""


def _in_clause(clause, stem):
    key = stem[:5]
    if len(key) < 3:
        return False
    return re.search(rf"(?<![0-9a-zа-я]){re.escape(key)}", clause) is not None


def _denied(query, flats):
    stems = []
    for word in _words(query):
        stem = word[:5]
        if stem not in stems:
            stems.append(stem)
    if not stems:
        return False
    predicate = _predicate(query)
    subjects = [stem for stem in stems if stem != predicate[:5]]
    focus = _focus_stem(query)
    text = "\n".join(flats)
    cues = [rf"(?<![0-9a-zа-я])не {re.escape(stem)}" for stem in stems]
    for form in _forms(predicate):
        cues.append(rf"(?<![0-9a-zа-я])не {re.escape(form)}(?![0-9a-zа-я])")
    for pattern in dict.fromkeys(cues):
        for match in re.finditer(pattern, text):
            clause = _clause(text, match.start())
            if not subjects or any(_in_clause(clause, stem) for stem in subjects):
                return True
    for match in re.finditer(r"(?<![0-9a-zа-я])(?:нет|нельзя)(?![0-9a-zа-я])", text):
        clause = _clause(text, match.start())
        # «нет» next to another noun from the question is not a negation of the asked thing.
        if focus and not _in_clause(clause, focus):
            continue
        if not subjects or any(_in_clause(clause, stem) for stem in subjects):
            return True
    return False


def _inverted(query, answer, flats):
    if "ли" not in re.findall(r"[а-яё]+", query.lower()):
        return False
    start = _flat(answer)
    says_yes = start.startswith("да")
    says_no = start.startswith("нет")
    if not says_yes and not says_no:
        return False
    denied = _denied(query, flats)
    if denied and says_yes:
        return True
    if (not denied) and says_no:
        return True
    return False


def _list_gap(query, answer, flats, cited=None):
    wants_count = _count_ask(query)
    wants_items = _list_ask(query) and not wants_count
    if not wants_items and not wants_count:
        return False
    indices = cited or list(range(1, len(flats) + 1))
    body = _flat(re.sub(r"\[[\d,\s]+\]", " ", answer))
    saw = False
    for number in indices:
        text = flats[number - 1]
        listed = re.search(r"список:\s*(.+)", text)
        numbered = re.search(r"разных значений[^:]*:\s*(\d+)", text)
        if not listed and not numbered:
            continue
        saw = True
        items = [part.strip(" .;") for part in re.split(r",| и ", listed.group(1)) if part.strip(" .;")] if listed else []
        count = numbered.group(1) if numbered else None
        items_hit = bool(items and all(_flat(item) in body for item in items))
        count_hit = bool(count and re.search(rf"(?<!\d){re.escape(count)}(?!\d)", body))
        if wants_items and items_hit:
            return False
        if wants_count and (count_hit or items_hit):
            return False
    return saw


def _shifted_definition(query, answer, bodies):
    if not re.search(r"что\s+так", _flat(query)):
        return False
    words = _words(query)
    if not words:
        return False
    term = words[0]
    purpose = re.compile(r"устанавлива|предназначен|регламентир|определя", re.IGNORECASE)
    claimed = False
    for sentence in re.split(r"[.!?]\s+|\n+", answer or ""):
        if not purpose.search(sentence):
            continue
        claimed = True
        if term not in _flat(sentence):
            return True
    if not claimed:
        return False
    for body in bodies:
        for sentence in re.split(r"[.!?]\s+|\n+", body or ""):
            if term in _flat(sentence) and purpose.search(sentence):
                return False
    return True


def _section_code_conflict(chunk, wanted):
    section_codes = set(_codes(chunk.get("section") or ""))
    return bool(section_codes) and not (section_codes & wanted)


def _keep_cited(used, scores, facts, bodies):
    if len(used) < 2:
        return used
    best = max(scores[number - 1] for number in used)
    ranked = sorted(used, key=lambda number: (-scores[number - 1], number))
    covered = set()
    kept = []
    for number in ranked:
        if best and scores[number - 1] * 2 < best:
            continue
        owned = []
        for fact in facts:
            if fact[1] in covered or not _grounded(fact, bodies[number - 1]):
                continue
            owned.append(fact[1])
        if facts and not owned and scores[number - 1] != best:
            continue
        if not facts and kept and scores[number - 1] != best:
            continue
        kept.append(number)
        covered.update(owned)
    return kept or [ranked[0]]


def check_agent(answer, chunks, query="", known=None):
    """Подтвердить ответ по найденному тексту или вернуть отзыв. Модель не вызывается."""
    text = answer.strip()
    known = known or (lambda _term: True)
    absent = [token for token in _specific(query) if not known(_flat(token))]
    if not chunks or not text or absent or _flat(NO_ANSWER).rstrip(".") in _flat(text):
        return _verdict(MISSING)
    flats = [_flat(chunk["text"]) for chunk in chunks]
    bodies = [_case(chunk["text"]) for chunk in chunks]
    asked = " ".join(word for word in _flat(query).replace("?", " ").split() if known(word.strip(".,:;«»()")))
    if _copied(text, flats):
        return _verdict(UNCONFIRMED, feedback=COPIED)
    if _inverted(query, text, flats):
        return _verdict(UNCONFIRMED, feedback=INVERT)
    cited = []
    for group in re.findall(r"\[([\d,\s]+)\]", text):
        for number in re.findall(r"\d+", group):
            number = int(number)
            if not 1 <= number <= len(chunks):
                return _verdict(UNCONFIRMED, feedback=f"Ссылайся только на номера фрагментов от 1 до {len(chunks)}.")
            if number not in cited:
                cited.append(number)
    if _list_gap(query, text, flats, cited):
        return _verdict(UNCONFIRMED, feedback=LIST_GAP)
    if _dangling_list(text):
        return _verdict(UNCONFIRMED, feedback=LIST_GAP)
    if _shifted_definition(query, text, bodies):
        return _verdict(UNCONFIRMED, feedback=DEFINE)
    used = list(cited)
    missing = []
    facts = _facts(text)
    for fact in facts:
        if _from_question(fact, asked) or any(_grounded(fact, bodies[number - 1]) for number in used):
            continue
        holders = [number for number in range(1, len(chunks) + 1) if _grounded(fact, bodies[number - 1])]
        if holders:
            used.append(holders[0])
        elif fact[1] not in missing:
            missing.append(fact[1])
    if missing:
        feedback = "В прошлом ответе были данные, которых нет во фрагментах: " + ", ".join(missing) + ". Ответь заново только по фрагментам."
        return _verdict(UNCONFIRMED, missing, feedback)
    words = [("stem", word) for word in _words(re.sub(r"\[[\d,\s]+\]", " ", text)) if len(word) >= 5]
    asked_stems = {word[:5] for word in _words(asked) if len(word) >= 5}
    extra = [word for word in words if word[1][:5] not in asked_stems]
    example_stems = {
        word[:5]
        for item in fewshot()
        for word in _words(item.get("reply", ""))
        if len(word) >= 5
    }
    # Слово из примера короче 8 букв ответ не бракует. Иначе отказ ловит обычные слова вроде «равно».
    borrowed = [
        word for word in extra
        if len(word[1]) >= 8 and word[1][:5] in example_stems and not any(_grounded(word, body) for body in bodies)
    ]
    if borrowed:
        return _verdict(UNCONFIRMED, feedback=RETRY)
    if extra and not facts:
        grounded_extra = sum(1 for word in extra if any(_grounded(word, body) for body in bodies))
        if grounded_extra * 3 < len(extra):
            return _verdict(UNCONFIRMED, feedback=RETRY)
        scored = extra
    else:
        scored = words
    scores = [sum(_grounded(word, body) for word in scored) for body in bodies]
    if not any(scores):
        return _verdict(UNCONFIRMED, feedback=RETRY)
    used = [number for number in used if scores[number - 1] or any(_grounded(fact, bodies[number - 1]) for fact in facts)]
    if not used:
        best = max(scores)
        used = [number for number, score in enumerate(scores, 1) if score == best][:2]
    wanted = set(_codes(re.sub(r"\[[\d,\s]+\]", " ", text)))
    if wanted:
        coded = [number for number in used if not _section_code_conflict(chunks[number - 1], wanted)]
        if coded:
            used = coded
    used = _keep_cited(used, scores, facts, bodies)
    return _verdict(CONFIRMED, sources=[_source(number, chunks[number - 1]) for number in sorted(used)])
