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
  const start = html.indexOf(token);
  if (start < 0) throw new Error("missing " + name);
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
const closedFolders = new Set();
let persisted = 0;
function persistTree() {
  JSON.stringify(tree);
  persisted += 1;
}
eval(extract("findParent"));
eval(extract("containsNode"));
eval(extract("dropOn"));

function sample() {
  return {
    id: "root",
    name: "",
    children: [
      {
        id: "c",
        name: "Outer",
        children: [
          {
            id: "a",
            name: "Nested",
            children: [
              { id: "b", name: "Inner", children: [] },
              { document_name: "note.txt" },
            ],
          },
        ],
      },
    ],
  };
}

function parentOf(node, target, parent) {
  if (node === target) return parent;
  for (const child of node.children || []) {
    const found = parentOf(child, target, node);
    if (found) return found;
  }
  return null;
}

function findId(node, id) {
  if (node.id === id) return node;
  for (const child of node.children || []) {
    const found = findId(child, id);
    if (found) return found;
  }
  return null;
}

let tree = sample();
persisted = 0;
dropOn(tree, JSON.stringify({ folder: true, id: "a", name: "" }));
const lifted = findId(tree, "a");
if (parentOf(tree, lifted, null) !== tree) throw new Error("folder did not move to the root");
if (persisted !== 1) throw new Error("root move was not saved");
if (!findId(lifted, "b") || !lifted.children.some((child) => child.document_name === "note.txt")) {
  throw new Error("folder lost its contents on the way to the root");
}

tree = sample();
const before = JSON.stringify(tree);
persisted = 0;
dropOn(findId(tree, "b"), JSON.stringify({ folder: true, id: "a", name: "" }));
if (JSON.stringify(tree) !== before) throw new Error("drop into a descendant changed the tree");
if (persisted !== 0) throw new Error("cyclic drop was saved");
dropOn(findId(tree, "a"), JSON.stringify({ folder: true, id: "a", name: "" }));
if (JSON.stringify(tree) !== before) throw new Error("drop onto itself changed the tree");
JSON.stringify(tree);

tree = sample();
persisted = 0;
dropOn(tree, JSON.stringify({ folder: false, id: "", name: "note.txt" }));
if (!tree.children.some((child) => child.document_name === "note.txt")) {
  throw new Error("file did not move to the root");
}
if (findId(tree, "a").children.some((child) => child.document_name === "note.txt")) {
  throw new Error("file stayed in the old folder");
}
if (persisted !== 1) throw new Error("file move was not saved");

console.log("ok");
"""


def test_folder_drop_moves_up_and_refuses_a_cycle():
    page = HTML.read_text(encoding="utf-8")
    assert "subtreeIds(folder).has(payload.id)" not in page
    assert "containsNode(found.node, folder)" in page
    completed = subprocess.run(
        [NODE, "-e", SCRIPT],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "TREE_HTML": str(HTML)},
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"
