"""Update the translation files of MegaSpin and compile them.

Usage (from the megaspin folder, needs PySide6 with its Qt tools):

    python tools/update_translations.py            # all languages in translations/*.ts
    python tools/update_translations.py de         # only German
    python tools/update_translations.py fr         # new language: creates translations/megaspin_fr.ts

What it does:
1. lupdate scans src/megaspin for tr() calls and merges new/changed texts into megaspin_<lang>.ts
   (existing translations are kept).
2. All contexts are merged into one context "MegaSpin" (the runtime looks texts up in that context).
3. lrelease compiles megaspin_<lang>.ts into megaspin_<lang>.qm (the file the program loads).

Translators: open translations/megaspin_<lang>.ts with Qt Linguist (or any text editor), translate every
<translation type="unfinished"> entry and remove that attribute. Then run this script again.
"""
from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import PySide6

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "src" / "megaspin"
TR = SRC / "translations"
CONTEXT = "MegaSpin"
SOURCE_LANG = "en"
QT_BIN = Path(PySide6.__file__).resolve().parent


def tool(name: str) -> str:
    for cand in (QT_BIN / f"{name}.exe", QT_BIN / name):
        if cand.exists():
            return str(cand)
    raise SystemExit(f"{name} not found in {QT_BIN}")


def merge_contexts(ts_path: Path, lang: str) -> None:
    tree = ET.parse(ts_path)
    root = tree.getroot()
    seen: dict[str, ET.Element] = {}
    for ctx in root.findall("context"):
        for msg in ctx.findall("message"):
            src_el = msg.find("source")
            if src_el is None or src_el.text is None:
                continue
            key = src_el.text
            tr_el = msg.find("translation")
            text = (tr_el.text or "") if tr_el is not None else ""
            # keep the first entry, but prefer one that already has a translation
            if key not in seen:
                seen[key] = msg
            else:
                old_tr = seen[key].find("translation")
                old_text = (old_tr.text or "") if old_tr is not None else ""
                if not old_text and text:
                    seen[key] = msg
        root.remove(ctx)
    new_ctx = ET.SubElement(root, "context")
    ET.SubElement(new_ctx, "name").text = CONTEXT
    for key in sorted(seen, key=lambda s: s.lower()):
        msg = seen[key]
        for loc in msg.findall("location"):
            msg.remove(loc)
        new_ctx.append(msg)
    for msg in root.iter("message"):             # a non-empty translation counts as finished
        tr_el = msg.find("translation")
        if tr_el is not None and (tr_el.text or "").strip() and tr_el.get("type") == "unfinished":
            del tr_el.attrib["type"]
    root.set("language", lang)
    root.set("sourcelanguage", SOURCE_LANG)
    ET.indent(tree, space="    ")
    tree.write(ts_path, encoding="utf-8", xml_declaration=True)


def update(lang: str) -> None:
    ts = TR / f"megaspin_{lang}.ts"
    qm = TR / f"megaspin_{lang}.qm"
    TR.mkdir(exist_ok=True)
    sources = sorted(str(p) for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)
    subprocess.run([tool("lupdate"), *sources, "-ts", str(ts), "-source-language", SOURCE_LANG,
                    "-target-language", lang, "-no-obsolete"], check=True)
    merge_contexts(ts, lang)
    subprocess.run([tool("lrelease"), str(ts), "-qm", str(qm)], check=True)
    total = len(list(ET.parse(ts).getroot().iter("message")))
    open_ = sum(1 for t in ET.parse(ts).getroot().iter("translation")
                if t.get("type") == "unfinished" or not (t.text or "").strip())
    print(f"{lang}: {total} texts, {open_} unfinished -> {qm.name}")


if __name__ == "__main__":
    langs = sys.argv[1:] or sorted(p.stem.removeprefix("megaspin_") for p in TR.glob("megaspin_*.ts"))
    if not langs:
        langs = ["de"]
    for lang in langs:
        update(lang)
