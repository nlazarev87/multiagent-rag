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


def test_check_rejects_short_number_from_another_line():
    chunk = {"text": "Насос > Характеристики\nРабочее давление: 6 бар\nНомер цеха: 4", "document_name": "pump.md"}
    decimal = {"text": "Насос > Характеристики\nРабочее давление: 6,5 бар\nНомер цеха: 4", "document_name": "pump.md"}
    wrong = agents.check_agent("Рабочее давление насоса равно 4 бар [1].", [chunk])
    assert wrong["status"] == agents.UNCONFIRMED
    assert wrong["missing"] == ["4"]
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [chunk])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 6,5 бар [1].", [decimal])["status"] == agents.CONFIRMED
    asked = agents.check_agent(
        "Да, рабочее давление насоса равно 10 бар [1].",
        [chunk],
        "Верно ли, что давление равно 10 бар?",
        known=lambda term: True,
    )
    assert asked["status"] == agents.UNCONFIRMED
    assert "10" in asked["missing"]


def test_check_rejects_number_from_another_fact_in_the_same_sentence():
    joined = {"text": "Насос > Характеристики\nРабочее давление: 6 бар и температура: 80 градусов.", "document_name": "pump.md"}
    note = {"text": "Насос > Характеристики\nРабочее давление составляет 6 бар (цех номер 4).", "document_name": "pump.md"}
    ranged = {"text": "Насос > Режим\nРабочее давление: от 6 до 10 бар", "document_name": "pump.md"}
    coded = {"text": "Насос ХН-7 рабочее давление: 6 бар.", "document_name": "pump.md"}
    wrong = agents.check_agent("Рабочее давление насоса равно 80 бар [1].", [joined])
    assert wrong["status"] == agents.UNCONFIRMED
    assert wrong["missing"] == ["80"]
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [joined])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление равно 6 бар, температура равна 80 градусов [1].", [joined])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 4 бар [1].", [note])["missing"] == ["4"]
    assert agents.check_agent("Рабочее давление насоса равно 6 бар [1].", [note])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса от 6 до 10 бар [1].", [ranged])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса ХН-7 равно 6 бар [1].", [coded], "Какое давление у насоса ХН-7?")["status"] == agents.CONFIRMED


def test_check_rejects_three_digit_number_from_another_line():
    chunk = {"text": "Насос > Характеристики\nРабочее давление: 6 бар\nИнвентарный номер: 180", "document_name": "pump.md"}
    real = {"text": "Насос > Характеристики\nРабочее давление: 160 бар\nНомер: 12", "document_name": "pump.md"}
    wrong = agents.check_agent("Рабочее давление насоса равно 180 бар [1].", [chunk])
    assert wrong["status"] == agents.UNCONFIRMED
    assert wrong["missing"] == ["180"]
    assert agents.check_agent("Инвентарный номер насоса равен 180 [1].", [chunk])["status"] == agents.CONFIRMED
    assert agents.check_agent("Рабочее давление насоса равно 160 бар [1].", [real])["status"] == agents.CONFIRMED


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


def test_check_rejects_incomplete_list():
    chunk = {"text": "Цех > Смены\nРазных значений в столбце «Смена»: 3. Список: Утренняя, Дневная, Ночная.", "document_name": "charter.txt"}
    assert agents.check_agent("В цехе есть Утренняя и Дневная смены [1].", [chunk], "Какие смены есть в цехе?")["feedback"] == agents.LIST_GAP
    assert agents.check_agent("В цехе три смены: Утренняя, Дневная и Ночная [1].", [chunk], "Какие смены есть в цехе?")["status"] == agents.CONFIRMED


def test_check_rejects_empty_and_broken_answers():
    copied = "Цех имеет номер 4, в нём работают токари, слесари и наладчики, мастер цеха — Иванов, смена длится восемь часов, обед начинается в полдень и длится один час, склад находится рядом с цехом на первом этаже."
    shop = {"text": copied, "document_name": "charter.txt"}
    assert agents.check_agent("Да.", [PUMP])["status"] == agents.UNCONFIRMED
    assert agents.check_agent("Давление 6 бар [5].", [PUMP])["status"] == agents.UNCONFIRMED
    assert agents.check_agent(copied, [shop])["feedback"] == agents.COPIED
    assert agents.check_agent(agents.NO_ANSWER, [PUMP])["status"] == agents.MISSING
