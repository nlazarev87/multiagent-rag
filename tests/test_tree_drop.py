import json
import os
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

import api
import kb
import trees
import workspace
from api import app

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


def _client(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("APP_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("CONFIG_DIR", str(repo / "config"))
    monkeypatch.setenv("PROMPTS_DIR", str(repo / "data" / "prompts"))
    monkeypatch.delenv("RAG_TEST_USER", raising=False)
    import settings
    settings.reload()
    path = tmp_path / "workspace.json"
    monkeypatch.setattr(workspace, "PATH", path)
    monkeypatch.setattr(workspace, "DEFAULT", path)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setattr(api, "INBOX", inbox)
    monkeypatch.setattr(api, "list_documents", lambda: ["note.txt"])
    client = TestClient(app)
    assert client.post("/setup", json={"login": "admin", "password": "password12"}).status_code == 200
    api._state["done"] = True
    return client


def test_second_move_does_not_erase_the_saved_tree(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    source = {
        "dialogs": [],
        "tree": {"id": "root", "name": "", "children": [{"id": "old", "name": "Архив", "children": []}]},
    }
    workspace.PATH.write_text(json.dumps(source), encoding="utf-8")
    trees.migrate()
    target = trees.path_for(kb.get(kb.LEGACY_ID))
    assert trees.read(target)["children"][0]["name"] == "Архив"
    trees.write(target, trees.empty())
    trees.migrate()
    assert trees.read(target)["children"] == []


def test_broken_tree_file_is_left_in_place(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    target = trees.path_for(kb.get(kb.LEGACY_ID))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{", encoding="utf-8")
    assert trees.read(target)["children"] == []
    assert target.read_text(encoding="utf-8") == "{"


def test_folder_is_not_stored_inside_itself(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    sent = {
        "id": "root",
        "name": "",
        "children": [
            {
                "id": "f",
                "name": "Склад",
                "children": [{"id": "f", "name": "Внутри", "children": []}],
            },
            {"document_name": "note.txt"},
        ],
    }
    response = client.put("/ui", json={"tree": sent})
    assert response.status_code == 200
    stored = trees.read(trees.path_for(kb.get(kb.LEGACY_ID)))
    folder = next(child for child in stored["children"] if child.get("id") == "f")
    assert folder["children"] == []
    assert "note.txt" in workspace.iter_files(stored)


def test_file_from_another_base_does_not_enter_this_tree(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    kb.create("Кадры")
    response = client.put("/ui", json={"tree": {
        "id": "root",
        "name": "",
        "children": [{"document_name": "чужой.txt"}, {"document_name": "note.txt"}],
    }})
    assert response.status_code == 200
    names = workspace.iter_files(trees.read(trees.path_for(kb.get(kb.LEGACY_ID))))
    assert names == ["note.txt"]
