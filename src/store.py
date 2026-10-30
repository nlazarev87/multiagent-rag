import math
import os
import re
import threading
from collections import Counter
from pathlib import Path

from settings import runtime, where as route_where

CHROMA = Path(os.environ.get("CHROMA_PATH", "data/chroma"))
MODEL = Path(os.environ.get("EMBED_PATH", "data/models/multilingual-e5-small"))
CANDIDATES = 30
CONTEXT = 260
RRF = 5
K1 = 1.5
B = 0.75
calls = 0


def _candidates():
    return runtime().get("candidates", CANDIDATES)


def _context():
    return runtime().get("context", CONTEXT)


def _rrf():
    return runtime().get("rrf", RRF)


def _meta_ok(meta):
    extra = route_where()
    if not extra:
        return True
    return all(meta.get(key) == value for key, value in extra.items())


def _chroma_where(allowed):
    clauses = [{key: value} for key, value in route_where().items()]
    if allowed:
        clauses.append({"document_name": {"$in": list(allowed)}})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


_model = None
_client = None
_collection = None
_index = None
_stemmers = {}
_import_lock = threading.Lock()
# Sync routes share a thread pool with ingest. Search keeps the index object
# it opened. A delete or an upload clears the global when it finishes, and
# that must not crash the request that is already reading it.
_index_lock = threading.RLock()
_WORD = re.compile(r"[0-9a-zа-я]+(?:[._/-][0-9a-zа-я]+)*")
_NAME = re.compile(r"[0-9A-Za-zА-Яа-яЁё]+(?:[._/-][0-9A-Za-zА-Яа-яЁё]+)*")
_STOP = set(
    "а без более бы был была были было быть в вам вас весь во вот все всего всех вы где да даже для до его ее её "
    "если есть еще ещё же за здесь и из или им их к как какая какие каким какими каких каков какова каково какое "
    "какой какую кем когда кого кое ком которая которого которое которой котором которую которые который кто ли "
    "либо мне может мы на над нам нас не него нее неё нет ни них но ну о об однако он она они оно от по под при "
    "про с со так также такая такие такое такой там те тем то того тоже той только том ту тут ты у уж уже чего чей "
    "чем через что чтобы чье чья эта эти это этого этой этом этот эту я".split()
)


def _embed(texts):
    global _model
    if _model is None:
        with _import_lock:
            if _model is None:
                from sentence_transformers import SentenceTransformer
                _model = SentenceTransformer(str(MODEL))
    return _model.encode(texts, normalize_embeddings=True, batch_size=16).tolist()


def collection():
    global _collection, _client
    if _collection is None:
        with _import_lock:
            if _collection is None:
                import chromadb
                _client = chromadb.PersistentClient(path=str(CHROMA))
                _collection = _client.get_or_create_collection("fragments", metadata={"hnsw:space": "cosine"})
    return _collection


def reset():
    global _collection, _index, _client, calls
    with _index_lock:
        _collection = None
        system = getattr(_client, "_system", None) if _client is not None else None
        if system is not None and hasattr(system, "stop"):
            try:
                system.stop()
            except Exception:
                pass
        _client = None
        _index = None
        calls = 0
        import gc
        gc.collect()


def _rows(col, **where):
    ids, texts, metas, offset = [], [], [], 0
    while True:
        batch = col.get(include=["documents", "metadatas"], limit=500, offset=offset, **where)
        ids += batch["ids"]
        texts += batch["documents"] or []
        metas += batch["metadatas"] or []
        if len(batch["ids"]) < 500:
            return ids, texts, metas
        offset += 500


def upsert_chunks(chunks):
    global _index
    if not chunks:
        return
    with _index_lock:
        col = collection()
        groups = {}
        for chunk in chunks:
            groups.setdefault(chunk["document_name"], []).append(chunk)
        for name, items in groups.items():
            found = col.get(where={"document_name": name}, include=["metadatas"])
            metas = found["metadatas"] or []
            if len(metas) == len(items) and all(meta.get("checksum") == items[0]["checksum"] for meta in metas):
                continue
            if found["ids"]:
                col.delete(ids=found["ids"])
            for start in range(0, len(items), 64):
                batch = items[start:start + 64]
                col.add(
                    ids=[f"{chunk['checksum']}:{chunk['chunk_index']}" for chunk in batch],
                    documents=[chunk["text"] for chunk in batch],
                    embeddings=_embed(["passage: " + chunk.get("embed", chunk["text"]) for chunk in batch]),
                    metadatas=[{
                        "document_name": chunk["document_name"],
                        "chunk_index": chunk["chunk_index"],
                        "checksum": chunk["checksum"],
                        "section": chunk.get("section", ""),
                        "kind": chunk.get("kind", "text"),
                        "group": chunk.get("group", ""),
                        "head": chunk.get("head", ""),
                        "version": chunk.get("version", 0),
                        **({"collection": chunk["collection"]} if chunk.get("collection") else {}),
                    } for chunk in batch],
                )
        _index = None


def delete_document(document_name):
    global _index
    with _index_lock:
        col = collection()
        found = col.get(where={"document_name": document_name})
        if found["ids"]:
            col.delete(ids=found["ids"])
        _index = None


def list_documents():
    with _index_lock:
        names = []
        for meta in _rows(collection())[2]:
            if meta["document_name"] not in names:
                names.append(meta["document_name"])
        return names


def chunks_for_document(name):
    with _index_lock:
        _, texts, metas = _rows(collection(), where={"document_name": name})
        rows = [
            {
                "text": text,
                "section": meta.get("section", ""),
                "chunk_index": meta.get("chunk_index", 0),
            }
            for text, meta in zip(texts, metas)
        ]
        rows.sort(key=lambda row: row["chunk_index"])
        return rows


def _stem(word):
    language = "english" if word.isascii() else "russian"
    if language not in _stemmers:
        import snowballstemmer
        _stemmers[language] = snowballstemmer.stemmer(language)
    return _stemmers[language].stemWord(word)


def _words(text):
    return _WORD.findall(text.lower().replace("ё", "е"))


def _terms(text):
    terms = []
    for word in _words(text):
        if any(ch.isdigit() for ch in word):
            terms.append(word)
        for piece in re.split(r"[._/-]", word):
            if len(piece) < 2 or piece in _STOP:
                continue
            if any(ch.isdigit() for ch in piece):
                if len(piece) >= 3 and piece != word:
                    terms.append(piece)
                continue
            terms.append("s:" + _stem(piece))
            if len(piece) >= 5:
                terms.append("p:" + piece[:5])
    return terms


def _build(col):
    ids, texts, metas = _rows(col)
    counts = [Counter(_terms(text)) for text in texts]
    lengths = [sum(count.values()) for count in counts]
    frequency, size, chunks, vocabulary, groups = {}, Counter(), Counter(), {}, {}
    for number, (text, meta, count, length) in enumerate(zip(texts, metas, counts, lengths)):
        name = meta["document_name"]
        frequency.setdefault(name, Counter()).update(count.keys())
        size[name] += length
        chunks[name] += 1
        vocabulary.setdefault(name, set()).update(_words(text))
        if meta.get("group"):
            groups.setdefault((name, meta["group"]), []).append(number)
    for members in groups.values():
        members.sort(key=lambda number: metas[number]["chunk_index"])
    return {
        "groups": groups,
        "ids": ids,
        "texts": texts,
        "metas": metas,
        "counts": counts,
        "lengths": lengths,
        "frequency": frequency,
        "size": size,
        "chunks": chunks,
        "vocabulary": vocabulary,
        "position": {key: number for number, key in enumerate(ids)},
    }


def _open_index():
    global _index
    with _index_lock:
        col = collection()
        total = col.count()
        if total == 0:
            _index = None
            return col, 0, None
        if _index is None or len(_index["ids"]) != total:
            _index = _build(col)
        return col, total, _index


def known(term):
    _col, _total, index = _open_index()
    if index is None:
        return False
    term = term.lower().replace("ё", "е")
    return any(term in words for words in index["vocabulary"].values())


def _names(query):
    names = []
    for token in _NAME.findall(query):
        upper = sum(ch.isupper() for ch in token)
        coded = any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token)
        numbered = bool(re.search(r"\d+[._-]\d+", token))
        if upper >= 2 or coded or numbered:
            names.append(token.lower().replace("ё", "е"))
    return names


def _doc_markers(doc):
    low = doc.lower().replace("ё", "е")
    markers = set(_WORD.findall(low))
    markers.update(index_part for index_part in re.findall(r"\d+(?:[._-]\d+)+", low))
    return markers


def _marker_hit(name, markers, words):
    if name in words or name in markers:
        return True
    return any(
        marker == name
        or marker.startswith(name + ".")
        or marker.startswith(name + "-")
        or marker.startswith(name + "_")
        for marker in markers
    )


def scope(index, query):
    documents = sorted(index["vocabulary"])
    names = _names(query)
    if not names or len(documents) < 2:
        return None
    marks = {doc: _doc_markers(doc) for doc in documents}
    known = [
        name
        for name in names
        if any(_marker_hit(name, marks[doc], index["vocabulary"][doc]) for doc in documents)
    ]
    if not known:
        return None
    hits = {
        doc: sum(_marker_hit(name, marks[doc], index["vocabulary"][doc]) for name in known)
        for doc in documents
    }
    best = max(hits.values())
    chosen = [doc for doc in documents if hits[doc] == best]
    return chosen if len(chosen) < len(documents) else None


def _lexical(index, query, allowed):
    terms = set(_terms(query))
    documents = allowed or list(index["frequency"])
    total = sum(index["chunks"][doc] for doc in documents)
    average = max(1.0, sum(index["size"][doc] for doc in documents) / max(1, total))
    frequency = {term: sum(index["frequency"][doc][term] for doc in documents) for term in terms}
    scored = []
    for number, count in enumerate(index["counts"]):
        if allowed and index["metas"][number]["document_name"] not in allowed:
            continue
        if not _meta_ok(index["metas"][number]):
            continue
        score = 0.0
        for term in terms:
            seen = count.get(term)
            if not seen:
                continue
            weight = math.log(1 + (total - frequency[term] + 0.5) / (frequency[term] + 0.5))
            norm = K1 * (1 - B + B * index["lengths"][number] / average)
            score += weight * seen * (K1 + 1) / (seen + norm)
        if score > 0:
            scored.append((score, number))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [index["ids"][number] for _, number in scored[:_candidates()]]


def _dense(col, query, allowed, total):
    embedding = _embed(["query: " + query])
    with _index_lock:
        # The collection may have shrunk while the query vector was built.
        # Asking for more neighbours than Chroma still holds raises.
        current = col.count()
        if current == 0:
            return []
        found = col.query(
            query_embeddings=embedding,
            n_results=min(_candidates(), current, total or current),
            where=_chroma_where(allowed),
            include=["distances"],
        )
    return found["ids"][0] if found["ids"] else []


def _fuse(*rankings):
    scores = Counter()
    for ranking in rankings:
        for rank, key in enumerate(ranking):
            scores[key] += 1 / (_rrf() + rank + 1)
    return [key for key, _ in scores.most_common()]


def _focus(query, allowed):
    if not allowed:
        return query
    names = set(_names(query))
    kept = []
    for token in query.split():
        parts = [part.lower().replace("ё", "е") for part in _NAME.findall(token)]
        if parts and all(part in names for part in parts):
            continue
        kept.append(token)
    words = [token for token in kept if len(token.strip("?,.!:;«»()")) > 3]
    return " ".join(kept) if len(words) >= 2 else query


def _body(index, number):
    text = index["texts"][number]
    head = index["metas"][number].get("head", "")
    return text[len(head) + 1:] if head and text.startswith(head) else text


def _render(index, numbers):
    from ingest import count_tokens
    first = index["metas"][numbers[0]]
    if not first.get("group"):
        return "\n".join(index["texts"][number] for number in numbers)
    members = index["groups"][(first["document_name"], first["group"])]
    head = next((index["metas"][number].get("head") for number in members if index["metas"][number].get("head")), "")
    always = {number for number in members if index["metas"][number].get("kind") in ("overview", "intro")}
    chosen = set(numbers) | always
    size = (count_tokens(head) if head else 0) + sum(count_tokens(_body(index, number)) for number in chosen)
    places = [members.index(number) for number in numbers if number in members]
    for distance in range(1, len(members)):
        for place in places:
            for neighbour in (place - distance, place + distance):
                if 0 <= neighbour < len(members) and members[neighbour] not in chosen:
                    cost = count_tokens(_body(index, members[neighbour]))
                    if size + cost <= _context():
                        chosen.add(members[neighbour])
                        size += cost
    kinds = {number: index["metas"][number].get("kind") for number in members}
    ordered = []
    for kind in ("table", "intro", "overview"):
        ordered += [number for number in members if number in chosen and (kinds[number] or "table") == kind]
    lines = []
    for text in [head] + [_body(index, number) for number in ordered]:
        for line in text.split("\n"):
            if line and line not in lines:
                lines.append(line)
    return "\n".join(lines)


def _contexts(index, ranked, limit):
    slots, order = {}, []
    for place, key in enumerate(ranked):
        if place >= limit * 3 and len(order) >= limit:
            break
        number = index["position"][key]
        meta = index["metas"][number]
        slot = (meta["document_name"], meta["group"]) if meta.get("group") else key
        if slot in slots:
            if place < limit * 3:
                slots[slot].append(number)
        elif len(order) < limit:
            slots[slot] = [number]
            order.append(slot)
    found = []
    for slot in order:
        numbers = slots[slot]
        meta = index["metas"][numbers[0]]
        kind = meta.get("kind", "text")
        if meta.get("group"):
            members = index["groups"].get((meta["document_name"], meta["group"]), [])
            if any(index["metas"][number].get("kind") == "overview" for number in members):
                kind = "overview"
        found.append({
            "id": index["ids"][numbers[0]],
            "text": _render(index, numbers),
            "document_name": meta["document_name"],
            "chunk_index": meta["chunk_index"],
            "section": meta.get("section", ""),
            "kind": kind,
        })
    return found


def search_chunks(clear_query, limit=4, document_names=None):
    global calls
    calls += 1
    col, total, index = _open_index()
    if index is None:
        return []
    allowed = scope(index, clear_query)
    if document_names:
        present = [name for name in document_names if name in index["vocabulary"]]
        if present:
            allowed = present
    dense = _dense(col, _focus(clear_query, allowed), allowed, total)
    ranked = [
        key
        for key in _fuse(_lexical(index, clear_query, allowed), dense)
        if key in index["position"] and _meta_ok(index["metas"][index["position"][key]])
    ]
    return _contexts(index, ranked, limit)
