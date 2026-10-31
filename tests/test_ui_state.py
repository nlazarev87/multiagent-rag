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
  const node = { tag, className: "", textContent: "", children: [], attrs: {}, type: "" };
  node.classList = {
    add(name) {
      const parts = new Set(node.className.split(/\s+/).filter(Boolean));
      parts.add(name);
      node.className = [...parts].join(" ");
    },
    remove(name) {
      node.className = node.className.split(/\s+/).filter((part) => part && part !== name).join(" ");
    },
    toggle(name, force) {
      const has = node.className.split(/\s+/).includes(name);
      const next = force === undefined ? !has : Boolean(force);
      if (next) this.add(name);
      else this.remove(name);
      return next;
    },
  };
  node.setAttribute = (key, value) => { node.attrs[key] = String(value); };
  node.getAttribute = (key) => (key in node.attrs ? node.attrs[key] : null);
  node.addEventListener = () => {};
  node.append = (...kids) => {
    for (const kid of kids) {
      kid.parentNode = node;
      node.children.push(kid);
    }
  };
  return node;
}

function hasClass(node, name) {
  return (node.className || "").split(/\s+/).includes(name);
}

function walk(node, visit) {
  visit(node);
  for (const child of node.children || []) walk(child, visit);
}

function chips(node) {
  const found = [];
  walk(node, (current) => {
    if (hasClass(current, "chip")) found.push(current);
  });
  return found;
}

function rates(node) {
  const found = [];
  walk(node, (current) => {
    if (current.className === "rate") {
      found.push({
        label: current.children[0].textContent,
        on: current.children.filter((child) => hasClass(child, "on")).map((child) => child.textContent),
      });
    }
  });
  return found;
}

if (!AbortSignal.timeout) AbortSignal.timeout = () => new AbortController().signal;
global.document = { createElement: createNode };

const modeAgent = createNode("button");
modeAgent.className = "on";
const modeDocs = createNode("button");
const agentPane = createNode("div");
const docsPane = createNode("div");
docsPane.className = "hidden";
const docsTools = createNode("div");
docsTools.className = "hidden";
const readiness = { textContent: "" };
const readyDot = createNode("span");

let tree = { id: "root", name: "", children: [] };
let filter = "";
let systemReady = false;
let treeFresh = false;
let dialogs = [];
let dialogId = "";
let openTabs = [];
let activeTab = "";
let tabChunks = {};
const loads = [];
const retries = [];
const patches = [];
const fetches = [];
const painted = [];
let paints = 0;
let idled = 0;
let persisted = 0;

function current() {
  return dialogs.find((row) => row.id === dialogId) || null;
}
async function loadUi(flag) { loads.push(flag); }
function paintTree() { paints += 1; }
function paintTabs() {}
function paintChunks(chunks) { painted.push(chunks.map((chunk) => chunk.text).join("|")); }
function idlePreview() { idled += 1; }
function persistTree() { persisted += 1; }
global.setTimeout = (_fn, delay) => { retries.push(delay); return 0; };
global.window = { prompt: () => null };

for (const name of [
  "element", "rateRow", "sourceBlocks", "saveRate", "showReady",
  "treeFiles", "ensureTreeFiles", "setMode", "closeTab", "nodeMatches", "renameFolder",
]) eval(extract(name));

async function main() {
  const wrap = sourceBlocks([
    { number: 1, document_name: "note.txt", chunk_index: 0, section: "Склад" },
    { number: 2, document_name: "note.txt", chunk_index: "" },
  ], "Давление 6 бар", { links: { "1": 4, "2": 1 }, documents: { "note.txt": 2 } }, 3);
  const found = chips(wrap);
  if (found.length !== 3) throw new Error("citations and the document were not one chip each: " + found.length);
  const cite1 = found.find((chip) => chip.textContent === "[1]");
  const cite2 = found.find((chip) => chip.textContent === "[2]");
  const file = found.find((chip) => chip.textContent === "note.txt");
  if (!cite1 || cite1.getAttribute("data-index") !== "0" || cite1.getAttribute("data-section") !== "Склад") {
    throw new Error("the first chunk lost its index or section");
  }
  if (cite1.getAttribute("data-document") !== "note.txt" || cite1.getAttribute("data-answer") !== "Давление 6 бар") {
    throw new Error("the citation lost the document or the answer text");
  }
  if (!cite2 || cite2.getAttribute("data-index") !== null || cite2.getAttribute("data-section") !== null) {
    throw new Error("an empty chunk index was sent to the preview");
  }
  if (cite2.getAttribute("data-answer") !== "Давление 6 бар") throw new Error("the second citation lost the answer");
  if (!file || file.getAttribute("data-index") !== null) throw new Error("the document chip was aimed at a chunk");
  const rows = rates(wrap);
  if (rows.map((row) => row.label + ":" + row.on.join(",")).join("|") !== [
    "Правильность ссылки:4",
    "Правильность документа:2",
    "Правильность ссылки:1",
  ].join("|")) throw new Error("rating buttons: " + JSON.stringify(rows));

  const bare = sourceBlocks([{ number: 3, document_name: "plain.txt", chunk_index: 0 }], "", null, 0);
  const bareCite = chips(bare).find((chip) => chip.textContent === "[3]");
  if (!bareCite || bareCite.getAttribute("data-index") !== "0" || bareCite.getAttribute("data-answer") !== null) {
    throw new Error("a chunk index of zero was dropped, or an empty answer was stored");
  }

  dialogs = [{
    id: "d",
    turns: [{ ratings: { answer_complete: 5, answer_correct: 1, links: { "1": 2 }, documents: { "a.txt": 3 } } }],
  }];
  global.fetch = async (url, options) => {
    patches.push({ url, method: options.method, body: JSON.parse(options.body) });
    return { ok: true };
  };
  await saveRate(0, { answer_complete: 1 });
  if (patches.length) throw new Error("a rating was saved without a dialog");
  dialogId = "d";
  await saveRate(-1, { answer_complete: 1 });
  if (patches.length) throw new Error("a rating was saved for a negative turn");
  await saveRate(0, { links: { "2": 4 } });
  const ratings = dialogs[0].turns[0].ratings;
  if (ratings.answer_complete !== 5 || ratings.answer_correct !== 1 || ratings.links["1"] !== 2 || ratings.links["2"] !== 4) {
    throw new Error("a link score replaced the other ratings: " + JSON.stringify(ratings));
  }
  await saveRate(0, { documents: { "b.txt": 1 } });
  if (ratings.documents["a.txt"] !== 3 || ratings.documents["b.txt"] !== 1) {
    throw new Error("a document score replaced the other document");
  }
  await saveRate(0, { answer_complete: 4 });
  if (ratings.answer_complete !== 4 || ratings.answer_correct !== 1) throw new Error("the other score was cleared");
  await saveRate(3, { answer_correct: 2 });
  if (dialogs[0].turns.length !== 1 || ratings.answer_correct !== 1) throw new Error("a missing turn was created");
  if (patches.at(-1).method !== "PATCH" || !patches.at(-1).url.includes("/turns/3/ratings")) {
    throw new Error("the missing turn was not the request that was sent");
  }
  dialogId = "gone";
  await saveRate(0, { answer_complete: 2 });
  if (ratings.answer_complete !== 4) throw new Error("a missing dialog changed another dialog");

  global.fetch = async () => ({ status: 200, json: async () => ({}) });
  await showReady();
  if (!systemReady || readiness.textContent !== "Система готова" || !hasClass(readyDot, "on") || loads.join() !== "false") {
    throw new Error("a ready model did not load the workspace once");
  }
  if (retries.length) throw new Error("a ready model kept polling");
  await showReady();
  if (loads.length !== 1) throw new Error("every ready poll reloaded the workspace");

  global.fetch = async () => ({ status: 503, json: async () => ({ elapsed_sec: 9, eta_sec: 0 }) });
  await showReady();
  if (systemReady || hasClass(readyDot, "on") || loads.length !== 1) throw new Error("a loading model stayed ready");
  if (readiness.textContent !== "Модель загружается. Прошло 9 с. Осталось около 0 с.") {
    throw new Error("a zero estimate was hidden: " + readiness.textContent);
  }
  if (retries[0] !== 2000) throw new Error("loading did not poll again");
  global.fetch = async () => ({ status: 503, json: async () => ({ elapsed_sec: 9, eta_sec: null }) });
  await showReady();
  if (readiness.textContent !== "Модель загружается. Прошло 9 с.") {
    throw new Error("a missing estimate was shown as a number: " + readiness.textContent);
  }
  global.fetch = async () => { throw new Error("down"); };
  await showReady();
  if (readiness.textContent !== "Модель загружается…" || hasClass(readyDot, "on") || systemReady) {
    throw new Error("a dead readiness check stayed ready");
  }

  global.fetch = async (url) => {
    fetches.push(url);
    return { json: async () => ({ documents: ["from-server.txt"] }) };
  };
  tree = { id: "root", name: "", children: [{ id: "f", name: "Папка", children: [{ document_name: "kept.txt" }] }] };
  await setMode("agent");
  if (fetches.length || paints) throw new Error("the agent mode fetched documents or repainted the tree");
  await setMode("docs");
  if (fetches.length) throw new Error("opening documents fetched a list the tree already had");
  if (tree.children.some((child) => child.document_name)) throw new Error("a nested file was copied to the root");
  if (!hasClass(agentPane, "hidden") || hasClass(docsPane, "hidden") || hasClass(docsTools, "hidden")) {
    throw new Error("the document panes stayed hidden");
  }
  if (modeAgent.getAttribute("aria-selected") !== "false" || modeDocs.getAttribute("aria-selected") !== "true") {
    throw new Error("the mode tabs did not switch");
  }
  if (hasClass(modeAgent, "on") || !hasClass(modeDocs, "on") || paints !== 1) {
    throw new Error("the document mode did not paint the tree it already had");
  }
  tree = { id: "root", name: "", children: [] };
  await setMode("docs");
  if (fetches.length !== 1 || !String(fetches[0]).includes("/documents")) throw new Error("an empty tree did not ask for documents");
  if (!tree.children.some((child) => child.document_name === "from-server.txt")) {
    throw new Error("documents from the index were not added");
  }
  tree = { id: "root", name: "", children: [] };
  global.fetch = async () => { throw new Error("down"); };
  await setMode("docs");
  if (tree.children.length) throw new Error("a failed document list filled the tree");

  openTabs = ["a.txt", "b.txt"];
  activeTab = "a.txt";
  tabChunks = {
    "a.txt": [{ text: "текст а", chunk_index: 0 }],
    "b.txt": [{ text: "текст б", chunk_index: 1 }],
  };
  closeTab("b.txt");
  if (activeTab !== "a.txt" || tabChunks["b.txt"] || !tabChunks["a.txt"] || painted.at(-1) !== "текст а" || idled) {
    throw new Error("closing a background tab changed the open document");
  }
  closeTab("a.txt");
  if (activeTab !== "" || tabChunks["a.txt"] || openTabs.length || idled !== 1) {
    throw new Error("closing the last tab left a document open");
  }
  openTabs = ["a.txt", "b.txt"];
  activeTab = "a.txt";
  tabChunks = {
    "a.txt": [{ text: "текст а", chunk_index: 0 }],
    "b.txt": [{ text: "текст б", chunk_index: 1 }],
  };
  idled = 0;
  closeTab("a.txt");
  if (activeTab !== "b.txt" || painted.at(-1) !== "текст б" || tabChunks["a.txt"] || idled) {
    throw new Error("closing the open tab did not show the remaining document");
  }

  filter = "";
  const folder = { name: "Склад", children: [{ document_name: "Note.TXT" }] };
  if (!nodeMatches({ name: "", children: [] })) throw new Error("an empty filter hid a node");
  filter = "note";
  if (!nodeMatches(folder) || !nodeMatches({ name: "", children: [folder] })) {
    throw new Error("a folder hid a file whose name matches");
  }
  if (nodeMatches({ document_name: "archive.txt" })) throw new Error("an unrelated file matched the filter");
  if (!nodeMatches({ document_name: "notebook.txt" })) throw new Error("the filter stopped matching inside a name");
  filter = "склад";
  if (!nodeMatches(folder)) throw new Error("a folder name ignored letter case");
  filter = "note";
  if (nodeMatches({ name: "Архив", children: [{ document_name: "old.txt" }] })) {
    throw new Error("a folder matched without its file or its name");
  }

  const named = { id: "f", name: "Старое" };
  window.prompt = () => null;
  renameFolder(named);
  window.prompt = () => "   ";
  renameFolder(named);
  if (named.name !== "Старое" || persisted) throw new Error("a cancelled rename changed the folder");
  window.prompt = () => "  Новый склад  ";
  renameFolder(named);
  if (named.name !== "Новый склад" || persisted !== 1) throw new Error("the folder name was not trimmed");
  window.prompt = () => "я".repeat(90);
  renameFolder(named);
  if (named.name !== "я".repeat(80) || persisted !== 2) throw new Error("a long folder name was stored whole");

  console.log("ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
"""


def test_citations_ready_state_folder_filter_and_names():
    completed = subprocess.run(
        [NODE, "-e", SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "TREE_HTML": str(HTML)},
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"
