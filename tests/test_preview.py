import os
import shutil
import subprocess
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "src" / "web" / "index.html"
NODE = shutil.which("node") or "/exec-daemon/node"

SCRIPT = r"""
const fs = require("fs");
const html = fs.readFileSync(process.env.TREE_HTML, "utf8");
function extract(name) {
  const token = "function " + name + "(";
  let start = html.indexOf(token);
  if (start < 0) throw new Error("missing " + name);
  const asyncAt = start - "async ".length;
  if (html.slice(asyncAt, start) === "async ") start = asyncAt;
  const brace = html.indexOf("{", start);
  let depth = 0;
  for (let i = brace; i < html.length; i++) {
    if (html[i] === "{") depth += 1;
    else if (html[i] === "}") {
      depth -= 1;
      if (depth === 0) return html.slice(start, i + 1);
    }
  }
  throw new Error("unclosed " + name);
}

function classListFor(node) {
  const read = () => new Set(node.className.split(/\s+/).filter(Boolean));
  const write = (set) => { node.className = [...set].join(" "); };
  return {
    add(...names) { const set = read(); names.forEach((name) => set.add(name)); write(set); },
    remove(...names) { const set = read(); names.forEach((name) => set.delete(name)); write(set); },
    contains(name) { return read().has(name); },
    toggle(name, force) {
      const set = read();
      const has = set.has(name);
      const next = force === undefined ? !has : Boolean(force);
      if (next) set.add(name); else set.delete(name);
      write(set);
      return next;
    },
  };
}

function matches(node, selector) {
  if (selector.startsWith(".")) return node.className.split(/\s+/).includes(selector.slice(1));
  const attr = selector.match(/^\[([^=]+)="(.*)"\]$/);
  return Boolean(attr) && node.attrs[attr[1]] === attr[2];
}

function query(node, selector) {
  for (const child of node.children) {
    if (matches(child, selector)) return child;
    const found = query(child, selector);
    if (found) return found;
  }
  return null;
}

function textOf(node) {
  return [node.textContent || "", ...node.children.map(textOf)].join(" ");
}

const scrolled = [];
function createElement(tag) {
  const node = {
    tag,
    className: "",
    textContent: "",
    attrs: {},
    children: [],
    parentNode: null,
    setAttribute(key, value) { this.attrs[key] = String(value); },
    append(...nodes) {
      for (const child of nodes) {
        child.parentNode = this;
        this.children.push(child);
      }
    },
    replaceChildren(...nodes) {
      this.children = [];
      if (nodes.length) this.append(...nodes);
    },
    querySelector(selector) { return query(this, selector); },
    scrollIntoView() { scrolled.push(this); },
    addEventListener() {},
  };
  node.classList = classListFor(node);
  return node;
}

global.document = { createElement };
let openTabs = [];
let activeTab = "";
let tabChunks = {};
let preview = createElement("div");
preview.parentNode = { scrollTop: 0 };
let tabsEl = createElement("div");
let tree = { id: "root", name: "", children: [] };
let treePending = false;
let treeWriting = false;
let treeStamp = 0;
let painted = 0;
function paintTree() { painted += 1; }

(async () => {
eval(extract("tokens"));
eval(extract("contentWords"));
eval(extract("coverage"));
eval(extract("blocks"));
eval(extract("element"));
eval(extract("idlePreview"));
eval(extract("paintTabs"));
eval(extract("closeTab"));
eval(extract("paintChunks"));
eval(extract("showPreview"));
eval(extract("persistTree"));

function defer() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}
const fetches = [];
global.fetch = (url) => {
  const job = defer();
  fetches.push({ url: String(url), job });
  return job.promise;
};
function ok(chunks) {
  return { ok: true, json: async () => ({ chunks }) };
}

const slow = showPreview("slow.docx");
await Promise.resolve();
if (fetches.length !== 1 || !fetches[0].url.endsWith("/documents/slow.docx/preview")) {
  throw new Error("slow preview did not request its document");
}
tabChunks["fast.docx"] = [{ text: "Быстрый документ давления", chunk_index: 0 }];
await showPreview("fast.docx");
if (!textOf(preview).includes("Быстрый документ")) throw new Error("open tab was not painted");
fetches[0].job.resolve(ok([{ text: "Медленный документ температуры", chunk_index: 0 }]));
await slow;
if (textOf(preview).includes("Медленный")) throw new Error("stale preview replaced the open tab");
if (!textOf(preview).includes("Быстрый документ")) throw new Error("open tab was cleared");
if (tabChunks["slow.docx"][0].text !== "Медленный документ температуры") {
  throw new Error("late preview was not kept for a later open");
}

const failed = showPreview("error.docx");
await showPreview("fast.docx");
fetches.at(-1).job.resolve({ ok: false, json: async () => ({ detail: "Документ не найден" }) });
await failed;
if (textOf(preview).includes("Документ не найден")) throw new Error("failed preview replaced the open tab");
const dropped = showPreview("down.docx");
await showPreview("fast.docx");
fetches.at(-1).job.reject(new Error("network"));
await dropped;
if (textOf(preview).includes("Сервер не ответил")) throw new Error("failed preview replaced the open tab");

const tied = [
  { text: "Рабочее давление указано отдельно.", chunk_index: 1 },
  { text: "Рабочее давление указано в паспорте.", chunk_index: 7 },
];
paintChunks(tied, { chunkIndex: 7, answer: "Рабочее давление указано" });
const hit = preview.querySelector(".hit");
if (!hit || hit.textContent !== "Рабочее давление указано в паспорте.") {
  throw new Error("equal coverage did not stay on the cited chunk");
}
paintChunks(tied, { chunkIndex: 1, answer: "Рабочее давление указано" });
if (preview.querySelector(".hit").textContent !== "Рабочее давление указано отдельно.") {
  throw new Error("equal coverage did not stay on the earlier cited chunk");
}
paintChunks([
  { text: "Рабочее давление указано отдельно.", chunk_index: 1 },
  { text: "Только давление.", chunk_index: 7 },
], { chunkIndex: 7, answer: "Рабочее давление указано" });
if (preview.querySelector(".hit").textContent !== "Рабочее давление указано отдельно.") {
  throw new Error("a weaker cited chunk beat a closer paragraph");
}
scrolled.length = 0;
paintChunks([
  { text: "код 12", chunk_index: 4, section: "Паспорт" },
  { text: "другая строка", chunk_index: 5, section: "Иное" },
], { chunkIndex: "", section: "Паспорт", answer: "код 12" });
if (preview.querySelector(".hit")) throw new Error("short words highlighted a paragraph");
if (scrolled.at(-1).attrs["data-index"] !== "4") throw new Error("preview did not scroll to the cited section");

openTabs = ["a.docx", "b.docx"];
activeTab = "b.docx";
tabChunks = {
  "a.docx": [{ text: "Текст первого документа", chunk_index: 0 }],
  "b.docx": [{ text: "Текст второго документа", chunk_index: 1 }],
};
closeTab("b.docx");
if (activeTab !== "a.docx" || tabChunks["b.docx"]) throw new Error("closed tab stayed active");
if (!textOf(preview).includes("Текст первого документа")) throw new Error("remaining tab was not shown");
if (preview.querySelector(".hit")) throw new Error("closed answer stayed highlighted");
closeTab("a.docx");
if (activeTab || !preview.classList.contains("idle")) throw new Error("last tab did not return to the idle preview");
if (!textOf(preview).includes("Откройте документ")) throw new Error("idle preview has the wrong message");

const posts = [];
const pending = [];
global.fetch = (_url, options) => {
  const job = defer();
  posts.push(JSON.parse(options.body).tree);
  pending.push(job);
  return job.promise;
};
tree = { id: "root", name: "", children: [{ document_name: "note.txt" }] };
persistTree();
tree = {
  id: "root",
  name: "",
  children: [{ id: "folder", name: "Папка", children: [{ document_name: "note.txt" }] }],
};
persistTree();
pending[0].resolve({
  ok: true,
  json: async () => ({ tree: { id: "root", name: "", children: [{ document_name: "note.txt" }] } }),
});
for (let i = 0; i < 8 && posts.length < 2; i += 1) await Promise.resolve();
if (!posts[1].children[0].children) throw new Error("overlapping save sent the stale tree");
pending[1].resolve({ ok: true, json: async () => ({ tree: posts[1] }) });
for (let i = 0; i < 8 && treeWriting; i += 1) await Promise.resolve();
if (tree.children[0].id !== "folder") throw new Error("stale save replaced the folder");
if (painted < 1) throw new Error("settled save did not paint");

console.log("ok");
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


def test_preview_ignores_a_stale_document_and_a_stale_tree_save():
    page = HTML.read_text(encoding="utf-8")
    assert "if (activeTab !== name) return;" in page
    assert "if (!ok || treePending) continue;" in page
    completed = subprocess.run(
        [NODE, "-e", SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "TREE_HTML": str(HTML)},
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"
