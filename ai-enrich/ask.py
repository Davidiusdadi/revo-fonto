#!/usr/bin/env python3
"""The workflow agents' only tool besides reading their work file: short, fixed, read-only answers,
and the one write, their result.

  ask.py used <lng> <word>          which ReVo entries already carry this word as a translation
  ask.py exists <lng> <word>        is it a headword of that language's own Wiktionary, and as what
  ask.py entry <mrk>                a compact view of another entry or sense
  ask.py save <stage> <lng> <article> --run TAG --model M [--holdout] < result.json
                                    validate a propose/check result and write it (README, "Results")

`used` reads the enriched voko.db (revo-mcp's build; AI_DB overrides the path) opened read-only;
`exists` the headword table from headwords.py; `entry` the article XML. AI_OUT puts work files and
results in another folder than out/, so a second model can run the same articles apart. Every answer is a few lines,
so a question costs little and cannot flood an agent's context.
"""
import argparse, json, os, re, sqlite3, sys, time, unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = Path(os.environ.get("AI_DB", HERE.parent.parent.parent / "data" / "voko.db"))
HEADWORDS = HERE.parent / "wikt-enrich" / "data" / "headwords.db"
OUT = Path(os.environ.get("AI_OUT", HERE / "out"))
LIMIT = 12
MAJOR = ("de", "en", "fr", "es", "it", "pl", "ru", "nl", "pt", "la")


def ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def used(lng, word):
    db = ro(DB)
    rows = db.execute(
        """SELECT n.mrk, n.kind, h.txt, t.txt, COALESCE(t.fnt, '') FROM translation t
             JOIN node n ON n.id = t.node_id LEFT JOIN headword h ON h.id = n.kap_id
            WHERE t.lng = ? AND t.in_ekz = 0 AND (t.txt = ? COLLATE NOCASE OR t.ind = ? COLLATE NOCASE)
            ORDER BY t.fnt IS NOT NULL, n.id LIMIT ?""", (lng, word, word, LIMIT + 1)).fetchall()
    if not rows:
        return f"{lng} «{word}» translates no ReVo entry."
    out = [f"{lng} «{word}» translates:"]
    for mrk, kind, eo, txt, fnt in rows[:LIMIT]:
        where = "the whole entry" if kind in ("drv", "subdrv") else kind
        out.append(f"- {eo} ({mrk}, {where})" + (f" as «{txt}»" if txt.lower() != word.lower() else "")
                   + (f" [{fnt.split(';')[0]}]" if fnt else ""))
    if len(rows) > LIMIT:
        out.append("- … and more")
    return "\n".join(out)


def exists(lng, word):
    if not HEADWORDS.exists():
        return "The headword table is not built (headwords.py); decide without it."
    rows = ro(HEADWORDS).execute(
        "SELECT word, pos, tags, gloss FROM headword WHERE lng = ? AND word = ? COLLATE NOCASE LIMIT ?",
        (lng, word, LIMIT)).fetchall()
    if not rows:
        return (f"«{word}» has no page in the {lng} Wiktionary. That does not make it wrong (compounds "
                "often have none); it is only unconfirmed.")
    out = [f"«{word}» in the {lng} Wiktionary:"]
    for w, pos, tags, gloss in rows:
        out.append(f"- {w} ({pos})" + (f" [{tags}]" if tags else "") + (f": {gloss}" if gloss else ""))
    if lng == "zh" and all(pos == "soft-redirect" for _, pos, _, _ in rows):
        out.append("(a simplified form whose page points to the traditional one: ask for that)")
    return "\n".join(out)


def entry(mrk):
    sys.path.insert(0, str(HERE))
    from gaps import REVO, parser, read_article, by_lng
    path = REVO / f"{mrk.split('.')[0]}.xml"
    if not path.exists():
        return f"No article for {mrk}."
    for e in read_article(path, parser()):
        for node in [None, *e["senses"]]:
            if (node or e)["mrk"] != mrk and not (node is None and mrk == e["mrk"].split(".")[0]):
                continue
            ws = by_lng(node["below"] if node else e["all"], False)
            dif = (node or e)["dif"] or next((s["dif"] for s in e["senses"] if s["dif"]), "")
            out = [f"{e['eo']} ({mrk}): {dif[:300]}"]
            out += [f"- {l}: {', '.join(ws[l][:6])}" for l in MAJOR if l in ws]
            rest = sorted(set(ws) - set(MAJOR) - {"eo"})
            if rest:
                out.append(f"- also in: {' '.join(rest)}")
            if node is None and len(e["senses"]) > 1:
                out.append("- senses: " + "; ".join(f"{s['mrk']}: {s['dif'][:60]}" for s in e["senses"]))
            return "\n".join(out)
    return f"No entry or sense {mrk}."


def marks_of(work):
    """Every mrk the work file names: entries and their senses."""
    return {e["mrk"] for e in work["entries"]} | {s["mrk"] for e in work["entries"] for s in e["senses"]}


def save(a):
    from jsonschema import Draft202012Validator
    from jsonschema.validators import RefResolver
    base = OUT / a.lng / ("holdout" if a.holdout else "")
    work = json.loads((base / "work" / f"{a.article}.json").read_text(encoding="utf-8"))
    schema = json.loads((HERE / "schemas" / f"{a.stage}.json").read_text(encoding="utf-8"))
    resolver = RefResolver(base_uri=(HERE / "schemas").as_uri() + "/", referrer=schema)
    try:
        result = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        return f"Not saved: the input is not JSON ({e})."
    errors = [f"{'/'.join(map(str, e.path)) or '(top)'}: {e.message}"
              for e in Draft202012Validator(schema, resolver=resolver).iter_errors(result)]
    known = marks_of(work)
    # a flag may concern any entry (a linked one, say), so only the items it decides on are checked here
    items = [*result.get("definitions", []), *result.get("proposals", []), *result.get("covered", []),
             *result.get("verdicts", [])]
    errors += [f"mrk {x['mrk']} is not in the work file" for x in items if isinstance(x, dict)
               and x.get("mrk") not in known and x.get("mrk") != a.article]
    if a.lng == "zh":                           # ReVo writes both scripts, each with its pinyin
        for x in [*result.get("proposals", []), *result.get("verdicts", [])]:
            if not isinstance(x, dict):
                continue
            if a.stage == "propose" and not (x.get("pinyin") and x.get("traditional")):
                errors.append(f"{x.get('mrk')} «{x.get('word')}»: a Chinese word needs traditional and pinyin")
            bare = "".join(c for c in unicodedata.normalize("NFD", x.get("pinyin") or "") if not unicodedata.combining(c))
            if x.get("pinyin") and not re.fullmatch(r"[a-zA-Z' ]+", bare):
                errors.append(f"{x.get('mrk')} «{x.get('word')}»: pinyin «{x['pinyin']}» is not pinyin with tone marks")
    if a.stage == "check":
        prop = base / "results" / f"{a.article}.propose.json"
        if not prop.exists():
            errors.append("there is no proposal for this article to check")
        else:
            proposed = json.loads(prop.read_text(encoding="utf-8"))
            want = {(p["mrk"], p["word"]) for p in proposed["proposals"]}
            got = {(v["mrk"], v["word"]) for v in result.get("verdicts", [])}
            errors += [f"no verdict on {m} «{w}»" for m, w in sorted(want - got)]
            errors += [f"verdict on {m} «{w}», which was not proposed" for m, w in sorted(got - want)]
            want_d = {d["mrk"] for d in proposed["definitions"]}
            got_d = {d["mrk"] for d in result.get("definitions", [])}
            errors += [f"no verdict on the definition of {m}" for m in sorted(want_d - got_d)]
    if errors:
        return "Not saved; fix these and save again:\n" + "\n".join(f"- {e}" for e in errors[:20])
    result = {"article": a.article, "lng": a.lng, "stage": a.stage, "run": a.run, "model": a.model,
              "work_sha": work["sha"], "saved": time.strftime("%Y-%m-%dT%H:%M:%S"), **result}
    out = base / "results" / f"{a.article}.{a.stage}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {k: len(v) for k, v in result.items() if isinstance(v, list)}
    return f"Saved {out.relative_to(HERE)}: " + ", ".join(f"{k} {n}" for k, n in counts.items())


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("used", "exists"):
        s = sub.add_parser(name)
        s.add_argument("lng")
        s.add_argument("word", nargs="+")
    sub.add_parser("entry").add_argument("mrk")
    s = sub.add_parser("save")
    s.add_argument("stage", choices=("propose", "check"))
    s.add_argument("lng")
    s.add_argument("article")
    s.add_argument("--run", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--holdout", action="store_true")
    a = ap.parse_args()
    if a.cmd == "used":
        print(used(a.lng, " ".join(a.word)))
    elif a.cmd == "exists":
        print(exists(a.lng, " ".join(a.word)))
    elif a.cmd == "entry":
        print(entry(a.mrk))
    else:
        msg = save(a)
        print(msg)
        sys.exit(0 if msg.startswith("Saved") else 1)


if __name__ == "__main__":
    main()
