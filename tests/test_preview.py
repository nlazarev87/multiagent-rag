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
  if (html.slice(start - 6, start) === "async ") start -= 6;
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

function createNode(tag) {
  const node = {
    tag,
    className: "",
    textContent: "",
    children: [],
    parentNode: null,
    attrs: {},
    scrolled: null,
    scrollTop: 0,
  };
  node.classList = {
    add(name) {
      const parts = new Set(node.className.split(/\s+/).filter(Boolean));
      parts.add(name);
      node.className = [...parts].join(" ");
    },
    remove(name) {
      node.className = node.className.split(/\s+/).filter((part) => part && part !== name).join(" ");
    },
  };
  node.append = (...kids) => {
    for (const kid of kids) {
      kid.parentNode = node;
      node.children.push(kid);
    }
  };
  node.replaceChildren = (...kids) => {
    node.children = [];
    node.append(...kids);
  };
  node.setAttribute = (key, value) => {
    node.attrs[key] = String(value);
  };
  node.getAttribute = (key) => (key in node.attrs ? node.attrs[key] : null);
  node.addEventListener = () => {};
  node.querySelector = (selector) => find(node, selector);
  node.scrollIntoView = (options) => {
    node.scrolled = options || {};
  };
  return node;
}

function matches(node, selector) {
  if (selector === ".hit") return node.className.split(/\s+/).includes("hit");
  const found = /^\[data-index="(.*)"\]$/.exec(selector);
  return Boolean(found) && node.attrs["data-index"] === found[1];
}

function find(node, selector) {
  for (const child of node.children || []) {
    if (matches(child, selector)) return child;
    const nested = find(child, selector);
    if (nested) return nested;
  }
  return null;
}

function visible(node) {
  return (node.textContent || "") + (node.children || []).map(visible).join("");
}

function defer() {
  let resolve, reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function flush() {
  for (let step = 0; step < 8; step += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

const document = { createElement: createNode };
let preview = document.createElement("div");
preview.parentNode = document.createElement("div");
const tabsEl = document.createElement("div");
let openTabs = [];
let activeTab = "";
let tabChunks = {};
let tree = { id: "root", name: "", children: [] };
let treePending = false;
let treeWriting = false;
let treeStamp = 0;
let painted = 0;

function paintTree() {
  painted += 1;
}

if (!AbortSignal.timeout) AbortSignal.timeout = () => new AbortController().signal;

for (const name of [
  "tokens", "contentWords", "coverage", "blocks", "element",
  "paintChunks", "paintTabs", "showPreview",
  "treeFiles", "ensureTreeFiles", "removeFolder", "persistTree",
]) eval(extract(name));

process.on("unhandledRejection", (error) => {
  console.error(error);
  process.exit(1);
});

async function main() {
  const same = "Рабочее давление системы указано";
  paintChunks(
    [
      { text: same, chunk_index: 1 },
      { text: same, chunk_index: 4 },
    ],
    { chunkIndex: "4", answer: "Рабочее давление системы" },
  );
  const tied = preview.querySelector(".hit");
  if (!tied || tied.parentNode.getAttribute("data-index") !== "4") {
    throw new Error("equal highlight did not stay on the cited chunk");
  }

  paintChunks(
    [
      { text: "Рабочее давление системы равно норме", chunk_index: 1 },
      { text: "Склад закрыт по воскресеньям вечером", chunk_index: 4 },
    ],
    { chunkIndex: "4", answer: "Рабочее давление системы" },
  );
  const better = preview.querySelector(".hit");
  if (!better || better.parentNode.getAttribute("data-index") !== "1") {
    throw new Error("a closer paragraph lost to the cited chunk");
  }

  paintChunks(
    [{ text: "Учетная запись оператора создана", chunk_index: 0 }],
    { answer: "Учётная запись оператора" },
  );
  if (!visible(preview.querySelector(".hit") || {}).includes("Учетная")) {
    throw new Error("yo in the answer did not match ye in the document");
  }

  preview.parentNode.scrollTop = 7;
  paintChunks([{ text: "Давление равно 6 бар", chunk_index: 1 }], { answer: "6 бар" });
  if (preview.querySelector(".hit")) throw new Error("short answer words highlighted a paragraph");
  if (preview.parentNode.scrollTop !== 0) throw new Error("preview did not return to the top");

  paintChunks(
    [
      { text: "Первый абзац", chunk_index: 1, section: "Иное" },
      { text: "Нужный абзац", chunk_index: 2, section: "Склад" },
    ],
    { chunkIndex: "", section: "Склад" },
  );
  const cited = preview.querySelector('[data-index="2"]');
  if (!cited || cited.scrolled.block !== "start") {
    throw new Error("cited section was not scrolled into view");
  }
  if (preview.querySelector(".hit")) throw new Error("section fallback also highlighted a paragraph");

  tree = {
    id: "root",
    name: "",
    children: [
      { id: "folder", name: "Папка", children: [{ document_name: "note.txt" }] },
    ],
  };
  ensureTreeFiles(["note.txt", "", "other.txt", "other.txt"]);
  const rooted = tree.children.filter((child) => child.document_name).map((child) => child.document_name);
  if (rooted.join(",") !== "other.txt") {
    throw new Error("a file already in a folder was copied to the root: " + JSON.stringify(tree));
  }
  const folder = tree.children.find((child) => child.id === "folder");
  if (!folder.children.some((child) => child.document_name === "note.txt")) {
    throw new Error("nested file left its folder");
  }

  tree = {
    id: "root",
    name: "",
    children: [
      {
        id: "folder",
        name: "Папка",
        children: [
          { document_name: "note.txt" },
          { id: "inner", name: "Внутри", children: [{ document_name: "inner.txt" }] },
        ],
      },
      { document_name: "root.txt" },
    ],
  };
  let saves = 0;
  global.fetch = () => {
    saves += 1;
    return new Promise(() => {});
  };
  removeFolder({ id: "missing" }, tree);
  if (saves !== 0) throw new Error("a missing folder was saved");
  removeFolder(tree.children[0], tree);
  if (saves !== 1) throw new Error("deleting a folder was not saved");
  const kept = [];
  (function walk(node) {
    if (node.document_name) kept.push(node.document_name);
    (node.children || []).forEach(walk);
  })(tree);
  if (kept.join(",") !== "note.txt,inner.txt,root.txt") {
    throw new Error("deleting a folder dropped its files: " + kept.join(","));
  }
  if (!tree.children.some((child) => child.id === "inner")) {
    throw new Error("a nested folder was not lifted");
  }

  treeWriting = false;
  treePending = false;
  painted = 0;
  tree = { id: "root", name: "", children: [{ document_name: "kept.txt" }] };
  global.fetch = async () => ({
    ok: false,
    json: async () => ({ tree: { id: "root", name: "", children: [] } }),
  });
  persistTree();
  await flush();
  if (painted !== 0) throw new Error("a failed save repainted the tree");
  if (tree.children[0].document_name !== "kept.txt") throw new Error("a failed save cleared the tree");

  treeWriting = false;
  treePending = false;
  painted = 0;
  tree = { id: "root", name: "", children: [{ document_name: "first.txt" }] };
  const firstSave = defer();
  const calls = [];
  global.fetch = (_url, options) => {
    calls.push(JSON.parse(options.body).tree);
    if (calls.length === 1) return firstSave.promise;
    return Promise.resolve({
      ok: true,
      json: async () => ({ tree: { id: "root", name: "", children: [{ document_name: "from-server.txt" }] } }),
    });
  };
  persistTree();
  if (calls.length !== 1 || calls[0].children[0].document_name !== "first.txt") {
    throw new Error("the first save did not send the tree it started with");
  }
  tree = { id: "root", name: "", children: [{ document_name: "second.txt" }] };
  persistTree();
  firstSave.resolve({
    ok: true,
    json: async () => ({ tree: { id: "root", name: "", children: [{ document_name: "stale-server.txt" }] } }),
  });
  await flush();
  if (calls.length !== 2 || calls[1].children[0].document_name !== "second.txt") {
    throw new Error("the later edit was not the save that followed the stale response");
  }
  if (tree.children[0].document_name !== "from-server.txt") {
    throw new Error("a stale save replaced the newer tree: " + tree.children[0].document_name);
  }
  if (painted !== 1) throw new Error("a stale save repainted the tree");

  openTabs = [];
  activeTab = "";
  tabChunks = {};
  const fetches = [];
  const gates = new Map();
  global.fetch = (url) => {
    fetches.push(url);
    for (const [part, gate] of gates) {
      if (url.includes(part)) return gate.promise;
    }
    if (url.includes("missing")) {
      return Promise.resolve({ ok: false, json: async () => ({ detail: "Документ не найден" }) });
    }
    if (url.includes("empty")) {
      return Promise.resolve({ ok: true, json: async () => ({ chunks: [] }) });
    }
    if (url.includes("boom")) return Promise.reject(new Error("down"));
    return Promise.resolve({
      ok: true,
      json: async () => ({ chunks: [{ text: "Быстрый документ про давление", chunk_index: 3 }] }),
    });
  };
  await showPreview("");
  if (fetches.length !== 0) throw new Error("a blank name requested a preview");

  const slow = defer();
  gates.set("slow.txt", slow);
  const slowDone = showPreview("slow.txt");
  const fastDone = showPreview("fast.txt");
  await fastDone;
  if (!visible(preview).includes("Быстрый документ про давление")) {
    throw new Error("the open preview was not painted");
  }
  slow.resolve({
    ok: true,
    json: async () => ({ chunks: [{ text: "Медленный документ про склад", chunk_index: 1 }] }),
  });
  await slowDone;
  await flush();
  if (visible(preview).includes("Медленный")) throw new Error("a slow preview overwrote the open tab");
  if (!visible(preview).includes("Быстрый документ про давление")) {
    throw new Error("the open tab was cleared by a slow preview");
  }
  if (!tabChunks["slow.txt"] || tabChunks["slow.txt"][0].text !== "Медленный документ про склад") {
    throw new Error("a finished preview was dropped because the user had switched tabs");
  }
  const fetched = fetches.length;
  await showPreview("slow.txt");
  if (fetches.length !== fetched) throw new Error("a cached preview was requested again");
  if (!visible(preview).includes("Медленный документ про склад")) {
    throw new Error("a cached preview was not painted when its tab was opened");
  }

  const lateError = defer();
  gates.set("boom-late", lateError);
  const lateErrorDone = showPreview("boom-late.txt");
  await showPreview("fast.txt");
  lateError.reject(new Error("down"));
  await lateErrorDone;
  if (visible(preview).includes("Сервер не ответил")) {
    throw new Error("a failed preview overwrote the open tab");
  }
  if (!visible(preview).includes("Быстрый документ про давление")) {
    throw new Error("the open tab was cleared by a failed preview");
  }

  const lateMissing = defer();
  gates.set("missing-late", lateMissing);
  const lateMissingDone = showPreview("missing-late.txt");
  await showPreview("fast.txt");
  lateMissing.resolve({ ok: false, json: async () => ({ detail: "Документ не найден" }) });
  await lateMissingDone;
  if (visible(preview).includes("Документ не найден")) {
    throw new Error("a missing preview overwrote the open tab");
  }

  await showPreview("missing.txt");
  if (visible(preview) !== "Документ не найден") throw new Error("a missing document was not reported");
  await showPreview("empty.txt");
  if (visible(preview) !== "Нет текста") throw new Error("an empty document was " + JSON.stringify(visible(preview)));
  await showPreview("boom.txt");
  if (visible(preview) !== "Сервер не ответил") throw new Error("a dead preview was " + JSON.stringify(visible(preview)));

  console.log("ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


def test_preview_and_tree_save_ignore_a_stale_result():
    completed = subprocess.run(
        [NODE, "-e", SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "TREE_HTML": str(HTML)},
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"
