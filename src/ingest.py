"""Разбор inbox в чанки.

Битый файл пропускается и не обнуляет остальные. VERSION входит в checksum:
смена правил разбора без новой версии оставляет в индексе старый текст.
"""
import hashlib
import json
import os
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from settings import runtime

SUFFIXES = {".txt", ".md", ".doc", ".docx"}
VERSION = 3
TOKENS = 250
OVERLAP = 40
INTRO = 120


def _bind_runtime():
    global TOKENS, OVERLAP, INTRO
    data = runtime()
    TOKENS = data.get("tokens", TOKENS)
    OVERLAP = data.get("overlap", OVERLAP)
    INTRO = data.get("intro", INTRO)


def _tokens():
    return runtime().get("tokens", TOKENS)


def _overlap():
    return runtime().get("overlap", OVERLAP)


def _intro():
    return runtime().get("intro", INTRO)


_bind_runtime()

MODEL = Path(os.environ.get("EMBED_PATH", Path(__file__).resolve().parents[1] / "data" / "models" / "multilingual-e5-small"))
_HEADING = re.compile(r"^(heading|заголовок)\s*(\d)", re.IGNORECASE)
_NUMBERED_HEAD = re.compile(r"^(\d+(?:\.\d+)*)\s+(\S.*)$")
_TOC = re.compile(r"^(toc|оглавление)\s*\d", re.IGNORECASE)
_tokenizer = None


def _load_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        import store
        with store._import_lock:
            if _tokenizer is None:
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
                os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
                from transformers import AutoTokenizer
                _tokenizer = AutoTokenizer.from_pretrained(str(MODEL), local_files_only=True)
    return _tokenizer


def count_tokens(text):
    return len(_load_tokenizer()(text, add_special_tokens=False)["input_ids"])


@lru_cache(maxsize=200000)
def _word_tokens(word):
    return max(1, count_tokens(word))


def _plain_text(text):
    # A Word line break is a break inside the paragraph, not a new paragraph.
    # Collapsing it to a space stores "доку- мента", so the word never matches.
    # Join only when the next line continues a letter, as across paragraphs.
    # "6-" + "10" and "ISO-" + "9001" keep the hyphen instead of becoming 610.
    lines = []
    for raw in (text or "").splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        if (
            lines
            and len(lines[-1]) >= 2
            and lines[-1].endswith("-")
            and lines[-1][-2].isalpha()
            and line[:1].islower()
        ):
            lines[-1] = lines[-1][:-1] + line
            continue
        lines.append(line)
    return " ".join(lines)


def _text(cell, depth=0):
    # cell.text is the paragraphs only. A table nested in the cell is the value
    # Word shows there; leaving it out stores the row with an empty cell.
    if cell is None or depth >= 4 or not getattr(cell, "tables", None):
        return "" if cell is None else _plain_text(cell.text)
    from docx.table import Table

    parts = []
    for block in cell.iter_inner_content():
        if isinstance(block, Table):
            parts.extend(_nested_lines(block, depth + 1))
            continue
        text = _plain_text(block.text)
        if text:
            parts.append(text)
    return " ".join(parts)


def _nested_lines(table, depth):
    nested = _table_block(table, "", depth)
    if not nested:
        return []
    if nested["kind"] == "p":
        return [nested["text"]] if nested.get("text") else []
    keyvalue = nested.get("width") == 2 and len(nested["labels"]) == 2
    lines = []
    for pairs in nested["rows"]:
        line = _row_line(pairs, keyvalue)
        if line:
            lines.append(line)
    return lines


def _same_cell(left, right):
    return left is not None and right is not None and left._tc is right._tc


def _aligned_row(row):
    # A row that starts or ends in a later column simply omits those cells.
    # Reading only the cells that are present slides each value under the
    # previous header, so the minimum is stored as the name of the row.
    cells = list(row.cells)
    return [None] * row.grid_cols_before + cells + [None] * row.grid_cols_after


def _style_names(style):
    names = []
    while style is not None and len(names) < 10:
        names.append(style.name or "")
        style = style.base_style
    return names


def _numbered_heading(text):
    match = _NUMBERED_HEAD.match(text or "")
    if not match:
        return 0
    title = match.group(2).strip()
    if len(title) > 80 or title.count(" ") > 7 or title.endswith(".") or ". " in title:
        return 0
    if not title[:1].isupper():
        return 0
    return min(6, match.group(1).count(".") + 1)


def _outline(element):
    ppr = getattr(element, "pPr", None)
    level = getattr(ppr, "outlineLvl", None) if ppr is not None else None
    if level is not None and level.val is not None and int(level.val) < 9:
        return int(level.val) + 1
    return 0


def _heading_level(paragraph):
    style = paragraph.style
    for name in _style_names(style):
        match = _HEADING.match(name)
        if match:
            return int(match.group(2))
    level = _outline(paragraph._p)
    while not level and style is not None:
        level = _outline(style.element)
        style = style.base_style
    return level


def _subheader(top, low):
    spans = any(_same_cell(left, right) for left, right in zip(top, top[1:]))
    tied = any(_same_cell(upper, lower) for upper, lower in zip(top, low))
    return spans and tied


def _table_block(table, caption, depth=0):
    grid = [_aligned_row(row) for row in table.rows]
    width = max((len(row) for row in grid), default=0)
    grid = [row + [None] * (width - len(row)) for row in grid]
    grid = [row for row in grid if any(_text(cell, depth) for cell in row)]
    if len(grid) < 2:
        text = " ".join(_text(cell, depth) for row in grid for cell in row)
        return {"kind": "p", "text": text} if text else None
    labels = [_text(cell, depth) for cell in grid[0]]
    start = 1
    if len(grid) > 2 and _subheader(grid[0], grid[1]):
        labels = [
            top if _same_cell(upper, lower) or not _text(lower, depth) else f"{top} / {_text(lower, depth)}"
            for top, upper, lower in zip(labels, grid[0], grid[1])
        ]
        start = 2
    rows = []
    for row in grid[start:]:
        pairs = []
        last = None
        for label, cell in zip(labels, row):
            if cell is None:
                # The cell is absent, but the column is not. Dropping it here
                # slides the next value into this column: a two-column row stores
                # the measurement as the name, and the column summary counts it
                # under the previous header.
                if not pairs or pairs[-1][0] != label:
                    pairs.append((label, ""))
                last = None
                continue
            if cell._tc is last:
                # This column is the rest of a merged cell. Skipping it slides
                # the next value left, and the column summary counts that value
                # under this header.
                if not pairs or pairs[-1][0] != label:
                    pairs.append((label, ""))
                continue
            last = cell._tc
            value = _text(cell, depth)
            if pairs and pairs[-1][0] == label:
                if value:
                    pairs[-1] = (label, f"{pairs[-1][1]}; {value}" if pairs[-1][1] else value)
                continue
            pairs.append((label, value))
        if any(value for _, value in pairs):
            rows.append(pairs)
    names = []
    for label in labels:
        if not names or names[-1] != label:
            names.append(label)
    return {"kind": "table", "caption": caption, "labels": names, "width": len(labels), "rows": rows}


_WML = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# Revisions and content controls wrap the text Word shows. python-docx reads only
# a direct paragraph or a direct run, so an inserted value or a form field is
# skipped and the index keeps the old text or an empty cell.
_WORD_PARENTS = {
    "body", "p", "hyperlink", "sdtContent", "tc", "tbl", "tr",
    "smartTag", "ins", "moveTo", "txbxContent", "customXml",
}


def _word_name(tag):
    return tag.rsplit("}", 1)[-1]


def _unwrap_word_wrappers(root):
    for tag in ("del", "moveFrom"):
        for node in list(root.iter(_WML + tag)):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)
    for _ in range(32):
        changed = 0
        for tag in ("ins", "moveTo", "sdt", "smartTag"):
            for node in list(root.iter(_WML + tag)):
                parent = node.getparent()
                if parent is None or _word_name(parent.tag) not in _WORD_PARENTS:
                    continue
                if tag == "sdt":
                    content = node.find(_WML + "sdtContent")
                    children = list(content) if content is not None else []
                else:
                    children = list(node)
                index = parent.index(node)
                parent.remove(node)
                for offset, child in enumerate(children):
                    parent.insert(index + offset, child)
                changed += 1
        if not changed:
            return


def _docx_blocks(path):
    from docx import Document
    from docx.table import Table
    document = Document(str(path))
    _unwrap_word_wrappers(document.element)
    blocks = []
    previous = ""
    for item in document.iter_inner_content():
        if isinstance(item, Table):
            block = _table_block(item, previous)
            if block:
                blocks.append(block)
            previous = ""
            continue
        text = _plain_text(item.text)
        if not text:
            continue
        if any(_TOC.match(name) for name in _style_names(item.style)):
            continue
        level = _heading_level(item) or _numbered_heading(text)
        # A line break in "доку-мента" is a soft hyphen: drop it and join.
        # A hard hyphen before a number or after a digit must stay, otherwise
        # "6-" + "10" and "ISO-" + "9001" are stored as 610 and ISO9001.
        previous_block = blocks[-1] if blocks else None
        previous_text = previous_block.get("text", "") if isinstance(previous_block, dict) else ""
        if (
            not level
            and previous_block
            and previous_block.get("kind") == "p"
            and len(previous_text) >= 2
            and previous_text.endswith("-")
            and previous_text[-2].isalpha()
            and text[:1].islower()
        ):
            blocks[-1]["text"] = previous_text[:-1] + text
            previous = blocks[-1]["text"]
            continue
        blocks.append({"kind": "heading", "level": level, "text": text} if level else {"kind": "p", "text": text})
        previous = text
    return blocks


def _markdown_blocks(text):
    blocks = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            blocks.append({"kind": "heading", "level": len(match.group(1)), "text": match.group(2).strip()})
        else:
            blocks.append({"kind": "p", "text": line})
    return blocks


def _text_blocks(text):
    return [{"kind": "p", "text": " ".join(line.split())} for line in text.splitlines() if line.strip()]


def _doc_blocks(path):
    with tempfile.TemporaryDirectory() as folder:
        subprocess.run(
            ["soffice", "--headless", "--convert-to", "docx", "--outdir", folder, str(path)],
            check=True,
            capture_output=True,
        )
        return _docx_blocks(Path(folder) / (Path(path).stem + ".docx"))


def _blocks(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _docx_blocks(path)
    if suffix == ".doc":
        return _doc_blocks(path)
    text = path.read_text(encoding="utf-8")
    return _markdown_blocks(text) if suffix == ".md" else _text_blocks(text)


def _row_line(pairs, keyvalue):
    if keyvalue:
        key, value = pairs[0][1], (pairs[1][1] if len(pairs) > 1 else "")
        if not key:
            return f"{pairs[1][0]}: {value}" if len(pairs) > 1 else ""
        return f"{key}: {value or '—'}"
    return "; ".join(f"{label}: {value}" if label else value for label, value in pairs if value)


def _row_parts(pairs, keyvalue, room):
    line = _row_line(pairs, keyvalue)
    if keyvalue or len(pairs) < 3 or count_tokens(line) <= room:
        return [line] if line else []
    lead = 1
    while lead < min(3, len(pairs) - 1) and count_tokens(_row_line(pairs[:lead + 1], False)) * 3 <= room:
        lead += 1
    parts, current = [], []
    for pair in pairs[lead:]:
        if current and count_tokens(_row_line(pairs[:lead] + current + [pair], False)) > room:
            parts.append(_row_line(pairs[:lead] + current, False))
            current = []
        current.append(pair)
    if current:
        parts.append(_row_line(pairs[:lead] + current, False))
    return [part for part in parts if part]


def _cut(words, budget):
    pieces, start = [], 0
    while start < len(words):
        size, end = 0, start
        while end < len(words) and size + _word_tokens(words[end]) <= budget:
            size += _word_tokens(words[end])
            end += 1
        end = max(end, start + 1)
        if end < len(words) and end - start > 8:
            floor = start + max(4, (end - start) // 2)
            for index in range(end - 1, floor - 1, -1):
                token = words[index].rstrip("\"'«»“”")
                if token.endswith((".", ";", "?", "!")):
                    end = index + 1
                    break
        pieces.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        back, size = end, 0
        while back > start + 1 and size + _word_tokens(words[back - 1]) <= _overlap():
            back -= 1
            size += _word_tokens(words[back])
        start = back
    return pieces


def _tail(text, limit):
    words = text.split()
    taken, size = [], 0
    while words and size + _word_tokens(words[-1]) <= limit:
        size += _word_tokens(words[-1])
        taken.insert(0, words.pop())
    return " ".join(taken)


def _pack(lines, budget, overlap=True):
    pieces, current, size = [], [], 0
    for line in lines:
        cost = count_tokens(line)
        if cost > budget:
            if current:
                pieces.append(current)
                current, size = [], 0
            pieces.extend([part] for part in _cut(line.split(), budget))
            continue
        if current and size + cost > budget:
            pieces.append(current)
            tail = _tail("\n".join(current), _overlap()) if overlap else ""
            current, size = ([tail], count_tokens(tail)) if tail and count_tokens(tail) + cost <= budget else ([], 0)
        current.append(line)
        size += cost
    if current:
        pieces.append(current)
    return ["\n".join(piece) for piece in pieces]


def _distinct_column(block):
    for position in range(len(block["labels"])):
        values = []
        for pairs in block["rows"]:
            if position < len(pairs) and pairs[position][1]:
                values.append(pairs[position][1])
        unique = list(dict.fromkeys(values))
        if values and len(unique) * 2 >= len(values) and not all(re.fullmatch(r"[\d.,\s-]+", value) for value in unique):
            return block["labels"][position], unique
    return "", []


def _table_pieces(block, section):
    head = [line for line in (section, block["caption"]) if line]
    if len(head) == 2 and section.split(" > ")[-1] == block["caption"]:
        head = head[:1]
    keyvalue = block.get("width") == 2 and len(block["labels"]) == 2
    if keyvalue and any(block["labels"]):
        head.append(" | ".join(block["labels"]))
    head_text = "\n".join(head)
    room = max(60, _tokens() - (count_tokens(head_text) if head_text else 0))
    lines = []
    for pairs in block["rows"]:
        lines += _row_parts(pairs, keyvalue, room)
    title = block["caption"] or section.split(" > ")[-1]
    groups = [part for line in lines for part in _cut(line.split(), room)]
    pieces = [
        ("table", f"{head_text}\n{group}" if head_text else group, head_text, f"{title}\n{group}" if title else group)
        for group in groups
    ]
    if len(block["rows"]) > 1 and sum(count_tokens(line) for line in lines) > _tokens():
        label, values = _distinct_column(block)
        if values:
            # The count is the full column, so the list must stay complete. Cutting it to the
            # chunk budget drops later values while the line still claims to be exhaustive.
            overview = f"Разных значений в столбце «{label}»: {len(values)}. Список: {', '.join(values)}."
            pieces.insert(0, ("overview", f"{head_text}\n{overview}" if head_text else overview, head_text, f"{title}\n{overview}" if title else overview))
    return pieces


def chunks_from_blocks(blocks, document_name=""):
    """Собрать чанки из уже разобранных блоков одного документа."""
    # Upsert skips a document when this hash matches. Overlap, chunk size and the
    # intro limit change the stored text and kind without changing the source, and
    # often without changing how many chunks there are.
    limits = json.dumps(
        {"tokens": _tokens(), "overlap": _overlap(), "intro": _intro()},
        sort_keys=True,
    )
    digest = hashlib.sha256(
        (json.dumps(blocks, ensure_ascii=False) + str(VERSION) + limits).encode()
    ).hexdigest()
    pieces, path, buffer = [], [], []
    tables = 0

    def section():
        return " > ".join(text for _, text in path)

    def flush():
        if not buffer:
            return
        head = section()
        room = max(60, _tokens() - (count_tokens(head) if head else 0))
        for body in _pack(buffer, room):
            text = f"{head}\n{body}" if head else body
            pieces.append((head, "text", text, "", "", text))
        buffer.clear()

    for block in blocks:
        if block["kind"] == "heading":
            flush()
            while path and path[-1][0] >= block["level"]:
                path.pop()
            path.append((block["level"], block["text"]))
        elif block["kind"] == "p":
            buffer.append(block["text"])
        else:
            before = len(pieces)
            flush()
            tables += 1
            group = f"t{tables}"
            last = pieces[-1] if len(pieces) > before else None
            if last and last[1] == "text" and count_tokens(last[2]) <= _intro():
                pieces[-1] = (last[0], "intro", last[2], group, "", last[5])
            for kind, text, head, embed in _table_pieces(block, section()):
                pieces.append((section(), kind, text, group, head, embed))
    flush()
    return [
        {
            "text": text,
            "embed": embed,
            "document_name": document_name,
            "chunk_index": index,
            "checksum": digest,
            "section": head,
            "kind": kind,
            "group": group,
            "head": prefix,
            "version": VERSION,
        }
        for index, (head, kind, text, group, prefix, embed) in enumerate(pieces)
    ]


def split_chunks(text, document_name=""):
    """Нарезать плоский текст так же, как файл без таблиц."""
    return chunks_from_blocks(_text_blocks(text), document_name)


def load_text(path):
    """Вернуть видимый текст файла. Для docx это уже склеенные блоки."""
    lines = []
    for block in _blocks(path):
        if block["kind"] == "table":
            lines.append(block["caption"])
            lines.extend(_row_line(pairs, block.get("width") == 2 and len(block["labels"]) == 2) for pairs in block["rows"])
        else:
            lines.append(block["text"])
    return "\n".join(line for line in lines if line)


def ingest_dir(directory):
    """Прочитать каталог и вернуть чанки. Битый файл не отменяет остальные."""
    # Upload and startup both read the whole inbox. One file that cannot be
    # parsed used to abort that pass, so nothing was indexed, and the bad file
    # never appeared in the document list where it could be deleted.
    chunks = []
    for path in sorted(Path(directory).iterdir()):
        if path.suffix.lower() not in SUFFIXES or not path.is_file():
            continue
        try:
            chunks += chunks_from_blocks(_blocks(path), path.name)
        except ImportError:
            raise
        except Exception:
            continue
    return chunks
