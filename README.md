# noveldict

Build a personal **KOReader / StarDict dictionary** from your EPUB library using Claude AI.

Long-press any character name or fictional term while reading and get an instant description — without leaving your book.

![noveldict editor screenshot](docs/screenshot.png)

---

## What it does

- **Extracts** characters and world-building terms from EPUBs using Claude AI
- **Accumulates** a persistent cross-series master dictionary as you add books
- **Outputs** StarDict format compatible with KOReader on Kobo, Android, and desktop
- **Includes a web UI** for reviewing, editing, adding, and deleting entries
- **Costs ~$0.02–0.06 per book** using Claude Haiku

Great for dense sci-fi and fantasy series where you constantly forget who everyone is.

---

## Requirements

- Python 3.10+
- An [Anthropic API key](https://console.anthropic.com/) (Claude Haiku, ~$0.02–0.06/book)
- KOReader installed on your e-reader

---

## Installation

```bash
git clone https://github.com/yourname/noveldict.git
cd noveldict
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

Add the export to your `~/.zshrc` or `~/.bashrc` to make it permanent.

---

## Usage

### Process EPUBs

```bash
# Single book
python3 noveldict.py "Ancillary_Justice.epub"

# Multiple books
python3 noveldict.py book1.epub book2.epub book3.epub

# Whole series with glob
python3 noveldict.py ~/books/expanse/*.epub

# Custom output location and dictionary name
python3 noveldict.py --output-dir ~/dicts --dict-name "Expanse" book.epub

# Rebuild StarDict without re-extracting (e.g. after editing master JSON)
python3 noveldict.py --rebuild

# Re-process a book already in the processed list
python3 noveldict.py --reprocess book.epub
```

Output goes to `~/noveldict_output/` by default:

```
~/noveldict_output/
├── master_dictionary.json   ← persistent store of all entries
├── noveldict.log            ← full run log
└── Novels/
    ├── Novels.ifo
    ├── Novels.idx
    └── Novels.dict.dz       ← copy this folder to your reader
```

### Edit entries (web UI)

```bash
python3 noveldict_editor.py
# Open http://localhost:5001
```

Features:
- Filter by type (character / world term) and source book
- Edit names, descriptions, and aliases
- Add entries manually
- Delete entries
- Rebuild StarDict with one click

---

## Installing on KOReader (Kobo)

Connect your Kobo via USB, then copy the output folder:

```bash
cp -r ~/noveldict_output/Novels /Volumes/KOBOeReader/koreader/data/dict/
```

In KOReader: **long-press any word → tap the dictionary selector → choose Novels**.

To set it as the default, edit `/koreader/settings.reader.lua` and add your dictionary name to `dicts_order`:

```lua
["dicts_order"] = {"Novels", "English explanatory dictionary (main)"},
```

### Installing on KOReader (Android)

Copy the `Novels/` folder to:
```
/sdcard/koreader/data/dict/Novels/
```

### Installing on GoldenDict (desktop)

Add the `Novels/` folder as a dictionary source in GoldenDict preferences.

---

## macOS Automator app (drag-and-drop)

You can create a drag-and-drop app so you just drop EPUBs onto an icon:

1. Open **Automator** → New Document → **Application**
2. Add a **Run Shell Script** action
3. Set **Pass input** to **as arguments**
4. Paste the following script (update paths as needed):

```bash
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export ANTHROPIC_API_KEY="sk-ant-YOUR-KEY-HERE"

/opt/homebrew/bin/python3 /path/to/noveldict.py "$@" > /tmp/noveldict_log.txt 2>&1
exit_code=$?

summary_line=$(grep "^SUMMARY|" /tmp/noveldict_log.txt | tail -1)

if [ $exit_code -ne 0 ] || [ -z "$summary_line" ]; then
    osascript -e "tell app \"System Events\" to display dialog \"Error — check /tmp/noveldict_log.txt\" with title \"noveldict\" buttons {\"OK\"} default button \"OK\""
    exit 1
fi

IFS='|' read -r _ total new books outpath <<< "$summary_line"
msg="Dictionary updated.

Books: $books
New entries: $new
Total entries: $total"

osascript -e "tell app \"System Events\" to display dialog \"$msg\" with title \"noveldict\" buttons {\"OK\"} default button \"OK\""
```

5. **File → Save** as `noveldict.app`

---

## Configuration

Key constants at the top of `noveldict.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `MODEL` | `claude-haiku-4-5` | Claude model to use |
| `MAX_EXTRACT_CHARS` | `90000` | Characters of book text sent to Claude (~first 3–4 chapters) |
| `MAX_TOKENS` | `4096` | Max tokens in Claude's response |

Increasing `MAX_EXTRACT_CHARS` catches more characters but costs more. At 90,000 chars expect ~$0.04–0.06/book with Haiku.

---

## master_dictionary.json format

Plain JSON — easy to edit manually:

```json
{
  "entries": {
    "breq": {
      "name": "Breq",
      "type": "character",
      "aliases": ["Justice of Toren", "One Esk"],
      "description": "The sole surviving ancillary of the troop carrier Justice of Toren...",
      "source_book": "Ancillary Justice",
      "added": "2026-06-24T19:33:45"
    },
    "radch": {
      "name": "Radch",
      "type": "world_term",
      "aliases": ["Radchaai"],
      "description": "The empire that dominates human space...",
      "source_book": "Ancillary Justice",
      "added": "2026-06-24T19:33:45"
    }
  },
  "books_processed": [
    "Ancillary_Justice.epub"
  ]
}
```

---

## How it works

1. Unpacks the EPUB (it's a zip file)
2. Extracts text from spine documents
3. Sends the first `MAX_EXTRACT_CHARS` characters to Claude with a prompt asking for characters and world terms as JSON
4. Merges new entries into `master_dictionary.json` (existing entries are kept as-is)
5. Uses PyGlossary to build a StarDict `.ifo`/`.idx`/`.dict.dz` file

---

## Contributing

PRs welcome. Some ideas:
- Support for additional output formats (DictD, Babylon, EPUB dictionary)
- Series grouping in the editor UI
- Automatic Kobo sync via USB detection
- Support for other AI providers

---

## License

MIT
