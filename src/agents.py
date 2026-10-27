import re

from llm import complete, count_tokens
from store import search_chunks

NO_ANSWER = "В документах нет ответа."
CONFIRMED = "подтверждён"
UNCONFIRMED = "не подтверждён"
MISSING = "нет ответа"
PROMPT_TOKENS = 1500
SYSTEM = (
    "Отвечай на русском только по фрагментам ниже. "
    "После каждого факта ставь номер фрагмента, например [2]. "
    "Если фрагменты противоречат друг другу, скажи об этом. "
    "Названия, номера и коды переписывай из фрагментов без изменений. "
    "Строка «Разных значений в столбце … Список: …» перечисляет все значения столбца таблицы: "
    "назови число или перечисли весь список, когда нужно перечислить или посчитать. "
    "Если во фрагменте рядом с тем же сказуемым, что и в вопросе, стоит «не» или «нет», начни ответ со слова «Нет». "
    "Если ответа во фрагментах нет, напиши: В документах нет ответа."
)
TASK = (
    "Ответь на вопрос одним-тремя полными предложениями обычным текстом и после каждого факта поставь номер фрагмента в квадратных скобках. "
    "Если нужно перечислить, перечисли через запятую в одном предложении."
)
YES_NO = "Начни ответ со слова «Да» или «Нет»."
RETRY = "Прошлый ответ не содержал фактов из фрагментов. Ответь заново полным предложением по фрагментам."
COPIED = "Прошлый ответ переписывал фрагменты или повторялся. Ответь кратко своими словами в одном-трёх предложениях."
INVERT = "Вопрос с «ли»: начни с «Да» или «Нет» по отрицанию у того же сказуемого во фрагменте."
LIST_GAP = "В прошлом ответе не было полного списка или числа из строки «Разных значений». Перечисли все элементы или назови число."
SPAN = 30
_EXAMPLES = (
    (
        "Когда открыта библиотека?",
        ["Библиотека > Режим работы\nЧасы работы: с 9 до 18; Выходной: понедельник", "Библиотека > Фонд\nВ фонде 12 000 книг."],
        "Библиотека открыта с 9 до 18 часов, выходной день — понедельник [1].",
    ),
    (
        "Какие залы есть в библиотеке?",
        [
            "Библиотека > Залы\nТаблица 1 – Залы библиотеки\nЗал | Количество мест\nЧитальный: 40\nДетский: 25\nАрхивный: 10\n"
            "Разных значений в столбце «Зал»: 3. Список: Читальный, Детский, Архивный.",
            "Библиотека > Правила\nВ залах соблюдается тишина.",
        ],
        "В библиотеке три зала: Читальный, Детский и Архивный [1].",
    ),
    (
        "Нужно ли записываться заранее?",
        ["Библиотека > Правила\nЗапись заранее не нужна. Вход свободный."],
        "Нет, запись заранее не нужна [1].",
    ),
)
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
    if not work_turns or not _dependent(query):
        return query
    previous = work_turns[-1]
    extra = _anchors(previous.get("answer", ""))
    if extra:
        return f"{previous['query']} {query} {' '.join(extra)}"
    return f"{previous['query']} {query}"


def search_agent(clear_query, document_names=None):
    if document_names:
        return search_chunks(clear_query, 4, document_names)
    return search_chunks(clear_query, 4)


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


EXAMPLES = [_example(*example) for example in _EXAMPLES]


def build_prompt(query, chunks, previous=None, feedback=None, count=None, budget=PROMPT_TOKENS):
    count = count or count_tokens
    head, tail = _frame(query, previous, feedback)
    room = budget - count("\n\n".join(head + tail))
    parts = []
    for number, chunk in enumerate(chunks, 1):
        part = _fragment(number, chunk["document_name"], chunk["text"])
        cost = count(part)
        if cost > room:
            part = _trim(part, room, count)
            if part:
                parts.append(part)
            break
        parts.append(part)
        room -= cost
    return "\n\n".join(head + parts + tail)


def answer_agent(query, clear_query, chunks, work_turns, feedback=None):
    if not chunks:
        return NO_ANSWER
    previous = work_turns[-1] if work_turns and clear_query != query else None
    return complete(SYSTEM, build_prompt(query, chunks, previous, feedback), examples=EXAMPLES)


def _facts(answer):
    text = re.sub(r"\[[\d,\s]+\]", " ", answer)
    facts = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        context = tuple(word[:5] for word in _words(sentence) if len(word) >= 5)
        for match in _TOKEN.finditer(sentence):
            token = match.group(0)
            before = sentence[:match.start()].rstrip()
            start = not before or before[-1] in ".!?:\n«\"("
            if any(ch.isdigit() for ch in token):
                short = sum(ch.isdigit() for ch in token) <= 2
                facts.append(("near", token, context) if short and context else ("exact", token))
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


def _grounded(fact, text):
    kind, token = fact[0], _flat(fact[1])
    if kind == "stem":
        return re.search(rf"(?<![0-9a-zа-я]){re.escape(token[:5])}", text) is not None
    places = [match.start() for match in re.finditer(rf"(?<![0-9a-zа-я_]){re.escape(token)}(?![0-9a-zа-я_])", text)]
    if kind == "exact" or not places:
        return bool(places)
    for place in places:
        nearby = text[max(0, place - 80):place + 80]
        if any(re.search(rf"(?<![0-9a-zа-я]){re.escape(stem)}", nearby) for stem in fact[2]):
            return True
    return False


def _source(number, chunk):
    return {"number": number, "document_name": chunk["document_name"], "section": chunk.get("section", "")}


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
_ENDINGS = ("", "а", "о", "е", "ы", "и", "у", "я", "й", "н", "ен", "на", "но", "ны", "ный", "ная", "ное", "ные")


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
        for ending in _ENDINGS:
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


def _negated(query, flats):
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
    negated = _negated(query, flats)
    if negated and says_yes:
        return True
    if (not negated) and says_no:
        return True
    return False


def _list_gap(query, answer, flats):
    asked = query.lower()
    wants_items = any(marker in asked for marker in ("какие", "перечисли"))
    wants_count = "сколько" in asked
    if not wants_items and not wants_count:
        return False
    items, count = [], None
    for text in flats:
        listed = re.search(r"список:\s*(.+)", text)
        if listed:
            items = [part.strip(" .;") for part in re.split(r",| и ", listed.group(1)) if part.strip(" .;")]
        numbered = re.search(r"разных значений[^:]*:\s*(\d+)", text)
        if numbered:
            count = numbered.group(1)
    if not items and not count:
        return False
    body = _flat(re.sub(r"\[[\d,\s]+\]", " ", answer))
    items_hit = bool(items and all(_flat(item) in body for item in items))
    count_hit = bool(count and re.search(rf"(?<!\d){re.escape(count)}(?!\d)", body))
    if wants_items:
        return not items_hit
    return not (count_hit or items_hit)


def check_agent(answer, chunks, query="", known=None):
    text = answer.strip()
    known = known or (lambda _term: True)
    absent = [token for token in _specific(query) if not known(_flat(token))]
    if not chunks or not text or absent or _flat(NO_ANSWER).rstrip(".") in _flat(text):
        return _verdict(MISSING)
    flats = [_flat(chunk["text"]) for chunk in chunks]
    asked = " ".join(word for word in _flat(query).replace("?", " ").split() if known(word.strip(".,:;«»()")))
    if _copied(text, flats):
        return _verdict(UNCONFIRMED, feedback=COPIED)
    if _inverted(query, text, flats):
        return _verdict(UNCONFIRMED, feedback=INVERT)
    if _list_gap(query, text, flats):
        return _verdict(UNCONFIRMED, feedback=LIST_GAP)
    cited = []
    for group in re.findall(r"\[([\d,\s]+)\]", text):
        for number in re.findall(r"\d+", group):
            number = int(number)
            if not 1 <= number <= len(chunks):
                return _verdict(UNCONFIRMED, feedback=f"Ссылайся только на номера фрагментов от 1 до {len(chunks)}.")
            if number not in cited:
                cited.append(number)
    used = list(cited)
    missing = []
    facts = _facts(text)
    for fact in facts:
        if _grounded(fact, asked) or any(_grounded(fact, flats[number - 1]) for number in used):
            continue
        holders = [number for number in range(1, len(chunks) + 1) if _grounded(fact, flats[number - 1])]
        if holders:
            used.append(holders[0])
        elif fact[1] not in missing:
            missing.append(fact[1])
    if missing:
        feedback = "В прошлом ответе были данные, которых нет во фрагментах: " + ", ".join(missing) + ". Ответь заново только по фрагментам."
        return _verdict(UNCONFIRMED, missing, feedback)
    words = [("stem", word) for word in _words(re.sub(r"\[[\d,\s]+\]", " ", text)) if len(word) >= 5]
    scores = [sum(_grounded(word, flat) for word in words) for flat in flats]
    if not any(scores):
        return _verdict(UNCONFIRMED, feedback=RETRY)
    used = [number for number in used if scores[number - 1] or any(_grounded(fact, flats[number - 1]) for fact in facts)]
    if not used:
        best = max(scores)
        used = [number for number, score in enumerate(scores, 1) if score == best][:2]
    return _verdict(CONFIRMED, sources=[_source(number, chunks[number - 1]) for number in sorted(used)])
