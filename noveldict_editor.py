#!/usr/bin/env python3
"""
noveldict_editor.py — Web UI for editing your noveldict master dictionary.

Supports filtering by type/book, editing descriptions and aliases,
adding and deleting entries, and rebuilding the StarDict output.

Usage:
    python3 noveldict_editor.py
    python3 noveldict_editor.py --output-dir ~/mydict --dict-name "SciFi"
    Then open http://localhost:5001 in your browser.

Requirements:
    pip install flask pyglossary
"""

import json
import argparse
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, render_template_string
from pyglossary import Glossary

DEFAULT_OUTPUT_DIR = Path.home() / "noveldict_output"
DEFAULT_DICT_NAME  = "Novels"
DEFAULT_HOST = "127.0.0.1"

app = Flask(__name__)

# Set by CLI args at startup
OUTPUT_DIR  = DEFAULT_OUTPUT_DIR
DICT_NAME   = DEFAULT_DICT_NAME
MASTER_JSON = DEFAULT_OUTPUT_DIR / "master_dictionary.json"


# ── Data helpers ──────────────────────────────────────────────────────────────

def load_master() -> dict:
    if MASTER_JSON.exists():
        return json.loads(MASTER_JSON.read_text(encoding="utf-8"))
    return {"entries": {}, "books_processed": []}


def save_master(data: dict):
    MASTER_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── StarDict rebuild ──────────────────────────────────────────────────────────

def rebuild_stardict() -> tuple[bool, str]:
    master = load_master()
    try:
        Glossary.init()
        glos = Glossary()
        glos.setInfo("title", DICT_NAME)
        glos.setInfo("description", "Characters and world terms extracted from novels")
        glos.setInfo("author", "noveldict")

        for entry in sorted(master["entries"].values(), key=lambda e: e["name"].lower()):
            name    = entry["name"]
            etype   = entry.get("type", "character")
            desc    = entry.get("description", "")
            aliases = entry.get("aliases", [])
            source  = entry.get("source_book", "")

            type_label  = "Character" if etype == "character" else "World term"
            source_html = (f' <span style="color:#888;font-size:0.85em;">({source})</span>'
                           if source else "")
            defi = (
                f'<p><b>{name}</b> <i style="color:#666;">{type_label}</i>{source_html}</p>'
                f"<p>{desc}</p>"
            )
            words = [name] + [a for a in aliases if a]
            glos.addEntry(glos.newEntry(words, defi, defiFormat="h"))

        star_dir = OUTPUT_DIR / DICT_NAME
        star_dir.mkdir(parents=True, exist_ok=True)
        glos.write(str(star_dir / DICT_NAME), format="Stardict", dictzip=True)

        total_kb = sum(f.stat().st_size for f in star_dir.iterdir()) / 1024
        return True, f"Built {len(master['entries'])} entries → {star_dir.name}/ ({total_kb:.1f} KB)"
    except Exception as e:
        return False, str(e)


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>noveldict editor</title>
<style>
  :root {
    --ink:    #1a1a1a;
    --paper:  #f7f4ef;
    --border: #d4cfc7;
    --accent: #8b5e3c;
    --green:  #4a7c6f;
    --dim:    #7a746e;
    --danger: #b94040;
    --card:   #ffffff;
    --radius: 6px;
    --shadow: 0 1px 3px rgba(0,0,0,0.08);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Georgia, serif; background: var(--paper); color: var(--ink); min-height: 100vh; }

  header {
    background: var(--ink); color: var(--paper);
    padding: 1rem 2rem; display: flex; align-items: baseline; gap: 1rem;
  }
  header h1 { font-size: 1.15rem; font-weight: normal; letter-spacing: 0.05em; }
  header .stats { font-size: 0.8rem; color: #aaa; font-family: monospace; margin-left: auto; }

  .container { max-width: 1150px; margin: 0 auto; padding: 1.5rem 2rem; }

  .rebuild-bar {
    background: var(--card); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 0.75rem 1rem;
    margin-bottom: 1.25rem; display: flex; align-items: center;
    gap: 1rem; box-shadow: var(--shadow);
  }
  .rebuild-bar p { font-size: 0.85rem; color: var(--dim); flex: 1; }
  #rebuild-status { font-size: 0.82rem; color: var(--dim); font-family: monospace; }

  .toolbar {
    display: flex; gap: 0.75rem; align-items: center;
    margin-bottom: 1.25rem; flex-wrap: wrap;
  }
  .toolbar input[type=search] {
    flex: 1; min-width: 200px; padding: 0.5rem 0.75rem;
    border: 1px solid var(--border); border-radius: var(--radius);
    font-size: 0.9rem; font-family: inherit; background: var(--card);
  }
  .toolbar select {
    padding: 0.5rem 0.75rem; border: 1px solid var(--border);
    border-radius: var(--radius); font-size: 0.85rem;
    background: var(--card); font-family: inherit; cursor: pointer;
  }
  .entry-count { font-size: 0.8rem; color: var(--dim); padding: 0 0.25rem; }

  .btn {
    padding: 0.5rem 1rem; border: none; border-radius: var(--radius);
    font-size: 0.85rem; cursor: pointer; font-family: inherit;
    font-weight: bold; letter-spacing: 0.02em; transition: opacity 0.15s;
  }
  .btn:hover { opacity: 0.85; }
  .btn:disabled { opacity: 0.5; cursor: default; }
  .btn-primary   { background: var(--accent); color: white; }
  .btn-secondary { background: var(--green);  color: white; }
  .btn-danger    { background: var(--danger); color: white; }
  .btn-ghost     { background: transparent; border: 1px solid var(--border); color: var(--ink); }
  .btn-sm { padding: 0.25rem 0.6rem; font-size: 0.78rem; }

  .table-wrap { overflow-x: auto; }
  table {
    width: 100%; border-collapse: collapse;
    background: var(--card); border-radius: var(--radius);
    overflow: hidden; box-shadow: var(--shadow);
  }
  thead { background: var(--ink); color: var(--paper); }
  th {
    padding: 0.65rem 1rem; text-align: left; font-size: 0.78rem;
    font-weight: normal; letter-spacing: 0.06em;
    text-transform: uppercase; font-family: monospace;
  }
  td { padding: 0.6rem 1rem; border-bottom: 1px solid var(--border); font-size: 0.88rem; vertical-align: top; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #faf8f5; }

  .type-badge {
    display: inline-block; padding: 0.15rem 0.5rem; border-radius: 99px;
    font-size: 0.72rem; font-family: monospace; font-weight: bold; letter-spacing: 0.04em;
  }
  .type-character  { background: #e8f0ef; color: var(--green); }
  .type-world_term { background: #f0ebe5; color: var(--accent); }

  .aliases { color: var(--dim); font-size: 0.8rem; font-style: italic; }
  .source  { color: var(--dim); font-size: 0.78rem; font-family: monospace; }
  .desc    { max-width: 420px; line-height: 1.5; }
  .action-btns { display: flex; gap: 0.4rem; white-space: nowrap; }

  .modal-overlay {
    display: none; position: fixed; inset: 0;
    background: rgba(0,0,0,0.45); z-index: 100;
    align-items: center; justify-content: center;
  }
  .modal-overlay.open { display: flex; }
  .modal {
    background: var(--card); border-radius: var(--radius);
    padding: 2rem; width: 100%; max-width: 520px;
    max-height: 90vh; overflow-y: auto;
    box-shadow: 0 8px 32px rgba(0,0,0,0.18);
  }
  .modal h2 { font-size: 1rem; margin-bottom: 1.25rem; font-weight: normal; letter-spacing: 0.04em; }
  .form-group { margin-bottom: 1rem; }
  .form-group label {
    display: block; font-size: 0.78rem; color: var(--dim);
    margin-bottom: 0.3rem; text-transform: uppercase;
    letter-spacing: 0.05em; font-family: monospace;
  }
  .form-group input,
  .form-group select,
  .form-group textarea {
    width: 100%; padding: 0.5rem 0.75rem;
    border: 1px solid var(--border); border-radius: var(--radius);
    font-size: 0.9rem; font-family: inherit; background: var(--paper);
  }
  .form-group textarea { min-height: 90px; resize: vertical; line-height: 1.5; }
  .modal-actions { display: flex; gap: 0.75rem; justify-content: flex-end; margin-top: 1.5rem; }

  .empty { text-align: center; padding: 3rem; color: var(--dim); font-style: italic; }

  #toast {
    position: fixed; bottom: 1.5rem; right: 1.5rem;
    background: var(--ink); color: var(--paper);
    padding: 0.75rem 1.25rem; border-radius: var(--radius);
    font-size: 0.85rem; opacity: 0; transition: opacity 0.3s;
    max-width: 340px; z-index: 200; line-height: 1.4;
  }
  #toast.show { opacity: 1; }
  #toast.error { background: var(--danger); }
</style>
</head>
<body>

<header>
  <h1>📖 noveldict editor</h1>
  <span class="stats" id="header-stats">Loading…</span>
</header>

<div class="container">
  <div class="rebuild-bar">
    <p>Edit entries below, then rebuild to update the StarDict dictionary on your reader.</p>
    <span id="rebuild-status"></span>
    <button class="btn btn-secondary" onclick="rebuild()">⚙ Rebuild StarDict</button>
  </div>

  <div class="toolbar">
    <input type="search" id="search" placeholder="Search names, descriptions, aliases…" oninput="applyFilters()">
    <select id="filter-type" onchange="applyFilters()">
      <option value="">All types</option>
      <option value="character">Characters</option>
      <option value="world_term">World terms</option>
    </select>
    <select id="filter-book" onchange="applyFilters()">
      <option value="">All books</option>
    </select>
    <span class="entry-count" id="entry-count"></span>
    <button class="btn btn-primary" onclick="openAdd()">+ Add entry</button>
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Name</th><th>Type</th><th>Description</th>
          <th>Aliases</th><th>Source</th><th></th>
        </tr>
      </thead>
      <tbody id="table-body">
        <tr><td colspan="6" class="empty">Loading…</td></tr>
      </tbody>
    </table>
  </div>
</div>

<div class="modal-overlay" id="modal">
  <div class="modal">
    <h2 id="modal-title">Entry</h2>
    <input type="hidden" id="modal-key">
    <div class="form-group">
      <label>Name</label>
      <input type="text" id="f-name">
    </div>
    <div class="form-group">
      <label>Type</label>
      <select id="f-type">
        <option value="character">Character</option>
        <option value="world_term">World term</option>
      </select>
    </div>
    <div class="form-group">
      <label>Description</label>
      <textarea id="f-desc"></textarea>
    </div>
    <div class="form-group">
      <label>Aliases (comma-separated)</label>
      <input type="text" id="f-aliases" placeholder="e.g. Breq, Justice of Toren">
    </div>
    <div class="form-group">
      <label>Source book</label>
      <input type="text" id="f-source">
    </div>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="saveEntry()">Save</button>
    </div>
  </div>
</div>

<div id="toast"></div>

<script>
let allEntries = [];

async function loadEntries() {
  const res  = await fetch("/api/entries");
  const data = await res.json();
  allEntries = data.entries;

  const books = [...new Set(allEntries.map(e => e.source_book).filter(Boolean))].sort();
  const sel = document.getElementById("filter-book");
  sel.innerHTML = '<option value="">All books</option>' +
    books.map(b => `<option value="${esc(b)}">${esc(b)}</option>`).join("");

  document.getElementById("header-stats").textContent =
    `${allEntries.length} entries · ${data.books_processed} books processed`;
  applyFilters();
}

function applyFilters() {
  const q    = document.getElementById("search").value.toLowerCase();
  const type = document.getElementById("filter-type").value;
  const book = document.getElementById("filter-book").value;

  const filtered = allEntries.filter(e => {
    if (type && e.type !== type) return false;
    if (book && e.source_book !== book) return false;
    if (q) {
      const hay = [e.name, e.description, ...(e.aliases||[]), e.source_book].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  renderTable(filtered);
  document.getElementById("entry-count").textContent =
    filtered.length === allEntries.length
      ? `${allEntries.length} entries`
      : `${filtered.length} of ${allEntries.length}`;
}

function renderTable(entries) {
  const tbody = document.getElementById("table-body");
  if (!entries.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">No entries match.</td></tr>`;
    return;
  }
  tbody.innerHTML = entries.map(e => `
    <tr>
      <td><strong>${esc(e.name)}</strong></td>
      <td><span class="type-badge type-${e.type}">${e.type === "character" ? "character" : "world"}</span></td>
      <td class="desc">${esc(e.description)}</td>
      <td class="aliases">${(e.aliases||[]).map(esc).join(", ")}</td>
      <td class="source">${esc(e.source_book||"")}</td>
      <td>
        <div class="action-btns">
          <button class="btn btn-ghost btn-sm" onclick='openEdit(${JSON.stringify(e)})'>Edit</button>
          <button class="btn btn-danger btn-sm" onclick="deleteEntry('${esc(e.key)}', '${esc(e.name)}')">Delete</button>
        </div>
      </td>
    </tr>`).join("");
}

function openAdd() {
  document.getElementById("modal-title").textContent = "Add entry";
  document.getElementById("modal-key").value = "";
  document.getElementById("f-name").value = "";
  document.getElementById("f-type").value = "character";
  document.getElementById("f-desc").value = "";
  document.getElementById("f-aliases").value = "";
  document.getElementById("f-source").value = "";
  document.getElementById("modal").classList.add("open");
  document.getElementById("f-name").focus();
}

function openEdit(e) {
  document.getElementById("modal-title").textContent = "Edit entry";
  document.getElementById("modal-key").value = e.key;
  document.getElementById("f-name").value = e.name;
  document.getElementById("f-type").value = e.type || "character";
  document.getElementById("f-desc").value = e.description;
  document.getElementById("f-aliases").value = (e.aliases||[]).join(", ");
  document.getElementById("f-source").value = e.source_book || "";
  document.getElementById("modal").classList.add("open");
}

function closeModal() {
  document.getElementById("modal").classList.remove("open");
}
document.getElementById("modal").addEventListener("click", e => {
  if (e.target === document.getElementById("modal")) closeModal();
});

async function saveEntry() {
  const oldKey = document.getElementById("modal-key").value;
  const name   = document.getElementById("f-name").value.trim();
  if (!name) { toast("Name is required", true); return; }

  const payload = {
    old_key:     oldKey || null,
    name,
    type:        document.getElementById("f-type").value,
    description: document.getElementById("f-desc").value.trim(),
    aliases:     document.getElementById("f-aliases").value
                   .split(",").map(s => s.trim()).filter(Boolean),
    source_book: document.getElementById("f-source").value.trim(),
  };

  const res  = await fetch("/api/entries", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (data.ok) { closeModal(); toast(data.message); await loadEntries(); }
  else toast(data.error, true);
}

async function deleteEntry(key, name) {
  if (!confirm(`Delete "${name}"?`)) return;
  const res  = await fetch(`/api/entries/${encodeURIComponent(key)}`, { method: "DELETE" });
  const data = await res.json();
  if (data.ok) { toast(data.message); await loadEntries(); }
  else toast(data.error, true);
}

async function rebuild() {
  const btn = document.querySelector(".btn-secondary");
  btn.disabled = true;
  btn.textContent = "⚙ Building…";
  document.getElementById("rebuild-status").textContent = "Building…";

  const res  = await fetch("/api/rebuild", { method: "POST" });
  const data = await res.json();
  btn.disabled = false;
  btn.textContent = "⚙ Rebuild StarDict";

  if (data.ok) {
    document.getElementById("rebuild-status").textContent = data.message;
    toast("StarDict rebuilt successfully");
  } else {
    document.getElementById("rebuild-status").textContent = "Build failed";
    toast("Build failed: " + data.error, true);
  }
}

function esc(s) {
  return String(s||"")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

let toastTimer;
function toast(msg, isError=false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "show" + (isError ? " error" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.className = "", 3500);
}

loadEntries();
</script>
</body>
</html>"""


# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/entries")
def get_entries():
    master = load_master()
    entries = [{**e, "key": k} for k, e in master["entries"].items()]
    entries.sort(key=lambda e: e["name"].lower())
    return jsonify({
        "entries": entries,
        "books_processed": len(master.get("books_processed", [])),
    })


@app.route("/api/entries", methods=["POST"])
def save_entry():
    data    = request.json
    master  = load_master()
    name    = data.get("name", "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Name is required"})

    new_key = name.lower()
    old_key = data.get("old_key")

    if old_key and old_key != new_key and old_key in master["entries"]:
        del master["entries"][old_key]

    if not old_key and new_key in master["entries"]:
        return jsonify({"ok": False, "error": name + " already exists"})

    is_new = new_key not in master["entries"]
    master["entries"][new_key] = {
        "name":        name,
        "type":        data.get("type", "character"),
        "aliases":     data.get("aliases", []),
        "description": data.get("description", ""),
        "source_book": data.get("source_book", ""),
        "added":       master["entries"].get(new_key, {}).get("added")
                       or datetime.now().isoformat(timespec="seconds"),
    }
    save_master(master)
    verb = "Added" if is_new else "Updated"
    return jsonify({"ok": True, "message": verb + " " + name})


@app.route("/api/entries/<key>", methods=["DELETE"])
def delete_entry(key):
    master = load_master()
    if key not in master["entries"]:
        return jsonify({"ok": False, "error": "Entry not found"})
    name = master["entries"][key]["name"]
    del master["entries"][key]
    save_master(master)
    return jsonify({"ok": True, "message": "Deleted " + name})


@app.route("/api/rebuild", methods=["POST"])
def api_rebuild():
    ok, message = rebuild_stardict()
    return jsonify({"ok": ok, "message" if ok else "error": message})


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global OUTPUT_DIR, DICT_NAME, MASTER_JSON

    parser = argparse.ArgumentParser(description="Web UI for editing your noveldict master dictionary.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--dict-name",  default=DEFAULT_DICT_NAME)
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--host", default=str(DEFAULT_HOST))
    args = parser.parse_args()

    OUTPUT_DIR  = Path(args.output_dir)
    DICT_NAME   = args.dict_name
    MASTER_JSON = OUTPUT_DIR / "master_dictionary.json"

    if not MASTER_JSON.exists():
        print(f"Warning: {MASTER_JSON} not found — process some EPUBs first with noveldict.py")

    print(f"\n📖 noveldict editor")
    print(f"   Dictionary: {MASTER_JSON}")
    print(f"   Output:     {OUTPUT_DIR / DICT_NAME}/")
    print(f"\n   Open http://localhost:{args.port} in your browser\n")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
