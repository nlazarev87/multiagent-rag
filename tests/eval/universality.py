import json
import os
import re
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
EVAL = Path(__file__).resolve().parent
PUMP = ROOT / "tests" / "docs" / "pump.md"
LIBRARY = ROOT / "tests" / "corpora" / "library"
QUESTIONS = json.loads((EVAL / "questions.json").read_text(encoding="utf-8"))
EDGE = "0-9A-Za-zА-Яа-яЁё_"
CORPUS_NEEDLES = (
    "Н-12",
    "Читальный",
    "Детский",
    "Архивный",
    "Запись заранее не нужна",
)


def question_needles():
    found = set()
    for item in QUESTIONS:
        for fact in item.get("facts", []):
            for option in fact if isinstance(fact, list) else [fact]:
                if len(option) >= 4:
                    found.add(option)
        for phrase in item.get("evidence", []) + item.get("evidence_any", []) + item.get("together", []):
            if len(phrase) >= 4:
                found.add(phrase)
        for token in re.findall(r"[0-9A-Za-zА-Яа-яЁё_.-]+", item["query"]):
            token = token.strip(".-")
            if len(token) >= 3 and sum(ch.isupper() for ch in token) >= 2:
                found.add(token)
        if item.get("document") not in (None, "*"):
            found.add(Path(item["document"]).stem)
    return found


def leakage_needles():
    return sorted(question_needles() | set(CORPUS_NEEDLES))


def src_files():
    return [path for path in SRC.rglob("*") if path.suffix in {".py", ".html", ".js"}]


def src_hits(needles=None):
    needles = needles or leakage_needles()
    bodies = {path: path.read_text(encoding="utf-8") for path in src_files()}
    hits = []
    for needle in needles:
        flags = 0 if needle.upper() == needle else re.IGNORECASE
        pattern = re.compile(f"(?<![{EDGE}]){re.escape(needle)}(?![{EDGE}])", flags)
        for path, body in bodies.items():
            if pattern.search(body):
                hits.append(f"{path.relative_to(ROOT)}: {needle}")
    return hits


def measure_leakage():
    hits = src_hits()
    return {
        "now": float(len(hits)),
        "n": max(1, len(leakage_needles())),
        "hits": len(hits),
        "extra": {"lines": hits},
    }


def _asked_line(user):
    match = re.search(r"Вопрос:\s*(.+)", user)
    return (match.group(1) if match else user).splitlines()[0]


def _complete_from_prompt(system, user, max_tokens=None, examples=()):
    from agents import NO_ANSWER

    asked = _asked_line(user).lower()
    if "обозначен" in asked and "Н-12" in user:
        return "Насос имеет обозначение Н-12 [1]."
    if "залы" in asked and "Читальный" in user:
        return "В библиотеке залы Читальный, Детский и Архивный [1]."
    if ("открыта" in asked or "часы" in asked) and "с 9 до 18" in user:
        return "Библиотека открыта с 9 до 18 [1]."
    return NO_ANSWER


def _has_any(text, needles):
    flat = (text or "").lower()
    return any(needle.lower() in flat for needle in needles)


def _probe_corpus(store, agents, ingest_dir, corpus, inside_query, inside_needles, outside_query, outside_needles):
    store.reset()
    store.upsert_chunks(ingest_dir(corpus))
    inside_chunks = store.search_chunks(inside_query)
    inside = agents.answer_agent(inside_query, inside_query, inside_chunks, [])
    outside_chunks = store.search_chunks(outside_query)
    outside = agents.answer_agent(outside_query, outside_query, outside_chunks, [])
    leaked = _has_any(" ".join(chunk["text"] for chunk in outside_chunks), outside_needles)
    inside_ok = _has_any(inside, inside_needles) and agents.NO_ANSWER not in inside
    outside_ok = agents.NO_ANSWER in outside and not _has_any(outside, outside_needles)
    cited = bool(re.search(r"\[\d+\]", inside))
    verdict = agents.check_agent(inside, inside_chunks, inside_query, lambda _term: True)
    grounded = verdict["status"] == agents.CONFIRMED
    return inside_ok and outside_ok and not leaked, cited and grounded, inside, outside


def measure_swap():
    import agents
    import store
    from ingest import ingest_dir

    saved_chroma = store.CHROMA
    saved_complete = agents.complete
    saved_count = agents.count_tokens
    hits = 0
    cites = 0
    total = 2
    try:
        agents.complete = _complete_from_prompt
        agents.count_tokens = lambda text: max(1, len((text or "").split()))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = Path(raw)
            store.CHROMA = root / "chroma-pump"
            pump_dir = root / "pump"
            pump_dir.mkdir()
            shutil.copy(PUMP, pump_dir / PUMP.name)
            pump_ok, pump_cite, *_ = _probe_corpus(
                store, agents, ingest_dir, pump_dir,
                "Какое обозначение у насоса?", ("Н-12",),
                "Когда открыта библиотека?", ("9 до 18", "Читальный"),
            )
            hits += int(pump_ok)
            cites += int(pump_cite)
            store.reset()
            store.CHROMA = root / "chroma-library"
            library_ok, library_cite, *_ = _probe_corpus(
                store, agents, ingest_dir, LIBRARY,
                "Какие залы есть в библиотеке?", ("Читальный", "Детский", "Архивный"),
                "Какое обозначение у насоса?", ("Н-12",),
            )
            hits += int(library_ok)
            cites += int(library_cite)
            store.reset()
    finally:
        agents.complete = saved_complete
        agents.count_tokens = saved_count
        store.reset()
        store.CHROMA = saved_chroma
        store.reset()
    return {
        "swap": {"now": hits / total, "n": total, "hits": hits},
        "citation": {"now": cites / total, "n": total, "hits": cites},
    }


def _chunk(text, name, index, kind):
    return {
        "text": text,
        "embed": text,
        "document_name": name,
        "chunk_index": index,
        "checksum": "config-only",
        "section": "",
        "kind": kind,
        "group": "",
        "head": "",
        "version": 2,
    }


def measure_config_only():
    import agents
    import settings
    import store

    saved_chroma = store.CHROMA
    saved_config = os.environ.get("CONFIG_DIR")
    hits = 0
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = Path(raw)
            cfg = root / "config"
            shutil.copytree(ROOT / "config", cfg)
            os.environ["CONFIG_DIR"] = str(cfg)
            settings.reload()
            store.CHROMA = root / "chroma"
            store.reset()
            store.upsert_chunks([
                _chunk("Код участка АЛЬФА-77 стоит в тексте.", "mix.md", 0, "text"),
                _chunk("Разных значений в столбце «Код»: 1. Список: BETA-01.", "mix.md", 1, "overview"),
            ])
            opened = store.search_chunks("АЛЬФА-77")
            open_ok = any("АЛЬФА-77" in chunk["text"] for chunk in opened)
            routing = json.loads((cfg / "routing.json").read_text(encoding="utf-8"))
            routing["where"] = {"kind": "overview"}
            (cfg / "routing.json").write_text(json.dumps(routing, ensure_ascii=False, indent=2), encoding="utf-8")
            settings.reload()
            filtered = store.search_chunks("АЛЬФА-77")
            filter_ok = all(chunk.get("kind") != "text" for chunk in filtered)
            filter_ok = filter_ok and not any("АЛЬФА-77" in chunk["text"] for chunk in filtered)
            (cfg / "check_lexicon.json").write_text("{}", encoding="utf-8")
            settings.reload()
            agents.reload_behavior()
            verdict = agents.check_agent(
                "Код участка BETA-01 [1].",
                [{"text": "Разных значений в столбце «Код»: 1. Список: BETA-01.", "document_name": "mix.md", "section": ""}],
                "Какой код участка?",
                lambda _term: True,
            )
            lexicon_ok = verdict["status"] in {agents.CONFIRMED, agents.UNCONFIRMED, agents.MISSING}
            hits = int(open_ok and filter_ok and lexicon_ok)
            store.reset()
    finally:
        if saved_config is None:
            os.environ.pop("CONFIG_DIR", None)
        else:
            os.environ["CONFIG_DIR"] = saved_config
        settings.reload()
        agents.reload_behavior()
        store.reset()
        store.CHROMA = saved_chroma
        store.reset()
    return {"now": float(hits), "n": 1, "hits": hits}


def measure_universality():
    leakage = measure_leakage()
    swap = measure_swap()
    config = measure_config_only()
    return {
        "leakage": leakage,
        "swap": swap["swap"],
        "citation": swap["citation"],
        "config": config,
    }
