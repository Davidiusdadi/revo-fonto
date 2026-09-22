#!/usr/bin/env python3
"""The register tags a Wiktionary edition puts on the senses of its own language's words.

  WIKT_DATA=/path/to/dumps  sense_tags.py de     -> $WIKT_DATA/sense_tags.de.json

{word: [[sense_index, [tag, ...]], ...]}, one item per sense of every section of the page (a page
with a noun and a verb section has two senses numbered 1). Only tags that marks.toml maps are
kept, so an empty list means "this sense is neutral". packets.py turns them into marks.
"""
import gzip, json, os, sys, tomllib
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("WIKT_DATA", HERE / "data"))
KNOWN = {t for m in tomllib.load(open(HERE / "marks.toml", "rb"))["mark"].values() for t in m["tags"]}

for lng in sys.argv[1:]:
    pages = defaultdict(list)
    with gzip.open(DATA / f"{lng}-extract.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if f'"lang_code": "{lng}"' not in line:
                continue
            d = json.loads(line)
            if d.get("lang_code") != lng or not d.get("word"):
                continue
            for i, s in enumerate(d.get("senses", []), 1):
                if "form-of" in (s.get("tags") or []):
                    continue
                pages[d["word"]].append([str(s.get("sense_index") or i), sorted(KNOWN & set(s.get("tags") or []))])
    out = DATA / f"sense_tags.{lng}.json"
    out.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    print(out, len(pages), "pages,", sum(1 for p in pages.values() for _, t in p if t), "tagged senses")
