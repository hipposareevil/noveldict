#!/usr/bin/env python3
"""
noveldict — Build a KOReader/StarDict dictionary from your EPUB library.

Extracts characters and world-building terms from EPUBs using Claude AI,
maintains a persistent cross-series master dictionary, and outputs StarDict
format compatible with KOReader on Kobo, Android, and desktop readers.

Usage:
    noveldict.py book.epub
    noveldict.py book1.epub book2.epub book3.epub
    noveldict.py ~/books/series/*.epub
    noveldict.py --rebuild          # Rebuild StarDict without re-extracting
    noveldict.py --output-dir ~/mydict --dict-name "SciFi"

Requirements:
    pip install anthropic beautifulsoup4 lxml pyglossary
    ANTHROPIC_API_KEY environment variable must be set.

Installing on KOReader (Kobo):
    Copy the output folder to:
    /koreader/data/dict/<DictName>/
    Then long-press any word → select your dictionary.
"""

import sys
import os
import re
import json
import zipfile
import tempfile
import argparse
import logging
from datetime import datetime
from pathlib import Path

import anthropic
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from pyglossary import Glossary


# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_OUTPUT_DIR  = Path.home() / "noveldict_output"
DEFAULT_DICT_NAME   = "Novels"
MODEL               = "claude-haiku-4-5"
MAX_TOKENS          = 4096
MAX_EXTRACT_CHARS   = 90_000    # ~first 3-4 chapters; enough for major characters


# ── Logging ───────────────────────────────────────────────────────────────────

def setup_logging(output_dir: Path) -> logging.Logger:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "noveldict.log"

    logger = logging.getLogger("noveldict")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


# ── EPUB helpers ──────────────────────────────────────────────────────────────

def find_opf(unpacked: Path) -> Path:
    container = unpacked / "META-INF" / "container.xml"
    soup = BeautifulSoup(container.read_text(encoding="utf-8"), "xml")
    rootfile = soup.find("rootfile")
    if not rootfile:
        raise RuntimeError("Cannot find rootfile in container.xml")
    return unpacked / rootfile["full-path"]


def get_book_metadata(opf: Path) -> tuple[str, str]:
    soup = BeautifulSoup(opf.read_text(encoding="utf-8"), "xml")
    title   = soup.find("dc:title")
    creator = soup.find("dc:creator")
    return (
        title.get_text(strip=True)   if title   else "Unknown",
        creator.get_text(strip=True) if creator else "Unknown",
    )


def spine_documents(opf: Path) -> list[Path]:
    opf_dir = opf.parent
    soup = BeautifulSoup(opf.read_text(encoding="utf-8"), "xml")
    manifest = {item["id"]: item.get("href", "")
                for item in soup.find("manifest").find_all("item")}
    docs = []
    for itemref in soup.find("spine").find_all("itemref"):
        href = manifest.get(itemref["idref"], "")
        if href.lower().endswith((".xhtml", ".html", ".htm")):
            docs.append(opf_dir / href)
    return docs


def extract_text(docs: list[Path]) -> str:
    parts = []
    for path in docs:
        if path.exists():
            soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
            parts.append(soup.get_text(separator=" ", strip=True))
    return "\n\n".join(parts)


# ── Claude extraction ─────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a literary analyst. Given the opening portion of a novel,
extract two categories of entries for a reader's reference dictionary:

1. CHARACTERS — significant named people/beings with meaningful page presence
2. WORLD TERMS — invented words, places, factions, organisations, technology,
   or concepts specific to this fictional universe (e.g. "Radch", "ancillary",
   "ansible", "the Imperium"). Skip real-world words found in a standard dictionary.

For each entry write a short spoiler-free description (1-3 sentences).
Base descriptions ONLY on what is established in the provided text.
Do NOT reveal plot twists, deaths, or late revelations.

Return ONLY valid JSON — no markdown fences, no preamble, no commentary.

Format:
[
  {
    "name": "Canonical Name or Term",
    "type": "character",
    "aliases": ["Alt Name", "Nickname"],
    "description": "Short description here."
  },
  {
    "name": "WorldTerm",
    "type": "world_term",
    "aliases": ["variant"],
    "description": "What this term means in this fictional universe."
  }
]

Order by importance/prominence. Skip one-line mentions."""


def call_claude(text: str, logger: logging.Logger) -> list[dict]:
    client = anthropic.Anthropic()

    if len(text) > MAX_EXTRACT_CHARS:
        logger.info(f"  Capping input at {MAX_EXTRACT_CHARS:,} chars "
                    f"(of {len(text):,}) to control cost")
        text = text[:MAX_EXTRACT_CHARS]

    logger.info(f"  Sending {len(text):,} chars (~{len(text)//4:,} tokens) to Claude")

    last_err = None
    response = None
    for attempt in range(1, 4):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"Novel text:\n\n{text}"}],
            )
            break
        except Exception as e:
            last_err = e
            logger.warning(f"  API attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                import time
                time.sleep(5 * attempt)

    if response is None:
        raise RuntimeError(f"API failed after 3 attempts: {last_err}")

    logger.debug(f"  Stop reason: {response.stop_reason}")

    if not response.content:
        raise RuntimeError("Claude returned empty response")

    raw = response.content[0].text.strip()
    if not raw:
        raise RuntimeError(f"Claude returned blank response (stop_reason={response.stop_reason})")

    # Extract JSON array — handles preamble text and markdown fences
    json_match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not json_match:
        logger.error(f"Raw response (first 500 chars):\n{raw[:500]}")
        raise RuntimeError("No JSON array found in Claude response")

    entries = json.loads(json_match.group(0))
    chars = sum(1 for e in entries if e.get("type") == "character")
    terms = sum(1 for e in entries if e.get("type") == "world_term")
    logger.info(f"  Extracted {len(entries)} entries ({chars} characters, {terms} world terms)")
    return entries


# ── Master dictionary ─────────────────────────────────────────────────────────

def load_master(master_json: Path, logger: logging.Logger) -> dict:
    if master_json.exists():
        data = json.loads(master_json.read_text(encoding="utf-8"))
        logger.info(f"Loaded master dictionary: {len(data['entries'])} existing entries")
        return data
    logger.info("No master dictionary found — starting fresh")
    return {"entries": {}, "books_processed": []}


def save_master(data: dict, master_json: Path, logger: logging.Logger):
    master_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.debug(f"Saved master dictionary ({len(data['entries'])} entries)")


def merge_entries(master: dict, new_entries: list[dict],
                  book_title: str, logger: logging.Logger) -> tuple[int, int]:
    """Merge new entries into master. Keep existing descriptions. Returns (added, skipped)."""
    added = skipped = 0
    for entry in new_entries:
        name = entry.get("name", "").strip()
        if not name:
            continue
        key = name.lower()
        if key in master["entries"]:
            logger.debug(f"  Keeping existing: {name}")
            skipped += 1
        else:
            master["entries"][key] = {
                "name":        name,
                "type":        entry.get("type", "character"),
                "aliases":     [a.strip() for a in entry.get("aliases", []) if a.strip()],
                "description": entry.get("description", "").strip(),
                "source_book": book_title,
                "added":       datetime.now().isoformat(timespec="seconds"),
            }
            logger.info(f"  + [{entry.get('type', 'character'):10s}] {name}")
            added += 1
    return added, skipped


# ── StarDict generation ───────────────────────────────────────────────────────

def generate_stardict(master: dict, output_dir: Path,
                      dict_name: str, logger: logging.Logger):
    """Build a StarDict dictionary from master entries using PyGlossary."""
    Glossary.init()
    glos = Glossary()
    glos.setInfo("title", dict_name)
    glos.setInfo("description", "Characters and world terms extracted from novels")
    glos.setInfo("author", "noveldict")

    entries_sorted = sorted(master["entries"].values(), key=lambda e: e["name"].lower())
    logger.info(f"Building StarDict from {len(entries_sorted)} entries...")

    for entry in entries_sorted:
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

    star_dir = output_dir / dict_name
    star_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(star_dir / dict_name)

    logger.info(f"Writing StarDict to {star_dir}...")
    glos.write(out_path, format="Stardict", dictzip=True)

    total_kb = sum(f.stat().st_size for f in star_dir.iterdir()) / 1024
    logger.info(f"Done: {star_dir.name}/ ({total_kb:.1f} KB total)")
    for f in sorted(star_dir.iterdir()):
        logger.info(f"  {f.name}  ({f.stat().st_size / 1024:.1f} KB)")


# ── Process one EPUB ──────────────────────────────────────────────────────────

def process_epub(epub_path: Path, master: dict, logger: logging.Logger) -> dict:
    logger.info("=" * 60)
    logger.info(f"Processing: {epub_path.name}")

    summary = {
        "file": epub_path.name, "title": "", "author": "",
        "added": 0, "skipped": 0, "error": None,
    }

    try:
        with tempfile.TemporaryDirectory() as tmp:
            unpacked = Path(tmp) / "unpacked"
            unpacked.mkdir()
            with zipfile.ZipFile(epub_path, "r") as z:
                z.extractall(unpacked)

            opf = find_opf(unpacked)
            title, author = get_book_metadata(opf)
            summary["title"]  = title
            summary["author"] = author
            logger.info(f"  Title:  {title}")
            logger.info(f"  Author: {author}")

            docs = spine_documents(opf)
            logger.info(f"  Spine documents: {len(docs)}")

            text = extract_text(docs)
            logger.info(f"  Total text: {len(text):,} chars")

            new_entries = call_claude(text, logger)
            added, skipped = merge_entries(master, new_entries, title, logger)
            summary["added"]   = added
            summary["skipped"] = skipped
            logger.info(f"  Result: {added} new, {skipped} already existed")

    except Exception as e:
        logger.error(f"  ERROR: {e}", exc_info=True)
        summary["error"] = str(e)

    return summary


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Build a KOReader/StarDict dictionary from EPUB files using Claude AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  noveldict.py book.epub
  noveldict.py series/*.epub
  noveldict.py --dict-name "Expanse" --output-dir ~/dicts book.epub
  noveldict.py --rebuild

Installing on KOReader (Kobo):
  Copy the output/<DictName>/ folder to:
  /koreader/data/dict/<DictName>/
  Then long-press any word and select your dictionary.
        """
    )
    parser.add_argument("epubs", nargs="*", help="EPUB file(s) to process")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR),
                        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})")
    parser.add_argument("--dict-name", default=DEFAULT_DICT_NAME,
                        help=f"Dictionary name shown in KOReader (default: {DEFAULT_DICT_NAME})")
    parser.add_argument("--rebuild", action="store_true",
                        help="Rebuild StarDict from existing master JSON without re-extracting")
    parser.add_argument("--reprocess", action="store_true",
                        help="Re-extract even books already in books_processed list")
    args = parser.parse_args()

    output_dir  = Path(args.output_dir)
    dict_name   = args.dict_name
    master_json = output_dir / "master_dictionary.json"

    logger = setup_logging(output_dir)
    logger.info("=" * 60)
    logger.info(f"noveldict  started  {datetime.now().isoformat(timespec='seconds')}")
    logger.info(f"Output dir: {output_dir}")
    logger.info(f"Dictionary: {dict_name}")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    master = load_master(master_json, logger)
    summaries = []

    if not args.rebuild:
        if not args.epubs:
            logger.error("No EPUB files specified. Pass EPUBs as arguments or use --rebuild.")
            sys.exit(1)

        for epub_arg in args.epubs:
            epub_path = Path(epub_arg)
            if not epub_path.exists():
                logger.error(f"File not found: {epub_path}")
                continue
            if epub_path.suffix.lower() != ".epub":
                logger.warning(f"Skipping non-EPUB: {epub_path.name}")
                continue

            already_done = epub_path.name in master.get("books_processed", [])
            if already_done and not args.reprocess:
                logger.info(f"Already processed: {epub_path.name} (use --reprocess to force)")
                summaries.append({
                    "file": epub_path.name, "title": "", "author": "",
                    "added": 0, "skipped": 0, "error": "already processed"
                })
                continue

            summary = process_epub(epub_path, master, logger)
            summaries.append(summary)

            if not summary["error"]:
                books = master.setdefault("books_processed", [])
                if epub_path.name not in books:
                    books.append(epub_path.name)
                save_master(master, master_json, logger)

    # Rebuild StarDict
    logger.info("=" * 60)
    logger.info(f"Building StarDict from {len(master['entries'])} total entries...")
    try:
        generate_stardict(master, output_dir, dict_name, logger)
    except Exception as e:
        logger.error(f"StarDict generation failed: {e}", exc_info=True)
        sys.exit(1)

    # Summary
    logger.info("=" * 60)
    logger.info("SUMMARY")
    total_added = total_skipped = 0
    for s in summaries:
        if s.get("error") == "already processed":
            logger.info(f"  {s['file']}: skipped (already processed)")
        elif s.get("error"):
            logger.info(f"  {s['file']}: ERROR — {s['error']}")
        else:
            logger.info(f"  {s['file']}: +{s['added']} new, {s['skipped']} existing")
        total_added   += s.get("added", 0)
        total_skipped += s.get("skipped", 0)

    star_dir = output_dir / dict_name
    logger.info(f"  Total entries in dictionary: {len(master['entries'])}")
    logger.info(f"  New entries this run:        {total_added}")
    logger.info(f"  Dictionary output:           {star_dir}/")
    logger.info(f"  Master JSON:                 {master_json}")
    logger.info(f"  Log:                         {output_dir / 'noveldict.log'}")
    logger.info("=" * 60)

    # Machine-readable line for Automator/shell scripts
    books = [s.get("title") or s["file"] for s in summaries
             if s.get("error") not in ("already processed", ) and not s.get("error")]
    print(f"SUMMARY|{len(master['entries'])}|{total_added}|{','.join(books)}|{star_dir}")


if __name__ == "__main__":
    main()
