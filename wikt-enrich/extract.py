"""wiktextract dumps -> eo_links_all.db

Keeps every translation-table row that lists an Esperanto word: one `pivot` row per
(Esperanto word x other-language word) sharing a sense of one source entry.

  WIKT_DATA=/path/to/dumps  extract.py de es en fr ...

Reads $WIKT_DATA/<edition>-extract.jsonl.gz, writes $WIKT_DATA/eo_links_all.db. Re-running an
edition replaces its rows.
"""
import gzip, json, os, sqlite3, sys
from pathlib import Path

DATA = Path(os.environ.get("WIKT_DATA", Path(__file__).resolve().parent / "data"))
db = sqlite3.connect(DATA / "eo_links_all.db")
db.execute("CREATE TABLE IF NOT EXISTS pivot(edition, src_lang, src_word, pos, sense_index, eo, lng, trd, lang_name)")
for ed in sys.argv[1:]:
    db.execute("DELETE FROM pivot WHERE edition=?", (ed,))
    n = 0
    with gzip.open(DATA / f"{ed}-extract.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if '"eo"' not in line:
                continue
            d = json.loads(line)
            lc, w, pos = d.get("lang_code"), d.get("word"), d.get("pos")
            if lc == "eo":
                continue
            trs = list(d.get("translations") or [])
            for s in d.get("senses", []):
                trs += s.get("translations") or []
            by = {}
            for t in trs:
                by.setdefault(str(t.get("sense_index") or t.get("sense") or ""), []).append(t)
            for si, ts in by.items():
                eos = {t["word"] for t in ts if t.get("lang_code") == "eo" and t.get("word")}
                if not eos:
                    continue
                rows = [(t.get("lang_code"), t["word"], t.get("lang")) for t in ts
                        if t.get("lang_code") not in (None, "eo") and t.get("word")]
                rows.append((lc, w, d.get("lang")))
                for eo in eos:
                    for l, trd, ln in rows:
                        db.execute("INSERT INTO pivot VALUES(?,?,?,?,?,?,?,?,?)", (ed, lc, w, pos, si, eo, l, trd, ln))
                        n += 1
    db.commit()
    print(ed, n, flush=True)
db.execute("CREATE INDEX IF NOT EXISTS p_eo ON pivot(eo,lng)")
