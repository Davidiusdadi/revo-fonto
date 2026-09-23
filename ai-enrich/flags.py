#!/usr/bin/env python3
"""Things found wrong in passing, in one file outside every repo, the one REVO_FLAGS names.

  flags.py collect [--lng de]        merge the flags in ai-enrich results (holdout ones too), no duplicates
  flags.py add <article> <mrk> <lng> <kind> <text> <note> [--suggestion S] [--by David]
  flags.py list [--kind K] [--article A] [--lng L]
  flags.py summary

One line per finding: {at, by, article, mrk, lng, kind, text, note, suggestion?, evidence?}.
`by` is model and run tag for an agent's flag, or a person. Agents never write the file (parallel
runs would collide); their flags ride in the result files and `collect` brings them here. A
finding is the same one when article, mrk, lng, kind and text agree: collecting twice adds nothing.
The kinds are those of schemas/flag.json.
"""
import argparse, json, os, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# outside every checkout, so every worktree and run adds to the same file
FLAGS = Path(os.environ.get("REVO_FLAGS") or sys.exit("flags.py: set REVO_FLAGS to the flags file, a .jsonl outside the repo"))
KINDS = json.loads((HERE / "schemas" / "flag.json").read_text(encoding="utf-8"))["properties"]["kind"]["enum"]


def key(f):
    return (f["article"], f["mrk"], f["lng"], f["kind"], f["text"])


def read():
    if not FLAGS.exists():
        return []
    return [json.loads(line) for line in FLAGS.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(new):
    FLAGS.parent.mkdir(parents=True, exist_ok=True)
    with open(FLAGS, "a", encoding="utf-8") as f:
        for x in new:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")


def collect(a):
    seen = {key(f) for f in read()}
    new = []
    for lng in [a.lng] if a.lng else sorted(p.name for p in (HERE / "out").iterdir() if p.is_dir()):
        for results in (HERE / "out" / lng / "results", HERE / "out" / lng / "holdout" / "results"):
            for path in sorted(results.glob("*.json")):
                r = json.loads(path.read_text(encoding="utf-8"))
                for fl in r.get("flags", []):
                    f = {"at": r["saved"], "by": f'{r["model"]} {r["run"]} {r["stage"]}', "article": r["article"], **fl}
                    if key(f) not in seen:
                        seen.add(key(f))
                        new.append(f)
    append(new)
    print(f"{len(new)} new flags collected into {FLAGS}")


def add(a):
    f = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "by": a.by, "article": a.article,
         "mrk": a.mrk, "lng": a.lng, "kind": a.kind, "text": a.text, "note": a.note}
    if a.suggestion:
        f["suggestion"] = a.suggestion
    if key(f) in {key(x) for x in read()}:
        sys.exit("already flagged")
    append([f])
    print("flagged")


def show(a):
    for f in read():
        if (a.kind and f["kind"] != a.kind) or (a.article and f["article"] != a.article) or (a.lng and f["lng"] != a.lng):
            continue
        s = f" → {f['suggestion']}" if f.get("suggestion") else ""
        print(f'{f["kind"]:<18} {f["mrk"]:<26} {f["lng"]} {f["text"]!r}: {f["note"]}{s}  [{f["by"]}]')


def summary(_):
    fs = read()
    print(f"{len(fs)} flags in {len({f['article'] for f in fs})} articles")
    for k, n in Counter(f["kind"] for f in fs).most_common():
        print(f"  {k:<18} {n}")
    for b, n in Counter(f["by"] for f in fs).most_common():
        print(f"  by {b}: {n}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("--lng"); c.set_defaults(fn=collect)
    d = sub.add_parser("add")
    for x in ("article", "mrk", "lng"):
        d.add_argument(x)
    d.add_argument("kind", choices=KINDS)
    d.add_argument("text"); d.add_argument("note")
    d.add_argument("--suggestion"); d.add_argument("--by", default="David")
    d.set_defaults(fn=add)
    ls = sub.add_parser("list")
    ls.add_argument("--kind", choices=KINDS); ls.add_argument("--article"); ls.add_argument("--lng")
    ls.set_defaults(fn=show)
    sub.add_parser("summary").set_defaults(fn=summary)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
