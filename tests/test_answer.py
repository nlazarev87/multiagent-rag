import agents

PUMP = {"text": "Насос > Характеристики\nРабочее давление: 6 бар\nГод выпуска: 2019", "document_name": "pump.md", "section": "Насос > Характеристики"}
SHOP = {"text": "Цех имеет номер 4. Мастер цеха — Иванов.", "document_name": "charter.txt", "section": ""}


def _words(text):
    return len(text.split())


def test_answer_refuses_empty_chunks():
    assert agents.answer_agent("цвет", "цвет насоса", [], []) == agents.NO_ANSWER


def test_answer_calls_model_once_with_numbered_fragments(monkeypatch):
    calls = []
    monkeypatch.setattr(agents, "count_tokens", _words)
    monkeypatch.setattr(agents, "complete", lambda system, user, examples=(): calls.append((system, user, examples)) or "Давление равно 6 бар [1].")
    answer = agents.answer_agent("Какое давление у насоса?", "Какое давление у насоса?", [PUMP, SHOP], [])
    assert answer == "Давление равно 6 бар [1]."
    assert len(calls) == 1
    system, user, examples = calls[0]
    assert system == agents.SYSTEM
    assert examples == agents.EXAMPLES
    assert "Фрагмент 1 (документ pump.md):" in user
    assert "Фрагмент 2 (документ charter.txt):" in user
    assert user.count("Вопрос: Какое давление у насоса?") == 2
    assert agents.YES_NO not in user


def test_prompt_keeps_previous_turn_for_dependent_question(monkeypatch):
    monkeypatch.setattr(agents, "count_tokens", _words)
    seen = []
    monkeypatch.setattr(agents, "complete", lambda system, user, examples=(): seen.append(user) or "2019 [1].")
    turns = [{"query": "Какое давление у насоса?", "answer": "Давление равно 6 бар [1].", "document_names": ["pump.md"]}]
    clear = agents.clarify_agent("В каком году его выпустили?", turns)
    assert clear == "Какое давление у насоса? В каком году его выпустили? 6"
    agents.answer_agent("В каком году его выпустили?", clear, [PUMP], turns)
    assert "Прошлый вопрос: Какое давление у насоса?" in seen[0]


def test_yes_no_hint_only_for_questions_with_li(monkeypatch):
    assert agents.YES_NO in agents.build_prompt("Есть ли у насоса фильтр?", [PUMP], count=_words)
    assert agents.YES_NO not in agents.build_prompt("Какое давление у насоса?", [PUMP], count=_words)


def test_prompt_fits_token_budget():
    long = {"text": "\n".join(f"строка {number} " + "слово " * 30 for number in range(40)), "document_name": "long.txt"}
    prompt = agents.build_prompt("Что в длинном файле?", [long, long], count=_words, budget=300)
    assert _words(prompt) <= 300
    assert "Фрагмент 1" in prompt and "Фрагмент 2" not in prompt


def test_check_confirms_grounded_answer_and_cites_sources():
    verdict = agents.check_agent("Рабочее давление насоса равно 6 бар, год выпуска 2019 [1].", [PUMP, SHOP])
    assert verdict["status"] == agents.CONFIRMED
    assert [source["document_name"] for source in verdict["sources"]] == ["pump.md"]


def test_check_rejects_number_missing_from_fragments():
    verdict = agents.check_agent("Насос выпущен в 2021 году [1].", [PUMP, SHOP])
    assert verdict["status"] == agents.UNCONFIRMED
    assert verdict["missing"] == ["2021"]
    assert "2021" in verdict["feedback"]


def test_check_fixes_wrong_citation():
    verdict = agents.check_agent("Насос выпущен в 2019 году [2].", [PUMP, SHOP])
    assert verdict["status"] == agents.CONFIRMED
    assert [source["number"] for source in verdict["sources"]] == [1]


def test_check_allows_names_from_question():
    verdict = agents.check_agent("Давление насоса ХН-7 равно 6 бар [1].", [PUMP], "Какое давление у насоса ХН-7?")
    assert verdict["status"] == agents.CONFIRMED


def test_check_refuses_when_question_names_unknown_thing():
    verdict = agents.check_agent("В насосе используется версия 2019 [1].", [PUMP], "Какая версия Python в насосе?", known=lambda term: term != "python")
    assert verdict["status"] == agents.MISSING


def test_check_rejects_yes_when_fragment_negates():
    chunk = {"text": "Охлаждение насоса не требуется. Давление равно 6 бар.", "document_name": "pump.md"}
    assert agents.check_agent("Да, охлаждение требуется [1].", [chunk], "Требуется ли охлаждение насоса?")["feedback"] == agents.INVERT
    assert agents.check_agent("Нет, охлаждение не требуется [1].", [chunk], "Требуется ли охлаждение насоса?")["status"] == agents.CONFIRMED
    absent = {"text": "Фильтра нет.", "document_name": "pump.md"}
    assert agents.check_agent("Да, фильтр есть [1].", [absent], "Есть ли фильтр?")["feedback"] == agents.INVERT
    assert agents.check_agent("Нет, фильтра нет [1].", [absent], "Есть ли фильтр?")["status"] == agents.CONFIRMED
    cooling = {"text": "Охлаждение требуется.", "document_name": "pump.md"}
    other = {"text": "Замена фильтра не требуется.", "document_name": "filter.md"}
    assert agents.check_agent("Да, охлаждение требуется [1].", [cooling, other], "Требуется ли охлаждение?")["status"] == agents.CONFIRMED
    assert agents.check_agent("Нет, охлаждение не требуется [2].", [cooling, other], "Требуется ли охлаждение?")["feedback"] == agents.INVERT
    library = {"text": "Запись заранее не нужна. Вход свободный.", "document_name": "rules.md"}
    assert agents.check_agent("Да, записываться заранее нужно [1].", [library], "Нужно ли записываться заранее?")["feedback"] == agents.INVERT
    assert agents.check_agent("Нет, запись заранее не нужна [1].", [library], "Нужно ли записываться заранее?")["status"] == agents.CONFIRMED
    permit = {"text": "Допуск не нужен. Вход свободный.", "document_name": "rules.md"}
    assert agents.check_agent("Да, допуск нужен [1].", [permit], "Нужно ли получать допуск?")["feedback"] == agents.INVERT
    assert agents.check_agent("Нет, допуск не нужен [1].", [permit], "Нужно ли получать допуск?")["status"] == agents.CONFIRMED
    installed = {"text": "Фильтр установлен на входе. Запасного насоса нет.", "document_name": "pump.md"}
    assert agents.check_agent("Да, фильтр есть [1].", [installed], "Есть ли фильтр у насоса?")["status"] == agents.CONFIRMED
    assert agents.check_agent("Нет, фильтра нет [1].", [installed], "Есть ли фильтр у насоса?")["feedback"] == agents.INVERT


def test_check_rejects_incomplete_list():
    chunk = {"text": "Цех > Смены\nРазных значений в столбце «Смена»: 3. Список: Утренняя, Дневная, Ночная.", "document_name": "charter.txt"}
    assert agents.check_agent("В цехе есть Утренняя и Дневная смены [1].", [chunk], "Какие смены есть в цехе?")["feedback"] == agents.LIST_GAP
    assert agents.check_agent("В цехе 3 смены: Утренняя и Дневная [1].", [chunk], "Какие смены есть в цехе?")["feedback"] == agents.LIST_GAP
    assert agents.check_agent("В цехе 13 смен [1].", [chunk], "Сколько смен в цехе?")["feedback"] == agents.LIST_GAP
    assert agents.check_agent("В цехе три смены: Утренняя, Дневная и Ночная [1].", [chunk], "Какие смены есть в цехе?")["status"] == agents.CONFIRMED
    assert agents.check_agent("В цехе 3 смены [1].", [chunk], "Сколько смен в цехе?")["status"] == agents.CONFIRMED


def test_check_rejects_empty_and_broken_answers():
    copied = "Цех имеет номер 4, в нём работают токари, слесари и наладчики, мастер цеха — Иванов, смена длится восемь часов, обед начинается в полдень и длится один час, склад находится рядом с цехом на первом этаже."
    shop = {"text": copied, "document_name": "charter.txt"}
    assert agents.check_agent("Да.", [PUMP])["status"] == agents.UNCONFIRMED
    assert agents.check_agent("Давление 6 бар [5].", [PUMP])["status"] == agents.UNCONFIRMED
    assert agents.check_agent(copied, [shop])["feedback"] == agents.COPIED
    assert agents.check_agent(agents.NO_ANSWER, [PUMP])["status"] == agents.MISSING
