#!/usr/bin/env python3
"""Every headword of the German and the English Wiktionary in its own language, for ask.py exists.

  headwords.py            -> <wikt data>/headwords.db  (from de-extract and en-extract, see wikt-enrich)
  headwords.py zh         replace just these languages' rows in the existing table

Chinese comes from both the zh and the en edition (en.wiktionary covers Chinese far more fully);
its tags carry the pinyin, so `exists` also confirms a reading.

One row per page, part of speech and sense: the word, its part of speech, the sense's tags (register
and field, as Wiktionary writes them) and its gloss, shortened. An agent asks it whether a word it
proposes is a word at all, and what Wiktionary says it means; a missing word is not wrong, only
unconfirmed (compounds often have no page), and the checker then searches.
"""
import gzip, json, shutil, sqlite3, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "wikt-enrich" / "data"
OUT = DATA / "headwords.db"
SENSES = 4                                         # per word and part of speech


DUMPS = {"de": ("de",), "en": ("en",), "zh": ("zh", "en")}


def pinyin(d):
    return next((s["zh_pron"].split(" (")[0] for s in d.get("sounds", []) if {"Mandarin", "Pinyin"} <= set(s.get("tags", []))
                 and set(s.get("tags", [])) & {"Standard", "Standard-Chinese"} and s.get("zh_pron")), "")


def rows(lng):
    for dump in DUMPS[lng]:
        with gzip.open(DATA / f"{dump}-extract.jsonl.gz", "rt", encoding="utf-8") as f:
            for line in f:
                if f'"lang_code": "{lng}"' not in line:
                    continue
                d = json.loads(line)
                if d.get("lang_code") != lng or not d.get("word"):
                    continue
                py = pinyin(d) if lng == "zh" else ""
                for s in (d.get("senses") or [])[:SENSES]:
                    gloss = "; ".join(s.get("glosses") or [])[:160]
                    tags = " ".join(sorted(set(s.get("tags") or []) | set(s.get("raw_tags") or [])))[:120]
                    tags = f"{py} {tags}".strip() if py else tags
                    if gloss or tags:
                        yield lng, d["word"], d.get("pos") or "", tags, gloss


def main():
    only = sys.argv[1:]
    tmp = OUT.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    if only:                                      # add or replace these languages in a copy of the table
        shutil.copyfile(OUT, tmp)
        db = sqlite3.connect(tmp)
        db.executemany("DELETE FROM headword WHERE lng = ?", [(l,) for l in only])
    else:
        db = sqlite3.connect(tmp)
        db.execute("CREATE TABLE headword (lng TEXT, word TEXT, pos TEXT, tags TEXT, gloss TEXT)")
    for lng in only or ("de", "en"):
        n = 0
        for batch in iter(lambda g=rows(lng): [r for _, r in zip(range(50000), g)], []):
            db.executemany("INSERT INTO headword VALUES (?,?,?,?,?)", batch)
            n += len(batch)
        print(lng, n, "senses", file=sys.stderr)
    db.execute("CREATE INDEX IF NOT EXISTS idx_headword ON headword(lng, word COLLATE NOCASE)")
    db.commit()
    db.close()
    tmp.replace(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
