#!/usr/bin/env python3
"""Every headword of the German and the English Wiktionary in its own language, for ask.py exists.

  headwords.py            -> <wikt data>/headwords.db  (from de-extract and en-extract, see wikt-enrich)

One row per page, part of speech and sense: the word, its part of speech, the sense's tags (register
and field, as Wiktionary writes them) and its gloss, shortened. An agent asks it whether a word it
proposes is a word at all, and what Wiktionary says it means; a missing word is not wrong, only
unconfirmed (compounds often have no page), and the checker then searches.
"""
import gzip, json, sqlite3, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "wikt-enrich" / "data"
OUT = DATA / "headwords.db"
SENSES = 4                                         # per word and part of speech


def rows(lng):
    with gzip.open(DATA / f"{lng}-extract.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("lang_code") != lng or not d.get("word"):
                continue
            for s in (d.get("senses") or [])[:SENSES]:
                gloss = "; ".join(s.get("glosses") or [])[:160]
                tags = " ".join(sorted(set(s.get("tags") or []) | set(s.get("raw_tags") or [])))[:120]
                if gloss or tags:
                    yield lng, d["word"], d.get("pos") or "", tags, gloss


def main():
    tmp = OUT.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.execute("CREATE TABLE headword (lng TEXT, word TEXT, pos TEXT, tags TEXT, gloss TEXT)")
    for lng in ("de", "en"):
        n = 0
        for batch in iter(lambda g=rows(lng): [r for _, r in zip(range(50000), g)], []):
            db.executemany("INSERT INTO headword VALUES (?,?,?,?,?)", batch)
            n += len(batch)
        print(lng, n, "senses", file=sys.stderr)
    db.execute("CREATE INDEX idx_headword ON headword(lng, word COLLATE NOCASE)")
    db.commit()
    db.close()
    tmp.replace(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
